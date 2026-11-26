package mysqlstore

import (
	"context"
	"crypto/sha256"
	"database/sql"
	"fmt"
	"github.com/jianzi123/maas/internal/release/management"
)

// ValidateMigrations reads only public migration markers, never private history.
func ValidateMigrations(ctx context.Context, db *sql.DB) error {
	var extra int
	if e := db.QueryRowContext(ctx, "SELECT COUNT(*) FROM release_schema_migrations WHERE version NOT IN (1,2,3)").Scan(&extra); e != nil || extra != 0 {
		return ErrUnavailable
	}
	for i, body := range []string{migration, historyMigration} {
		var digest, state string
		if e := db.QueryRowContext(ctx, "SELECT sha256,state FROM release_schema_migrations WHERE version=?", i+1).Scan(&digest, &state); e != nil || state != "Applied" || digest != fmt.Sprintf("%x", sha256.Sum256([]byte(body))) {
			return ErrUnavailable
		}
	}
	return management.ValidateMigration(ctx, db)
}
