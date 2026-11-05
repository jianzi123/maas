package mysqlstore

import (
	"context"
	"database/sql"
	"errors"
	"regexp"
	"sort"

	"github.com/google/uuid"
	"github.com/jianzi123/maas/internal/release"
)

var dnsLabel = regexp.MustCompile(`^[a-z0-9]([-a-z0-9]*[a-z0-9])?$`)
var aliasPattern = regexp.MustCompile(`^[A-Za-z0-9][A-Za-z0-9._-]*$`)

func validateDesired(d release.Desired) error {
	if !validID(d.CRUID) || d.Generation < 1 || d.Generation > maxCounter || !digestPattern.MatchString(d.Revision) || len(d.Namespace) > 63 || len(d.Name) > 63 || len(d.Gateway.Name) > 63 || !dnsLabel.MatchString(d.Namespace) || !dnsLabel.MatchString(d.Name) || !dnsLabel.MatchString(d.Gateway.Name) || !aliasPattern.MatchString(d.Alias) || len(d.Alias) > 64 {
		return release.ErrConflict
	}
	return nil
}
func mode(d release.Desired) string {
	if d.Deleting {
		return "Deleting"
	}
	if d.Paused {
		return "Paused"
	}
	return "Published"
}
func (s *Store) claim(ctx context.Context, tx *sql.Tx, l link) error {
	if _, err := tx.ExecContext(ctx, `INSERT IGNORE INTO active_model_bindings(cluster_id,gateway,model_alias,cr_uid) VALUES(?,?,?,?)`, s.cluster, l.gateway, l.alias, l.uid); err != nil {
		return err
	}
	var owner string
	if err := tx.QueryRowContext(ctx, `SELECT cr_uid FROM active_model_bindings WHERE cluster_id=? AND gateway=? AND model_alias=? FOR UPDATE NOWAIT`, s.cluster, l.gateway, l.alias).Scan(&owner); err != nil {
		return err
	}
	if owner != l.uid {
		return release.ErrConflict
	}
	return nil
}
func (s *Store) close(ctx context.Context, tx *sql.Tx, l *link, target *string) error {
	if target != nil {
		p, err := s.publication(ctx, tx, *target)
		if err != nil {
			return err
		}
		if p.CRUID != l.uid {
			return release.ErrConflict
		}
		if _, err = tx.ExecContext(ctx, `UPDATE publications SET state='Closed' WHERE cluster_id=? AND publication_id=? AND state IN ('Active','Candidate','Draining')`, s.cluster, *target); err != nil {
			return err
		}
		if _, err = tx.ExecContext(ctx, `UPDATE active_model_bindings SET admission_closed=TRUE WHERE cluster_id=? AND cr_uid=? AND publication_id=?`, s.cluster, l.uid, *target); err != nil {
			return err
		}
		if l.active.Valid && l.active.String == *target {
			l.closed = true
		}
	} else {
		if _, err := tx.ExecContext(ctx, `UPDATE publications SET state='Closed' WHERE cluster_id=? AND cr_uid=? AND state IN ('Active','Candidate','Draining')`, s.cluster, l.uid); err != nil {
			return err
		}
		if _, err := tx.ExecContext(ctx, `UPDATE active_model_bindings SET admission_closed=TRUE WHERE cluster_id=? AND cr_uid=?`, s.cluster, l.uid); err != nil {
			return err
		}
		l.closed = true
	}
	return nil
}
func (s *Store) Observe(ctx context.Context, d release.Desired) (release.State, error) {
	if err := validateCapture(d); err != nil {
		return release.State{}, err
	}
	if err := validateDesired(d); err != nil {
		return release.State{}, err
	}
	var out release.State
	err := s.transaction(ctx, func(tx *sql.Tx) error {
		l, err := s.lock(ctx, tx, d.CRUID, "FOR UPDATE NOWAIT")
		created := false
		if errors.Is(err, sql.ErrNoRows) {
			l = link{uid: d.CRUID, namespace: d.Namespace, name: d.Name, gateway: d.Gateway.Name, alias: d.Alias, revision: d.Revision, mode: mode(d), intent: release.Hash(d), generation: d.Generation, fence: 1, closed: true}
			_, err = tx.ExecContext(ctx, `INSERT INTO release_links(cluster_id,cr_uid,namespace,name,gateway,model_alias,revision,desired_mode,intent_sha256,last_observed_generation,reconcile_epoch) VALUES(?,?,?,?,?,?,?,?,?,?,?)`, s.cluster, l.uid, l.namespace, l.name, l.gateway, l.alias, l.revision, l.mode, l.intent, l.generation, l.fence)
			created = true
		}
		if err != nil {
			return err
		}
		if l.namespace != d.Namespace || l.name != d.Name || l.alias != d.Alias || d.Generation < l.generation || (l.tombstone && !d.Deleting) {
			return release.ErrConflict
		}
		if !created && d.Generation == l.generation && mode(d) != l.mode && !d.Deleting {
			return release.ErrConflict
		}
		changed := created || l.intent != release.Hash(d)
		if !changed && l.candidate.Valid && l.mode == "Published" {
			p, err := s.publication(ctx, tx, l.candidate.String)
			if err != nil {
				return err
			}
			// An already activated publication is never resurrected after gate closure.
			if p.State == "Closed" || p.State == "Cleaned" {
				changed = true
			}
		}
		if changed {
			if !created {
				if l.fence == maxCounter {
					return release.ErrConflict
				}
				l.fence++
			}
			l.generation = d.Generation
			l.intent = release.Hash(d)
			l.gateway = d.Gateway.Name
			l.mode = mode(d)
			l.cleaned = false
			if !l.tombstone {
				if err = s.claim(ctx, tx, l); err != nil {
					return err
				}
			}
			if l.mode == "Published" {
				if l.epoch == maxCounter {
					return release.ErrConflict
				}
				if l.candidate.Valid && (!l.active.Valid || l.candidate.String != l.active.String) {
					if _, err = tx.ExecContext(ctx, `UPDATE publications SET state='Closed' WHERE cluster_id=? AND publication_id=? AND state='Candidate'`, s.cluster, l.candidate.String); err != nil {
						return err
					}
				}
				l.epoch++
				l.revision = d.Revision
				l.candidate = sql.NullString{String: uuid.NewString(), Valid: true}
				inserted, insertErr := tx.ExecContext(ctx, `INSERT IGNORE INTO release_revisions(cluster_id,cr_uid,revision) VALUES(?,?,?)`, s.cluster, l.uid, l.revision)
				err = insertErr
				if err != nil {
					return err
				}
				count, _ := inserted.RowsAffected()
				if err = s.capture(ctx, tx, d, count == 1); err != nil {
					return err
				}
				if _, err = tx.ExecContext(ctx, `INSERT INTO publications(cluster_id,publication_id,cr_uid,generation,revision,activation_epoch,gateway,state) VALUES(?,?,?,?,?,?,?,'Candidate')`, s.cluster, l.candidate.String, l.uid, l.generation, l.revision, l.epoch, l.gateway); err != nil {
					return err
				}
			} else {
				if l.mode == "Deleting" {
					l.tombstone = true
				}
				if err = s.close(ctx, tx, &l, nil); err != nil {
					return err
				}
			}
			if _, err = tx.ExecContext(ctx, `INSERT INTO publish_intents(cluster_id,cr_uid,reconcile_epoch,intent_sha256) VALUES(?,?,?,?)`, s.cluster, l.uid, l.fence, l.intent); err != nil {
				return err
			}
			if err = s.save(ctx, tx, l); err != nil {
				return err
			}
		}
		out, err = s.state(ctx, tx, l)
		return err
	})
	return out, err
}

