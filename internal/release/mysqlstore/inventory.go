package mysqlstore

import (
	"context"
	"database/sql"
	"errors"

	"github.com/jianzi123/maas/internal/release"
)

var exclusiveKinds = map[string]bool{
	"networking.k8s.io/v1/Ingress": true, "extensions.higress.io/v1alpha1/WasmPlugin": true,
	"leaderworkerset.x-k8s.io/v1/LeaderWorkerSet": true, "v1/Service": true,
	"v1/ConfigMap": true, "networking.k8s.io/v1/NetworkPolicy": true,
}

func validateEntry(e release.Entry) error {
	if !validID(e.Owner) || !validID(e.Publication) || !digestPattern.MatchString(e.Digest) || !exclusiveKinds[e.Ref.APIVersion+"/"+e.Ref.Kind] || e.Ref.Ownership != "exclusive" || e.Ref.PublicationID == nil || *e.Ref.PublicationID != e.Publication || len(e.Ref.Name) > 63 || len(e.Ref.Namespace) > 63 || !dnsLabel.MatchString(e.Ref.Name) || !dnsLabel.MatchString(e.Ref.Namespace) || (e.Ref.UID != "" && !validID(e.Ref.UID)) {
		return release.ErrOwnership
	}
	return nil
}
func (s *Store) resourceKey(e release.Entry) string {
	return release.Hash([]string{s.cluster, e.Ref.APIVersion, e.Ref.Kind, e.Ref.Namespace, e.Ref.Name})
}

type inventoryRow struct {
	entry release.Entry
	state string
}

