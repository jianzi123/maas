package mysqlstore

import (
	"bytes"
	"context"
	"crypto/sha256"
	"database/sql"
	_ "embed"
	"encoding/hex"
	"encoding/json"
	"errors"
	api "github.com/jianzi123/maas/api/v1alpha1"
	"github.com/jianzi123/maas/internal/release"
	"strings"
)

//go:embed schema/0002_history.sql
var historyMigration string

func migrateHistory(ctx context.Context, db *sql.DB) error {
	c, e := db.Conn(ctx)
	if e != nil {
		return publicError(e)
	}
	defer c.Close()
	var schema string
	if e = c.QueryRowContext(ctx, "SELECT DATABASE()").Scan(&schema); e != nil {
		return ErrUnavailable
	}
	lock := "maas-release:" + release.Hash(schema)[:40]
	var n int
	if e = c.QueryRowContext(ctx, "SELECT GET_LOCK(?,0)", lock).Scan(&n); e != nil || n != 1 {
		return release.ErrConflict
	}
	defer c.ExecContext(context.Background(), "SELECT RELEASE_LOCK(?)", lock)
	digest := sha256.Sum256([]byte(historyMigration))
	want := hex.EncodeToString(digest[:])
	var prior, state string
	e = c.QueryRowContext(ctx, "SELECT sha256,state FROM release_schema_migrations WHERE version=2").Scan(&prior, &state)
	if e == nil {
		if prior != want {
			return release.ErrConflict
		}
		if state == "Applied" {
			return nil
		}
	} else if errors.Is(e, sql.ErrNoRows) {
		if e = c.QueryRowContext(ctx, "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=DATABASE() AND table_name='retained_release_snapshots'").Scan(&n); e != nil {
			return publicError(e)
		}
		if n != 0 {
			return release.ErrConflict
		}
		if _, e = c.ExecContext(ctx, "INSERT INTO release_schema_migrations VALUES(2,?,'Applying')", want); e != nil {
			return publicError(e)
		}
	} else {
		return publicError(e)
	}
	for _, q := range strings.Split(historyMigration, ";") {
		if strings.TrimSpace(q) != "" {
			if _, e = c.ExecContext(ctx, q); e != nil {
				return publicError(e)
			}
		}
	}
	_, e = c.ExecContext(ctx, "UPDATE release_schema_migrations SET state='Applied' WHERE version=2")
	return publicError(e)
}
func validateCapture(d release.Desired) error {
	if d.History == nil {
		return nil
	}
	h := d.History
	if h.ResourceVersion == "" || len(h.ResourceVersion) > 128 || d.Paused || d.Deleting || api.Validate(h.Spec, nil) != nil || h.Spec.ModelAlias != d.Alias || h.Spec.GatewayRef != d.Gateway || release.Revision(h.Spec, h.Resolution) != d.Revision {
		return release.ErrConflict
	}
	b, _ := json.Marshal(h.Spec)
	if len(b) > 65535 {
		return release.ErrConflict
	}
	return nil
}
func (s *Store) capture(ctx context.Context, tx *sql.Tx, d release.Desired, newRevision bool) error {
	if d.History == nil {
		return nil
	}
	b, _ := json.Marshal(d.History.Spec)
	var previous []byte
	e := tx.QueryRowContext(ctx, "SELECT spec_bytes FROM retained_release_snapshots WHERE cluster_id=? AND cr_uid=? AND revision=?", s.cluster, d.CRUID, d.Revision).Scan(&previous)
	if e == nil {
		if !bytes.Equal(previous, b) {
			return release.ErrConflict
		}
		return nil
	}
	if !errors.Is(e, sql.ErrNoRows) {
		return e
	}
	// A pre-existing hash without trusted capture time/spec is legacy. Do NOT
	// adopt the current CR as an invented historical snapshot or reset its date.
	if !newRevision {
		return nil
	}
	t, e := dbNow(ctx, tx)
	if e != nil {
		return e
	}
	sum := sha256.Sum256(b)
	_, e = tx.ExecContext(ctx, `INSERT INTO retained_release_snapshots(cluster_id,cr_uid,revision,namespace,name,generation,model_alias,source_type,spec_bytes,spec_sha256,source_resource_version,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)`, s.cluster, d.CRUID, d.Revision, d.Namespace, d.Name, d.Generation, d.Alias, d.History.Spec.Source.Type, b, hex.EncodeToString(sum[:]), d.History.ResourceVersion, t)
	return e
}