func equalNullable(v sql.NullString, w *string) bool {
	return (!v.Valid && w == nil) || (v.Valid && w != nil && v.String == *w)
}
func (s *Store) Apply(ctx context.Context, c release.Command) error {
	if err := release.ValidateCommand(c); err != nil {
		return err
	}
	return s.transaction(ctx, func(tx *sql.Tx) error {
		l, err := s.lock(ctx, tx, c.CRUID, "FOR UPDATE NOWAIT")
		if err != nil {
			return err
		}
		var oldUID, oldHash string
		err = tx.QueryRowContext(ctx, `SELECT cr_uid,command_sha256 FROM release_operations WHERE cluster_id=? AND command_id=?`, s.cluster, c.ID).Scan(&oldUID, &oldHash)
		if err == nil {
			if oldUID != c.CRUID || oldHash != release.Hash(c) {
				return release.ErrConflict
			}
			return nil
		}
		if !errors.Is(err, sql.ErrNoRows) {
			return err
		}
		if c.Generation != l.generation || c.Fence != l.fence || c.Revision != l.revision || !equalNullable(l.active, c.ExpectedActive) {
			return release.ErrConflict
		}
		switch c.Action {
		case "Activate":
			if err = s.activate(ctx, tx, &l, c); err != nil {
				return err
			}
		case "CloseAdmission":
			if err = s.close(ctx, tx, &l, c.Target); err != nil {
				return err
			}
		case "RecordCleanup":
			if err = s.recordCleanup(ctx, tx, &l); err != nil {
				return err
			}
		default:
			// Preparation is Observe; H1-H4/validation are not implemented by inventing
			// a receipt or dispatching a supplier request from this adapter.
			return release.ErrDependencyMissing
		}
		if err = s.save(ctx, tx, l); err != nil {
			return err
		}
		_, err = tx.ExecContext(ctx, `INSERT INTO release_operations(cluster_id,command_id,cr_uid,action,command_sha256) VALUES(?,?,?,?,?)`, s.cluster, c.ID, c.CRUID, c.Action, release.Hash(c))
		if err != nil {
			return err
		}
		if c.Action == "Activate" {
			// Independent, post-write DB clock/evidence check immediately before
			// commit; do not rely on a timestamp from before possible lock waits.
			p, err := s.publication(ctx, tx, *c.Target)
			if err != nil {
				return err
			}
			e, err := s.evidence(ctx, tx, p)
			if err != nil {
				return err
			}
			if !e.RuntimeReady || !e.GatewayApplied || !e.AccountingReady || !e.ValidationPassed || !sameRefs(c.EvidenceRefs, e.Refs) {
				return release.ErrDependencyMissing
			}
		}
		return nil
	})
}
func (s *Store) activate(ctx context.Context, tx *sql.Tx, l *link, c release.Command) error {
	if l.tombstone || l.mode != "Published" || c.Target == nil || !l.candidate.Valid || *c.Target != l.candidate.String {
		return release.ErrConflict
	}
	p, err := s.publication(ctx, tx, *c.Target)
	if err != nil {
		return err
	}
	if p.CRUID != l.uid || p.Generation != l.generation || p.Revision != l.revision || p.Epoch != l.epoch || p.State != "Candidate" || p.Activated {
		return release.ErrConflict
	}
	e, err := s.evidence(ctx, tx, p)
	if err != nil {
		return err
	}
	if !e.RuntimeReady || !e.GatewayApplied || !e.AccountingReady || !e.ValidationPassed {
		return release.ErrDependencyMissing
	}
	if !sameRefs(c.EvidenceRefs, e.Refs) {
		return release.ErrConflict
	}
	if l.active.Valid {
		if _, err = tx.ExecContext(ctx, `UPDATE publications SET state='Draining' WHERE cluster_id=? AND publication_id=? AND state='Active'`, s.cluster, l.active.String); err != nil {
			return err
		}
	}
	if _, err = tx.ExecContext(ctx, `UPDATE active_model_bindings SET admission_closed=TRUE WHERE cluster_id=? AND cr_uid=?`, s.cluster, l.uid); err != nil {
		return err
	}
	result, err := tx.ExecContext(ctx, `UPDATE publications SET state='Active',activated=TRUE WHERE cluster_id=? AND publication_id=? AND state='Candidate' AND activated=FALSE`, s.cluster, p.PublicationID)
	if err != nil {
		return err
	}
	if n, err := result.RowsAffected(); err != nil {
		return err
	} else if n != 1 {
		return release.ErrConflict
	}
	result, err = tx.ExecContext(ctx, `UPDATE active_model_bindings SET publication_id=?,admission_closed=FALSE WHERE cluster_id=? AND gateway=? AND model_alias=? AND cr_uid=?`, p.PublicationID, s.cluster, p.Gateway, l.alias, l.uid)
	if err != nil {
		return err
	}
	if n, err := result.RowsAffected(); err != nil {
		return err
	} else if n != 1 {
		return release.ErrConflict
	}
	l.active = sql.NullString{String: p.PublicationID, Valid: true}
	l.closed = false
	return nil
}
func sameRefs(a, b []string) bool {
	a = append([]string{}, a...)
	b = append([]string{}, b...)
	sort.Strings(a)
	sort.Strings(b)
	if len(a) != len(b) {
		return false
	}
	for i := range a {
		if a[i] != b[i] {
			return false
		}
	}
	return true
}
func (s *Store) drain(ctx context.Context, tx *sql.Tx, l link, pub string) (bool, error) {
	if s.kernel == nil {
		return false, release.ErrDependencyMissing
	}
	pubs, err := s.publications(ctx, tx, l.uid, pub)
	if err != nil {
		return false, err
	}
	if pub != "" && len(pubs) != 1 {
		return false, release.ErrOwnership
	}
	ids := []string{}
	for _, p := range pubs {
		if p.State == "Candidate" || p.State == "Active" {
			return false, nil
		}
		ids = append(ids, p.PublicationID)
	}
	proof, err := s.kernel.DrainEvidence(ctx, tx, l.uid, pubs)
	if err != nil {
		return false, err
	}
	now, err := dbNow(ctx, tx)
	if err != nil {
		return false, err
	}
	return proof.CRUID == l.uid && proof.Verified && sameRefs(proof.Publications, ids) && now.Before(proof.FreshUntil) && proof.InProgress == 0 && proof.HeldSlots == 0 && proof.QuarantinedSlots == 0, nil
}
func (s *Store) Drain(ctx context.Context, uid, pub string) (bool, error) {
	if !validID(uid) || (pub != "" && !validID(pub)) {
		return false, release.ErrConflict
	}
	safe := false
	err := s.transaction(ctx, func(tx *sql.Tx) error {
		l, err := s.lock(ctx, tx, uid, "FOR UPDATE NOWAIT")
		if err != nil {
			return err
		}
		safe, err = s.drain(ctx, tx, l, pub)
		return err
	})
	return safe, err
}
func (s *Store) recordCleanup(ctx context.Context, tx *sql.Tx, l *link) error {
	if !l.closed || (l.mode != "Paused" && l.mode != "Deleting") {
		return release.ErrConflict
	}
	safe, err := s.drain(ctx, tx, *l, "")
	if err != nil {
		return err
	}
	if !safe {
		return release.ErrConflict
	}
	var remaining int
	if err = tx.QueryRowContext(ctx, `SELECT COUNT(*) FROM resource_inventory WHERE cluster_id=? AND cr_uid=? AND state<>'Removed'`, s.cluster, l.uid).Scan(&remaining); err != nil {
		return err
	}
	if remaining != 0 {
		return release.ErrConflict
	}
	if _, err = tx.ExecContext(ctx, `UPDATE publications SET state='Cleaned' WHERE cluster_id=? AND cr_uid=? AND state IN ('Closed','Draining')`, s.cluster, l.uid); err != nil {
		return err
	}
	if l.tombstone {
		if _, err = tx.ExecContext(ctx, `DELETE FROM active_model_bindings WHERE cluster_id=? AND cr_uid=?`, s.cluster, l.uid); err != nil {
			return err
		}
	}
	l.cleaned = true
	return nil
}