func (s *Store) inventory(ctx context.Context, tx *sql.Tx, key string) (inventoryRow, error) {
	var r inventoryRow
	var uid sql.NullString
	err := tx.QueryRowContext(ctx, `SELECT cr_uid,publication_id,api_version,kind,namespace,name,object_uid,desired_sha256,state FROM resource_inventory WHERE cluster_id=? AND resource_key=? FOR UPDATE NOWAIT`, s.cluster, key).Scan(&r.entry.Owner, &r.entry.Publication, &r.entry.Ref.APIVersion, &r.entry.Ref.Kind, &r.entry.Ref.Namespace, &r.entry.Ref.Name, &uid, &r.entry.Digest, &r.state)
	r.entry.Ref.UID = uid.String
	r.entry.Ref.Ownership = "exclusive"
	r.entry.Ref.PublicationID = &r.entry.Publication
	r.entry.Retiring = r.state == "Retiring"
	return r, err
}
func identity(a, b release.Entry) bool {
	return a.Owner == b.Owner && a.Publication == b.Publication && a.Ref.APIVersion == b.Ref.APIVersion && a.Ref.Kind == b.Ref.Kind && a.Ref.Namespace == b.Ref.Namespace && a.Ref.Name == b.Ref.Name && a.Digest == b.Digest
}
func (s *Store) Intent(ctx context.Context, e release.Entry) error {
	if err := validateEntry(e); err != nil {
		return err
	}
	return s.transaction(ctx, func(tx *sql.Tx) error {
		l, err := s.lock(ctx, tx, e.Owner, "FOR UPDATE NOWAIT")
		if err != nil {
			return err
		}
		p, err := s.publication(ctx, tx, e.Publication)
		if err != nil {
			return err
		}
		if l.tombstone || l.mode != "Published" || p.CRUID != l.uid || (p.State != "Candidate" && p.State != "Active") || ((!l.candidate.Valid || l.candidate.String != p.PublicationID) && (!l.active.Valid || l.active.String != p.PublicationID)) {
			return release.ErrConflict
		}
		key := s.resourceKey(e)
		old, err := s.inventory(ctx, tx, key)
		if err == nil {
			if !identity(old.entry, e) {
				return release.ErrOwnership
			}
			if old.state == "Retiring" || old.state == "Removed" {
				return release.ErrConflict
			}
			return nil
		}
		if !errors.Is(err, sql.ErrNoRows) {
			return err
		}
		// Intent never binds a caller-supplied UID. Only the post-create Bind may do so.
		_, err = tx.ExecContext(ctx, `INSERT INTO resource_inventory(cluster_id,resource_key,cr_uid,publication_id,api_version,kind,namespace,name,desired_sha256,state) VALUES(?,?,?,?,?,?,?,?,?,'Planned')`, s.cluster, key, e.Owner, e.Publication, e.Ref.APIVersion, e.Ref.Kind, e.Ref.Namespace, e.Ref.Name, e.Digest)
		return err
	})
}
func (s *Store) Bind(ctx context.Context, e release.Entry) error {
	if err := validateEntry(e); err != nil {
		return err
	}
	if !validID(e.Ref.UID) {
		return release.ErrOwnership
	}
	return s.transaction(ctx, func(tx *sql.Tx) error {
		if _, err := s.lock(ctx, tx, e.Owner, "FOR UPDATE NOWAIT"); err != nil {
			return err
		}
		old, err := s.inventory(ctx, tx, s.resourceKey(e))
		if err != nil {
			return err
		}
		if !identity(old.entry, e) || (old.entry.Ref.UID != "" && old.entry.Ref.UID != e.Ref.UID) {
			return release.ErrOwnership
		}
		if old.state == "Retiring" || old.state == "Removed" {
			return release.ErrConflict
		}
		_, err = tx.ExecContext(ctx, `UPDATE resource_inventory SET object_uid=?,state='Bound' WHERE cluster_id=? AND resource_key=? AND (object_uid IS NULL OR object_uid=?) AND state IN ('Planned','Bound')`, e.Ref.UID, s.cluster, s.resourceKey(e), e.Ref.UID)
		return err
	})
}
func (s *Store) List(ctx context.Context, owner, pub string) ([]release.Entry, error) {
	if !validID(owner) || (pub != "" && !validID(pub)) {
		return nil, release.ErrOwnership
	}
	out := []release.Entry{}
	err := s.transaction(ctx, func(tx *sql.Tx) error {
		if _, err := s.lock(ctx, tx, owner, "FOR SHARE NOWAIT"); err != nil {
			return err
		}
		q := `SELECT publication_id,api_version,kind,namespace,name,object_uid,desired_sha256,state FROM resource_inventory WHERE cluster_id=? AND cr_uid=? AND state<>'Removed'`
		args := []any{s.cluster, owner}
		if pub != "" {
			q += " AND publication_id=?"
			args = append(args, pub)
		}
		q += " ORDER BY resource_key"
		rows, err := tx.QueryContext(ctx, q, args...)
		if err != nil {
			return err
		}
		defer rows.Close()
		for rows.Next() {
			e := release.Entry{Owner: owner}
			var uid sql.NullString
			var state string
			if err = rows.Scan(&e.Publication, &e.Ref.APIVersion, &e.Ref.Kind, &e.Ref.Namespace, &e.Ref.Name, &uid, &e.Digest, &state); err != nil {
				return err
			}
			e.Ref.UID = uid.String
			e.Ref.Ownership = "exclusive"
			publication := e.Publication
			e.Ref.PublicationID = &publication
			e.Retiring = state == "Retiring"
			out = append(out, e)
		}
		return rows.Err()
	})
	return out, err
}
func (s *Store) Retire(ctx context.Context, e release.Entry) error {
	if err := validateEntry(e); err != nil {
		return err
	}
	return s.transaction(ctx, func(tx *sql.Tx) error {
		l, err := s.lock(ctx, tx, e.Owner, "FOR UPDATE NOWAIT")
		if err != nil {
			return err
		}
		// Recheck the live core state inside this transaction; a prior Drain result
		// is not a permit, and inventory cannot decide slot safety on its own.
		safe, err := s.drain(ctx, tx, l, e.Publication)
		if err != nil {
			return err
		}
		if !safe {
			return release.ErrConflict
		}
		old, err := s.inventory(ctx, tx, s.resourceKey(e))
		if err != nil {
			return err
		}
		if !identity(old.entry, e) || old.entry.Ref.UID != e.Ref.UID {
			return release.ErrOwnership
		}
		if old.state == "Removed" {
			return nil
		}
		_, err = tx.ExecContext(ctx, `UPDATE resource_inventory SET state='Retiring' WHERE cluster_id=? AND resource_key=? AND state IN ('Planned','Bound','Retiring')`, s.cluster, s.resourceKey(e))
		return err
	})
}
func (s *Store) Removed(ctx context.Context, e release.Entry) error {
	if err := validateEntry(e); err != nil {
		return err
	}
	return s.transaction(ctx, func(tx *sql.Tx) error {
		l, err := s.lock(ctx, tx, e.Owner, "FOR UPDATE NOWAIT")
		if err != nil {
			return err
		}
		safe, err := s.drain(ctx, tx, l, e.Publication)
		if err != nil {
			return err
		}
		if !safe {
			return release.ErrConflict
		}
		old, err := s.inventory(ctx, tx, s.resourceKey(e))
		if err != nil {
			return err
		}
		if !identity(old.entry, e) || old.entry.Ref.UID != e.Ref.UID {
			return release.ErrOwnership
		}
		if old.state == "Removed" {
			return nil
		}
		if old.state != "Retiring" {
			return release.ErrConflict
		}
		_, err = tx.ExecContext(ctx, `UPDATE resource_inventory SET state='Removed' WHERE cluster_id=? AND resource_key=? AND state='Retiring'`, s.cluster, s.resourceKey(e))
		return err
	})
}

// A runtime instance shared by multiple publications requires the future
// runtime_instances/runtime_refs adapter. This implementation rejects reuse of
// an inventory key across publications; it cannot retire a shared runtime by
// pretending its reference count is zero. ExternalAPI objects are exclusive.
