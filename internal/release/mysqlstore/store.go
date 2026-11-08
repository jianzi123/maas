// Package mysqlstore implements release state only. It owns no Key, request,
// budget, terminal event or slot ledger. The operator binary does not wire this
// adapter until the real core/evidence/gateway integrations are approved.
package mysqlstore

import (
	"context"
	"database/sql"
	"errors"
	"regexp"
	"time"

	"github.com/go-sql-driver/mysql"
	"github.com/google/uuid"
	"github.com/jianzi123/maas/internal/release"
	"github.com/jianzi123/maas/internal/release/management"
)

var ErrUnavailable = errors.New("release storage unavailable")
var ErrCommitUnknown = errors.New("release commit outcome unknown; read durable state before retry")

const maxCounter = int64(9007199254740991)

var digestPattern = regexp.MustCompile(`^[0-9a-f]{64}$`)

// Kernel is implemented by the existing Go admission/evidence module, never by
// the operator or a diagnostic observer. Every method uses this SAME primary DB
// transaction; no Redis, RPC, K8s or supplier IO may run while locks are held.
// LockCapacity takes a shared lock on the v0.3 capacity guard FIRST (NOWAIT),
// blocking the core's exclusive allocation/recovery lock without needing core
// UPDATE privileges. Then this package locks the release row. A core caller of
// LockActive must ALREADY own its normal exclusive capacity lock; its later
// Key/budget/request/slot lock ordering and unique admission transaction remain.
type Kernel interface {
	LockCapacity(context.Context, *sql.Tx) error
	PublicationEvidence(context.Context, *sql.Tx, Publication) (Evidence, error)
	DrainEvidence(context.Context, *sql.Tx, string, []Publication) (DrainEvidence, error)
}
type Evidence struct {
	Binding                                                         release.Binding
	CRUID                                                           string
	FreshUntil                                                      time.Time
	RuntimeReady, GatewayApplied, AccountingReady, ValidationPassed bool
	Refs                                                            []string
}
type DrainEvidence struct {
	CRUID string
	// Exact publication set, including old/closed revisions; no aggregate model
	// count may stand in for the immutable invocation/slot bindings.
	Publications                            []string
	FreshUntil                              time.Time
	Verified                                bool
	InProgress, HeldSlots, QuarantinedSlots int64
}
type Publication struct {
	release.Binding
	CRUID, Gateway, State string
	Activated             bool
}
type Store struct {
	db                   *sql.DB
	cluster              string
	kernel               Kernel
	managementOperations bool
}

// WithManagementOperations opts this publisher into atomic operation completion.
// Its role additionally needs the documented narrow operation projection grants.
func (s *Store) WithManagementOperations() *Store {
	out := *s
	out.managementOperations = true
	return &out
}

func New(db *sql.DB, cluster string, k Kernel) (*Store, error) {
	if db == nil || !regexp.MustCompile(`^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$`).MatchString(cluster) {
		return nil, release.ErrDependencyMissing
	}
	return &Store{db: db, cluster: cluster, kernel: k}, nil
}

var _ release.Control = (*Store)(nil)
var _ release.Inventory = (*Store)(nil)

func validID(s string) bool { v, e := uuid.Parse(s); return e == nil && v.String() == s }
func publicError(err error) error {
	if err == nil {
		return nil
	}
	for _, known := range []error{release.ErrConflict, release.ErrOwnership, release.ErrDependencyMissing, ErrCommitUnknown, ErrUnavailable} {
		if errors.Is(err, known) {
			return known
		}
	}
	var m *mysql.MySQLError
	if errors.As(err, &m) && (m.Number == 1062 || m.Number == 1205 || m.Number == 1213 || m.Number == 3572) {
		return release.ErrConflict
	}
	// Raw SQL/DSN/driver errors can contain connection identifiers or user data.
	return ErrUnavailable
}
func (s *Store) transaction(ctx context.Context, fn func(*sql.Tx) error) error {
	tx, err := s.db.BeginTx(ctx, &sql.TxOptions{Isolation: sql.LevelReadCommitted})
	if err != nil {
		return publicError(err)
	}
	defer tx.Rollback()
	if s.kernel != nil {
		if err = s.kernel.LockCapacity(ctx, tx); err != nil {
			return publicError(err)
		}
	}
	if err = fn(tx); err != nil {
		return publicError(err)
	}
	if err = tx.Commit(); err != nil {
		return ErrCommitUnknown
	}
	return nil
}

type link struct {
	uid, namespace, name, gateway, alias, revision, mode, intent string
	generation, fence, epoch                                     int64
	candidate, active                                            sql.NullString
	closed, tombstone, cleaned                                   bool
}

const linkColumns = "cr_uid,namespace,name,gateway,model_alias,revision,desired_mode,intent_sha256,last_observed_generation,reconcile_epoch,activation_epoch,candidate_id,active_id,admission_closed,tombstone,cleanup_complete"