// LockActive is the release gate inside the SINGLE core admission transaction.
// The caller owns commit/rollback and subsequently performs its existing Key,
// budget, request and slot operations. This method writes none of those tables.
// It cannot authorize a request by itself and is not an HTTP inference endpoint.
// The core caller must hold its original exclusive capacity guard before calling.
func (s *Store) LockActive(ctx context.Context, tx *sql.Tx, uid string) (release.Binding, error) {
	if s.kernel == nil || tx == nil {
		return release.Binding{}, release.ErrDependencyMissing
	}
	if err := s.kernel.LockCapacity(ctx, tx); err != nil {
		return release.Binding{}, publicError(err)
	}
	l, err := s.lock(ctx, tx, uid, "FOR SHARE NOWAIT")
	if err != nil {
		return release.Binding{}, publicError(err)
	}
	if l.tombstone || l.mode != "Published" || l.closed || !l.active.Valid {
		return release.Binding{}, release.ErrConflict
	}
	p, err := s.publication(ctx, tx, l.active.String)
	if err != nil {
		return release.Binding{}, publicError(err)
	}
	if p.State != "Active" || !p.Activated || p.CRUID != uid {
		return release.Binding{}, release.ErrConflict
	}
	var owner string
	var active sql.NullString
	var closed bool
	if err = tx.QueryRowContext(ctx, `SELECT cr_uid,publication_id,admission_closed FROM active_model_bindings WHERE cluster_id=? AND gateway=? AND model_alias=? FOR SHARE NOWAIT`, s.cluster, p.Gateway, l.alias).Scan(&owner, &active, &closed); err != nil {
		return release.Binding{}, publicError(err)
	}
	if owner != uid || closed || !active.Valid || active.String != p.PublicationID {
		return release.Binding{}, release.ErrConflict
	}
	e, err := s.evidence(ctx, tx, p)
	if err != nil {
		return release.Binding{}, publicError(err)
	}
	if !e.RuntimeReady || !e.GatewayApplied || !e.AccountingReady || !e.ValidationPassed {
		return release.Binding{}, release.ErrDependencyMissing
	}
	return p.Binding, nil
}
