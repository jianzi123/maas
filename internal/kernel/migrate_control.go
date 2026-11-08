package kernel

import (
	"context"
	"crypto/sha256"
	"database/sql"
	_ "embed"
	"errors"
	"fmt"
	"strings"
)

//go:embed schema/0002_control.sql
var controlMigration string

func migrateControl(ctx context.Context, db *sql.DB) error {
	if e := migrateExtra(ctx, db, 2, controlMigration, "'key_metadata','rate_rebuilds','publication_proofs','validation_intents','validation_receipts'"); e != nil {
		return e
	}
	return migrateExtra(ctx, db, 3, diagnosticMigration, "'request_snapshot_digests','diagnostic_policy','request_usage_diagnostics'")
}
func migrateExtra(ctx context.Context, db *sql.DB, version int, migration, tables string) error {
	c, e := db.Conn(ctx)
	if e != nil {
		return sanitize(e)
	}
	defer c.Close()
	var n int
	if e = c.QueryRowContext(ctx, "SELECT GET_LOCK(CONCAT('maas-kernel:',DATABASE()),0)").Scan(&n); e != nil || n != 1 {
		return ErrBusy
	}
	defer c.ExecContext(context.Background(), "SELECT RELEASE_LOCK(CONCAT('maas-kernel:',DATABASE()))")
	want := fmt.Sprintf("%x", sha256.Sum256([]byte(migration)))
	var digest, state string
	e = c.QueryRowContext(ctx, "SELECT sha256,state FROM kernel_schema_migrations WHERE version=?", version).Scan(&digest, &state)
	if e == nil {
		if digest != want {
			return ErrConflict
		}
		if state == "Applied" {
			return nil
		}
	} else if errors.Is(e, sql.ErrNoRows) {
		if e = c.QueryRowContext(ctx, "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=DATABASE() AND table_name IN ("+tables+")").Scan(&n); e != nil {
			return sanitize(e)
		}
		if n != 0 {
			return ErrConflict
		}
		if _, e = c.ExecContext(ctx, "INSERT INTO kernel_schema_migrations VALUES(?,?,'Applying')", version, want); e != nil {
			return sanitize(e)
		}
	} else {
		return sanitize(e)
	}
	for _, q := range strings.Split(migration, ";") {
		if strings.TrimSpace(q) != "" {
			if _, e = c.ExecContext(ctx, q); e != nil {
				return sanitize(e)
			}
		}
	}
	_, e = c.ExecContext(ctx, "UPDATE kernel_schema_migrations SET state='Applied' WHERE version=?", version)
	return sanitize(e)
}
