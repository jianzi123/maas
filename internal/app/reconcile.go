package app

import (
	"context"
	"database/sql"
	"errors"
)

func validateOfflineLayout(ctx context.Context, db *sql.DB) error {
	rows, e := db.QueryContext(ctx, `SELECT column_name,data_type,is_nullable,column_key,character_maximum_length FROM information_schema.columns WHERE table_schema=DATABASE() AND table_name='product_offline_state'`)
	if e != nil {
		return errors.New("product_offline_layout_not_ready")
	}
	defer rows.Close()
	expected := map[string]string{"id": "int", "cluster_id": "varchar", "publication_id": "varchar", "key_id": "varchar", "key_cipher": "blob"}
	seen := 0
	for rows.Next() {
		var name, kind, nullable, key string
		var length sql.NullInt64
		if rows.Scan(&name, &kind, &nullable, &key, &length) != nil || expected[name] != kind || nullable != "NO" {
			return errors.New("product_offline_layout_not_ready")
		}
		if name == "id" && key != "PRI" || name == "cluster_id" && length.Int64 != 128 || (name == "publication_id" || name == "key_id") && length.Int64 != 36 {
			return errors.New("product_offline_layout_not_ready")
		}
		seen++
	}
	if rows.Err() != nil || seen != len(expected) {
		return errors.New("product_offline_layout_not_ready")
	}
	return nil
}

// ReconcileProduct002 is an explicit maintenance operation, never called from
// Open, readiness or authentication. It does not replay DDL or rewrite a digest.
// Only this release's complete, exact Applying002 can be committed Applied.
func ReconcileProduct002(ctx context.Context, c Config) error {
	if e := c.Validate(); e != nil {
		return e
	}
	db, e := openDB(ctx, c.MySQL.MigrationDSNFile)
	if e != nil {
		return e
	}
	defer db.Close()
	conn, e := db.Conn(ctx)
	if e != nil {
		return errors.New("product_reconciliation_unavailable")
	}
	defer conn.Close()
	for _, name := range []string{"maas-product-runtime:", "maas-product-schema:"} {
		var own int
		if e = conn.QueryRowContext(ctx, "SELECT GET_LOCK(CONCAT(?,DATABASE()),0)", name).Scan(&own); e != nil || own != 1 {
			return errors.New("product_reconciliation_requires_maintenance")
		}
		defer conn.ExecContext(context.Background(), "SELECT RELEASE_LOCK(CONCAT(?,DATABASE()))", name)
	}
	if e = validateRequiredSchema(ctx, db, true); e != nil {
		return e
	}
	if c.Offline.Enabled {
		// Reuse original idempotent seed checks, encrypted Key and immutable profile.
		// An orphaned seed/Key remains a reconciliation failure, never a replacement.
		if e = initializeOffline(ctx, db, c); e != nil {
			return errors.New("offline_seed_needs_reconciliation")
		}
		pepper, e := secret(c.Secrets.PepperFile, 32, 4096)
		if e != nil {
			return e
		}
		models, _, _, e := openModelSource(ctx, db, c, pepper)
		for i := range pepper {
			pepper[i] = 0
		}
		if e != nil {
			return errors.New("offline_seed_needs_reconciliation")
		}
		models.Close()
	}
	var state string
	if e = conn.QueryRowContext(ctx, "SELECT state FROM product_schema_migrations WHERE version=2").Scan(&state); e != nil {
		return errors.New("product_schema_not_ready")
	}
	if state == "Applied" {
		return nil
	}
	result, e := conn.ExecContext(ctx, "UPDATE product_schema_migrations SET state='Applied' WHERE version=2 AND state='Applying' AND sha256=?", sum(offlineMigration))
	if e != nil {
		return errors.New("product_reconciliation_unavailable")
	}
	n, e := result.RowsAffected()
	if e != nil || n != 1 {
		return errors.New("product_reconciliation_unconfirmed")
	}
	return nil
}