func (s *Store) lock(ctx context.Context, tx *sql.Tx, uid, lockMode string) (link, error) {
	var l link
	err := tx.QueryRowContext(ctx, "SELECT "+linkColumns+" FROM release_links WHERE cluster_id=? AND cr_uid=? "+lockMode, s.cluster, uid).Scan(&l.uid, &l.namespace, &l.name, &l.gateway, &l.alias, &l.revision, &l.mode, &l.intent, &l.generation, &l.fence, &l.epoch, &l.candidate, &l.active, &l.closed, &l.tombstone, &l.cleaned)
	return l, err
}
func (s *Store) save(ctx context.Context, tx *sql.Tx, l link) error {
	_, err := tx.ExecContext(ctx, `UPDATE release_links SET gateway=?,revision=?,desired_mode=?,intent_sha256=?,last_observed_generation=?,reconcile_epoch=?,activation_epoch=?,candidate_id=?,active_id=?,admission_closed=?,tombstone=?,cleanup_complete=? WHERE cluster_id=? AND cr_uid=?`, l.gateway, l.revision, l.mode, l.intent, l.generation, l.fence, l.epoch, l.candidate, l.active, l.closed, l.tombstone, l.cleaned, s.cluster, l.uid)
	if err == nil && s.managementOperations {
		return management.CompleteInTransaction(ctx, tx, s.cluster, l.uid)
	}
	return err
}
func (s *Store) publication(ctx context.Context, tx *sql.Tx, id string) (Publication, error) {
	var p Publication
	err := tx.QueryRowContext(ctx, `SELECT publication_id,cr_uid,generation,revision,activation_epoch,gateway,state,activated FROM publications WHERE cluster_id=? AND publication_id=?`, s.cluster, id).Scan(&p.PublicationID, &p.CRUID, &p.Generation, &p.Revision, &p.Epoch, &p.Gateway, &p.State, &p.Activated)
	return p, err
}
func (s *Store) publications(ctx context.Context, tx *sql.Tx, uid, pub string) ([]Publication, error) {
	q := `SELECT publication_id,cr_uid,generation,revision,activation_epoch,gateway,state,activated FROM publications WHERE cluster_id=? AND cr_uid=?`
	args := []any{s.cluster, uid}
	if pub != "" {
		q += " AND publication_id=?"
		args = append(args, pub)
	}
	q += " ORDER BY activation_epoch"
	rows, err := tx.QueryContext(ctx, q, args...)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	out := []Publication{}
	for rows.Next() {
		var p Publication
		if err = rows.Scan(&p.PublicationID, &p.CRUID, &p.Generation, &p.Revision, &p.Epoch, &p.Gateway, &p.State, &p.Activated); err != nil {
			return nil, err
		}
		out = append(out, p)
	}
	return out, rows.Err()
}
func dbNow(ctx context.Context, tx *sql.Tx) (time.Time, error) {
	var now time.Time
	err := tx.QueryRowContext(ctx, "SELECT UTC_TIMESTAMP(6)").Scan(&now)
	return now, err
}
func (s *Store) evidence(ctx context.Context, tx *sql.Tx, p Publication) (Evidence, error) {
	if s.kernel == nil {
		return Evidence{}, release.ErrDependencyMissing
	}
	e, err := s.kernel.PublicationEvidence(ctx, tx, p)
	if err != nil {
		return Evidence{}, err
	}
	now, err := dbNow(ctx, tx)
	if err != nil {
		return Evidence{}, err
	}
	if e.CRUID != p.CRUID || e.Binding != p.Binding || !now.Before(e.FreshUntil) || len(e.Refs) == 0 || len(e.Refs) > 32 {
		return Evidence{}, release.ErrDependencyMissing
	}
	for _, ref := range e.Refs {
		if !validID(ref) {
			return Evidence{}, release.ErrDependencyMissing
		}
	}
	return e, nil
}
func (s *Store) state(ctx context.Context, tx *sql.Tx, l link) (release.State, error) {
	out := release.State{CRUID: l.uid, Generation: l.generation, Fence: l.fence, Revision: l.revision, AdmissionClosed: l.closed, Tombstone: l.tombstone, EvidenceRefs: []string{}, Draining: []release.Binding{}}
	pubs, err := s.publications(ctx, tx, l.uid, "")
	if err != nil {
		return out, err
	}
	for _, p := range pubs {
		b := p.Binding
		if l.candidate.Valid && p.PublicationID == l.candidate.String {
			out.Candidate = &b
			if p.State == "Candidate" || p.State == "Active" {
				e, eErr := s.evidence(ctx, tx, p)
				if eErr == nil {
					out.RuntimeReady = e.RuntimeReady
					out.GatewayApplied = e.GatewayApplied
					out.AccountingReady = e.AccountingReady
					out.ValidationPassed = e.ValidationPassed
					out.EvidenceRefs = e.Refs
				} else if !errors.Is(eErr, release.ErrDependencyMissing) {
					return out, eErr
				}
			}
		}
		if l.active.Valid && p.PublicationID == l.active.String {
			active := p.Binding
			out.Active = &active
		}
		// Includes superseded candidates whose partial inventory must be recovered.
		if (p.State == "Draining" || p.State == "Closed") && (!l.candidate.Valid || p.PublicationID != l.candidate.String) {
			out.Draining = append(out.Draining, p.Binding)
		}
	}
	return out, nil
}
func (s *Store) Read(ctx context.Context, uid string) (release.State, error) {
	if !validID(uid) {
		return release.State{}, release.ErrConflict
	}
	var out release.State
	err := s.transaction(ctx, func(tx *sql.Tx) error {
		l, err := s.lock(ctx, tx, uid, "FOR SHARE NOWAIT")
		if err != nil {
			return err
		}
		out, err = s.state(ctx, tx, l)
		return err
	})
	return out, err
}
