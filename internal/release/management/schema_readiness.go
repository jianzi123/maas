package management

import (
	"context"
	"crypto/sha256"
	"database/sql"
	"fmt"
	"github.com/jianzi123/maas/internal/release"
)

func ValidateMigration(ctx context.Context, db *sql.DB) error {
	var digest, state string
	if e := db.QueryRowContext(ctx, "SELECT sha256,state FROM release_schema_migrations WHERE version=3").Scan(&digest, &state); e != nil || state != "Applied" || digest != fmt.Sprintf("%x", sha256.Sum256([]byte(migration))) {
		return release.ErrDependencyMissing
	}
	return nil
}
