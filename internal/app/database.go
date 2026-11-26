package app

import (
	"context"
	"crypto/pbkdf2"
	"crypto/rand"
	"crypto/sha256"
	"database/sql"
	_ "embed"
	"errors"
	"strings"
	"time"

	"github.com/go-sql-driver/mysql"
	"github.com/google/uuid"
	a "github.com/jianzi123/maas/internal/agentruntime"
	"github.com/jianzi123/maas/internal/kernel"
	"github.com/jianzi123/maas/internal/release/mysqlstore"
)

//go:embed migrations/001_product.sql
var productMigration string

func openDB(ctx context.Context, file string) (*sql.DB, error) {
	b, e := secret(file, 1, 8192)
	if e != nil {
		return nil, e
	}
	cfg, e := mysql.ParseDSN(string(b))
	for i := range b {
		b[i] = 0
	}
	if e != nil || cfg.DBName == "" || cfg.MultiStatements || cfg.AllowAllFiles {
		return nil, ErrConfig
	}
	cfg.ParseTime = true
	cfg.Loc = time.UTC
	cfg.Timeout = 5e9
	cfg.ReadTimeout = 10 * time.Second
	cfg.WriteTimeout = 10 * time.Second
	db, e := sql.Open("mysql", cfg.FormatDSN())
	if e != nil {
		return nil, ErrConfig
	}
	db.SetMaxOpenConns(20)
	db.SetMaxIdleConns(5)
	if db.PingContext(ctx) != nil {
		db.Close()
		return nil, errors.New("product_database_unavailable")
	}
	return db, nil
}
func Migrate(ctx context.Context, c Config) error {
	if e := c.Validate(); e != nil {
		return e
	}
	db, e := openDB(ctx, c.MySQL.MigrationDSNFile)
	if e != nil {
		return e
	}
	defer db.Close()
	if e = kernel.Migrate(ctx, db); e != nil {
		return errors.New("kernel_migration_failed")
	}
	if e = mysqlstore.Migrate(ctx, db); e != nil {
		return errors.New("release_migration_failed")
	}
	if e = a.Migrate(ctx, db); e != nil {
		return errors.New("agent_migration_failed")
	}
	conn, e := db.Conn(ctx)
	if e != nil {
		return e
	}
	defer conn.Close()
	var locked int
	if e = conn.QueryRowContext(ctx, "SELECT GET_LOCK(CONCAT('maas-product-schema:',DATABASE()),0)").Scan(&locked); e != nil || locked != 1 {
		return errors.New("product_migration_busy")
	}
	defer conn.ExecContext(context.Background(), "SELECT RELEASE_LOCK(CONCAT('maas-product-schema:',DATABASE()))")
	if _, e = conn.ExecContext(ctx, "CREATE TABLE IF NOT EXISTS product_schema_migrations(version INT PRIMARY KEY,sha256 CHAR(64) NOT NULL,state VARCHAR(16) NOT NULL)"); e != nil {
		return errors.New("product_migration_failed")
	}
	want := sum(productMigration)
	var digest, state string
	e = conn.QueryRowContext(ctx, "SELECT sha256,state FROM product_schema_migrations WHERE version=1").Scan(&digest, &state)
	if e == nil && (digest != want || state != "Applied") {
		return errors.New("product_schema_needs_reconciliation")
	}
	if e != nil && !errors.Is(e, sql.ErrNoRows) {
		return e
	}
	if errors.Is(e, sql.ErrNoRows) {
		if _, e = conn.ExecContext(ctx, "INSERT INTO product_schema_migrations VALUES(1,?,'Applying')", want); e != nil {
			return e
		}
		for _, statement := range strings.Split(productMigration, ";") {
			if strings.TrimSpace(statement) == "" {
				continue
			}
			if _, e = conn.ExecContext(ctx, statement); e != nil {
				return errors.New("product_migration_failed")
			}
		}
		if _, e = conn.ExecContext(ctx, "UPDATE product_schema_migrations SET state='Applied' WHERE version=1"); e != nil {
			return e
		}
	}
	if e = initializeLedger(ctx, db, c); e != nil {
		return e
	}
	if e = applyExtraMigration(ctx, conn, 2, offlineMigration); e != nil {
		return e
	}
	var existing string
	e = conn.QueryRowContext(ctx, "SELECT admin_id FROM product_admins WHERE username=?", c.Auth.Username).Scan(&existing)
	if e == nil {
		if existing != c.Auth.AdminID {
			return errors.New("admin_identity_conflict")
		}
		return initializeOffline(ctx, db, c)
	}
	if !errors.Is(e, sql.ErrNoRows) {
		return e
	}
	password, e := secret(c.Auth.PasswordFile, 12, 1024)
	if e != nil {
		return errors.New("bootstrap_password_unavailable")
	}
	defer func() {
		for i := range password {
			password[i] = 0
		}
	}()
	salt := make([]byte, 32)
	if _, e = rand.Read(salt); e != nil {
		return e
	}
	verifier, e := pbkdf2.Key(sha256.New, string(password), salt, passwordIterations, 32)
	if e != nil {
		return e
	}
	_, e = conn.ExecContext(ctx, "INSERT INTO product_admins(admin_id,username,salt,verifier,policy_revision) VALUES(?,?,?,?,?)", c.Auth.AdminID, c.Auth.Username, salt, verifier, uuid.NewString())
	if e != nil {
		return errors.New("admin_initialization_failed")
	}
	return initializeOffline(ctx, db, c)
}

