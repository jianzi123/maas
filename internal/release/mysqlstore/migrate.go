package mysqlstore

import (
	"context"
	"crypto/sha256"
	"database/sql"
	_ "embed"
	"errors"
	"fmt"
	"strings"
	"time"

	"github.com/jianzi123/maas/internal/release"
	"github.com/jianzi123/maas/internal/release/management"
)

//go:embed schema/0001_release.sql
var migration string

// Migrate is an explicit administrative action, never called by New/operator
// startup. MySQL DDL commits independently; Applying is durable so an interrupted
// migration resumes the SAME checksummed IF-NOT-EXISTS statements. This is not a
// promise of multi-statement transactional DDL or a destructive down migration.
func Migrate(ctx context.Context, db *sql.DB) error {
	if e := migrateBase(ctx, db); e != nil {
		return e
	}
	if e := migrateHistory(ctx, db); e != nil {
		return e
	}
	return management.Migrate(ctx, db)
}
func migrateBase(ctx context.Context, db *sql.DB) error {
	if db == nil {
		return release.ErrDependencyMissing
	}
	conn, err := db.Conn(ctx)
	if err != nil {
		return publicError(err)
	}
	defer conn.Close()
	var database string
	if err = conn.QueryRowContext(ctx, "SELECT DATABASE()").Scan(&database); err != nil || database == "" {
		return ErrUnavailable
	}
	lockName := "maas-release:" + release.Hash(database)[:40]
	var locked sql.NullInt64
	if err = conn.QueryRowContext(ctx, "SELECT GET_LOCK(?,0)", lockName).Scan(&locked); err != nil || !locked.Valid || locked.Int64 != 1 {
		return release.ErrConflict
	}
	defer func() {
		releaseCtx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
		defer cancel()
		_, _ = conn.ExecContext(releaseCtx, "SELECT RELEASE_LOCK(?)", lockName)
	}()
	if _, err = conn.ExecContext(ctx, `CREATE TABLE IF NOT EXISTS release_schema_migrations(version INT PRIMARY KEY,sha256 CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,state ENUM('Applying','Applied') NOT NULL) ENGINE=InnoDB`); err != nil {
		return publicError(err)
	}
	var hash, state string
	err = conn.QueryRowContext(ctx, "SELECT sha256,state FROM release_schema_migrations WHERE version=1").Scan(&hash, &state)
	if err != nil && !errors.Is(err, sql.ErrNoRows) {
		return publicError(err)
	}
	want := fmt.Sprintf("%x", sha256.Sum256([]byte(migration)))
	if err == nil && hash != want {
		return release.ErrConflict
	}
	if err == nil && state == "Applied" {
		return nil
	}
	if errors.Is(err, sql.ErrNoRows) {
		// Refuse to adopt unversioned tables from another implementation. Only a
		// durable Applying record permits recovery of our partially completed DDL.
		var existing int
		if err = conn.QueryRowContext(ctx, `SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=DATABASE() AND table_name IN ('release_links','release_revisions','publish_intents','publications','active_model_bindings','resource_inventory','release_operations')`).Scan(&existing); err != nil {
			return publicError(err)
		}
		if existing != 0 {
			return release.ErrConflict
		}
		if _, err = conn.ExecContext(ctx, "INSERT INTO release_schema_migrations(version,sha256,state) VALUES(1,?,'Applying')", want); err != nil {
			return publicError(err)
		}
	}
	for _, statement := range strings.Split(migration, ";") {
		if statement = strings.TrimSpace(statement); statement != "" {
			if _, err = conn.ExecContext(ctx, statement); err != nil {
				return publicError(err)
			}
		}
	}
	_, err = conn.ExecContext(ctx, "UPDATE release_schema_migrations SET state='Applied' WHERE version=1 AND sha256=?", want)
	return publicError(err)
}
