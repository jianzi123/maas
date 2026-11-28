package kernel

import (
	"context"
	"crypto/sha256"
	"database/sql"
	"fmt"
)

// ValidateMigrations is read-only; only the explicit migrator may resume DDL.
func ValidateMigrations(ctx context.Context, db *sql.DB) error {
	var extra int
	if e := db.QueryRowContext(ctx, "SELECT COUNT(*) FROM kernel_schema_migrations WHERE version NOT IN (1,2,3)").Scan(&extra); e != nil || extra != 0 {
		return ErrUnavailable
	}
	for i, body := range []string{migration, controlMigration, diagnosticMigration} {
		var digest, state string
		if e := db.QueryRowContext(ctx, "SELECT sha256,state FROM kernel_schema_migrations WHERE version=?", i+1).Scan(&digest, &state); e != nil || state != "Applied" || digest != fmt.Sprintf("%x", sha256.Sum256([]byte(body))) {
			return ErrUnavailable
		}
	}
	return nil
}
