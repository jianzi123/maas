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
	want := fmt.Sprintf("%x", sha256.Sum256([]byte(controlMigration)))
	var digest, state string
	e = c.QueryRowContext(ctx, "SELECT sha256,state FROM kernel_schema_migrations WHERE version=2").Scan(&digest, &state)
	if e == nil {
		if digest != want {
			return ErrConflict
		}
		if state == "Applied" {
			return nil
		}
	} else if errors.Is(e, sql.ErrNoRows) {
		if e = c.QueryRowContext(ctx, `SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=DATABASE() AND table_name IN ('key_metadata','rate_rebuilds','publication_proofs','validation_intents','validation_receipts')`).Scan(&n); e != nil {
			return sanitize(e)
		}
		if n != 0 {
			return ErrConflict
		}
		if _, e = c.ExecContext(ctx, "INSERT INTO kernel_schema_migrations VALUES(2,?,'Applying')", want); e != nil {
			return sanitize(e)
		}
	} else {
		return sanitize(e)
	}
	for _, q := range strings.Split(controlMigration, ";") {
		if strings.TrimSpace(q) != "" {
			if _, e = c.ExecContext(ctx, q); e != nil {
				return sanitize(e)
			}
		}
	}
	_, e = c.ExecContext(ctx, "UPDATE kernel_schema_migrations SET state='Applied' WHERE version=2")
	return sanitize(e)
}