func applyExtraMigration(ctx context.Context, conn *sql.Conn, version int, migration string) error {
	want := sum(migration)
	var hash, state string
	e := conn.QueryRowContext(ctx, "SELECT sha256,state FROM product_schema_migrations WHERE version=?", version).Scan(&hash, &state)
	if e == nil {
		if hash != want || state != "Applied" {
			return errors.New("product_schema_needs_reconciliation")
		}
		return nil
	}
	if !errors.Is(e, sql.ErrNoRows) {
		return e
	}
	if _, e = conn.ExecContext(ctx, "INSERT INTO product_schema_migrations VALUES(?,?,'Applying')", version, want); e != nil {
		return e
	}
	for _, statement := range strings.Split(migration, ";") {
		if strings.TrimSpace(statement) != "" {
			if _, e = conn.ExecContext(ctx, statement); e != nil {
				return errors.New("product_extra_migration_failed")
			}
		}
	}
	_, e = conn.ExecContext(ctx, "UPDATE product_schema_migrations SET state='Applied' WHERE version=?", version)
	return e
}
func validateSchema(ctx context.Context, db *sql.DB) error {
	return validateRequiredSchema(ctx, db, false)
}
func validateRequiredSchema(ctx context.Context, db *sql.DB, reconciling002 bool) error {
	if kernel.ValidateMigrations(ctx, db) != nil {
		return errors.New("kernel_schema_not_ready")
	}
	if mysqlstore.ValidateMigrations(ctx, db) != nil {
		return errors.New("release_schema_not_ready")
	}
	// Both migrations are unconditional in Migrate, including installations
	// without the offline profile. Physical tables alone are not a commit marker.
	var extra int
	if e := db.QueryRowContext(ctx, "SELECT COUNT(*) FROM product_schema_migrations WHERE version NOT IN (1,2)").Scan(&extra); e != nil || extra != 0 {
		return errors.New("product_schema_not_ready")
	}
	for _, required := range []struct {
		version int
		body    string
	}{{1, productMigration}, {2, offlineMigration}} {
		var sha, state string
		if e := db.QueryRowContext(ctx, "SELECT sha256,state FROM product_schema_migrations WHERE version=?", required.version).Scan(&sha, &state); e != nil || sha != sum(required.body) || (state != "Applied" && !(reconciling002 && required.version == 2 && state == "Applying")) {
			return errors.New("product_schema_not_ready")
		}
	}
	for _, q := range []string{"SELECT session_id,owner_id,revision,document FROM agent_sessions_v1 LIMIT 0", "SELECT admin_id,username,salt,verifier,policy_revision,enabled FROM product_admins LIMIT 0", "SELECT token_sha256,admin_id,csrf_token,expires_at,revoked FROM product_sessions LIMIT 0", "SELECT request_id,result FROM generation_requests LIMIT 0", "SELECT id,cluster_id,publication_id,key_id,key_cipher FROM product_offline_state LIMIT 0", "SELECT identity_sha256,window_start,attempts FROM product_login_attempts LIMIT 0"} {
		rows, e := db.QueryContext(ctx, q)
		if e != nil {
			return errors.New("runtime_schema_or_permissions_unavailable")
		}
		rows.Close()
	}
	if e := validateOfflineLayout(ctx, db); e != nil {
		return e
	}
	return validateAgentShape(ctx, db)
}

func validateAgentShape(ctx context.Context, db *sql.DB) error {
	var primary, owners int
	// Agent has no journal: validate the existing shape rather than invent one.
	if e := db.QueryRowContext(ctx, `SELECT COUNT(*) FROM information_schema.statistics WHERE table_schema=DATABASE() AND table_name='agent_sessions_v1' AND index_name='PRIMARY' AND column_name='session_id' AND seq_in_index=1 AND non_unique=0`).Scan(&primary); e != nil || primary != 1 {
		return errors.New("agent_schema_not_ready")
	}
	if e := db.QueryRowContext(ctx, `SELECT COUNT(*) FROM information_schema.statistics WHERE table_schema=DATABASE() AND table_name='agent_sessions_v1' AND index_name='owner_sessions' AND ((column_name='owner_id' AND seq_in_index=1) OR (column_name='session_id' AND seq_in_index=2))`).Scan(&owners); e != nil || owners != 2 {
		return errors.New("agent_schema_not_ready")
	}
	var invalid int
	e := db.QueryRowContext(ctx, `SELECT 1 FROM agent_sessions_v1 WHERE JSON_EXTRACT(document,'$.schema_version') IS NULL OR JSON_EXTRACT(document,'$.id') IS NULL OR JSON_EXTRACT(document,'$.owner') IS NULL OR JSON_EXTRACT(document,'$.revision') IS NULL OR JSON_UNQUOTE(JSON_EXTRACT(document,'$.schema_version'))<>? OR JSON_UNQUOTE(JSON_EXTRACT(document,'$.id'))<>session_id OR JSON_UNQUOTE(JSON_EXTRACT(document,'$.owner'))<>owner_id OR JSON_EXTRACT(document,'$.revision')<>revision LIMIT 1`, a.Version).Scan(&invalid)
	if e != sql.ErrNoRows {
		return errors.New("agent_document_version_not_ready")
	}
	return nil
}
