package app

import (
	"context"
	"database/sql"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/go-sql-driver/mysql"
	"github.com/google/uuid"
)

// SHOW VIEW grants metadata visibility without SELECT on private history rows.
// All grants here are limited to the fixture's disposable MySQL/schema/user.
func TestProductSchemaMetadataPrivilegeDoesNotReadHistory(t *testing.T) {
	c, db := productFixture(t)
	ctx := context.Background()
	if e := Migrate(ctx, c); e != nil {
		t.Fatal(e)
	}
	raw, e := os.ReadFile(c.MySQL.RuntimeDSNFile)
	if e != nil {
		t.Fatal(e)
	}
	cfg, e := mysql.ParseDSN(string(raw))
	if e != nil {
		t.Fatal(e)
	}
	user := "shape_" + strings.ReplaceAll(uuid.NewString(), "-", "")[:16]
	password := "controlled-metadata-test-only"
	if _, e = db.Exec("CREATE USER '" + user + "'@'localhost' IDENTIFIED BY 'controlled-metadata-test-only'"); e != nil {
		t.Fatal(e)
	}
	t.Cleanup(func() { db.Exec("DROP USER '" + user + "'@'localhost'") })
	if _, e = db.Exec("GRANT SHOW VIEW ON `" + cfg.DBName + "`.retained_release_snapshots TO '" + user + "'@'localhost'"); e != nil {
		t.Fatal(e)
	}
	cfg.User, cfg.Passwd = user, password
	scoped, e := sql.Open("mysql", cfg.FormatDSN())
	if e != nil {
		t.Fatal(e)
	}
	defer scoped.Close()
	for _, table := range []string{"tables", "columns", "statistics"} {
		var count int
		q := "SELECT COUNT(*) FROM information_schema." + table + " WHERE table_schema=DATABASE() AND table_name='retained_release_snapshots'"
		if e = scoped.QueryRow(q).Scan(&count); e != nil || (table == "columns" && count != 0) || (table != "columns" && count == 0) {
			t.Fatalf("unexpected metadata visibility for %s: count=%d error=%v", table, count, e)
		}
	}
	if rows, e := scoped.Query("SELECT spec_bytes FROM retained_release_snapshots LIMIT 0"); e == nil {
		rows.Close()
		t.Fatal("metadata privilege exposed private data")
	}
	if _, e = scoped.Exec("UPDATE retained_release_snapshots SET spec_bytes=spec_bytes WHERE FALSE"); e == nil {
		t.Fatal("metadata privilege allowed history mutation")
	}
}

func TestProductPhysicalGateWithOriginalFourRoles(t *testing.T) {
	c, admin := productFixture(t)
	ctx := context.Background()
	if e := Migrate(ctx, c); e != nil {
		t.Fatal(e)
	}
	raw, e := os.ReadFile(c.MySQL.RuntimeDSNFile)
	if e != nil {
		t.Fatal(e)
	}
	driver, e := mysql.ParseDSN(string(raw))
	if e != nil {
		t.Fatal(e)
	}
	exec := func(q string) {
		t.Helper()
		if _, e := admin.Exec(q); e != nil {
			t.Fatal(e)
		}
	}
	for _, file := range []string{"../../config/mysql/release-permissions.sql", "../../config/mysql/kernel-permissions.sql", "../../config/mysql/controlapi-projections.sql", "../../deploy/agent/session-role.sql"} {
		b, e := os.ReadFile(file)
		if e != nil {
			t.Fatal(e)
		}
		lines := []string{}
		for _, line := range strings.Split(string(b), "\n") {
			if !strings.HasPrefix(strings.TrimSpace(line), "--") {
				lines = append(lines, line)
			}
		}
		for _, statement := range strings.Split(strings.ReplaceAll(strings.Join(lines, "\n"), "__MAAS_DATABASE__", driver.DBName), ";") {
			if strings.TrimSpace(statement) != "" {
				exec(statement)
			}
		}
	}
	exec("CREATE ROLE IF NOT EXISTS maas_product_auth_runtime")
	for _, table := range []string{"product_admins", "product_schema_migrations", "product_offline_state"} {
		exec("GRANT SELECT ON `" + driver.DBName + "`." + table + " TO maas_product_auth_runtime")
	}
	for _, table := range []string{"product_sessions", "product_login_attempts"} {
		exec("GRANT SELECT,INSERT,UPDATE ON `" + driver.DBName + "`." + table + " TO maas_product_auth_runtime")
	}
	user := "runtime_" + strings.ReplaceAll(uuid.NewString(), "-", "")[:16]
	exec("CREATE USER '" + user + "'@'localhost' IDENTIFIED BY 'controlled-runtime-test-only'")
	t.Cleanup(func() { admin.Exec("DROP USER '" + user + "'@'localhost'") })
	roles := "maas_kernel_runtime,maas_release_reader,maas_agent_session_runtime,maas_product_auth_runtime"
	exec("GRANT " + roles + " TO '" + user + "'@'localhost'")
	exec("SET DEFAULT ROLE " + roles + " TO '" + user + "'@'localhost'")
	driver.User, driver.Passwd = user, "controlled-runtime-test-only"
	path := filepath.Join(t.TempDir(), "runtime-dsn")
	if e = os.WriteFile(path, []byte(driver.FormatDSN()), 0600); e != nil {
		t.Fatal(e)
	}
	c.MySQL.RuntimeDSNFile = path
	scoped, e := openDB(ctx, path)
	if e != nil {
		t.Fatal(e)
	}
	defer scoped.Close()
	if e = validateSchema(ctx, scoped); e != nil {
		t.Fatal("narrow identity cannot verify positive shape", e)
	}
	var metadataGrants int
	if e = admin.QueryRow("SELECT COUNT(*) FROM information_schema.table_privileges WHERE table_schema=? AND grantee=? AND privilege_type='SHOW VIEW'", driver.DBName, "'maas_release_reader'@'%'").Scan(&metadataGrants); e != nil || metadataGrants != 12 {
		t.Fatal("metadata grants exceed exact object scope", metadataGrants, e)
	}
	// An old installation without the additional object metadata privilege
	// must fail closed instead of accepting an unverifiable private table.
	exec("REVOKE SHOW VIEW ON `" + driver.DBName + "`.retained_release_snapshots FROM maas_release_reader")
	if opened, e := Open(ctx, c); e == nil {
		opened.Close()
		t.Fatal("missing metadata permission served")
	}
	exec("GRANT SHOW VIEW ON `" + driver.DBName + "`.retained_release_snapshots TO maas_release_reader")
	r, e := Open(ctx, c)
	if e != nil {
		t.Fatal("normal narrow runtime failed", e)
	}
	defer r.Close()
	for _, table := range []string{"release_revisions", "publish_intents", "resource_inventory", "release_operations", "release_history_owners", "retained_release_snapshots", "release_history_retention", "release_history_legacy_audit", "release_management_operations", "release_history_directory", "release_history_projection", "release_history_completeness"} {
		if rows, e := scoped.Query("SELECT * FROM " + table + " LIMIT 0"); e == nil {
			rows.Close()
			t.Fatal("private data access gained", table)
		}
	}
	if rows, e := scoped.Query("SELECT spec_bytes FROM retained_release_snapshots LIMIT 0"); e == nil {
		rows.Close()
		t.Fatal("raw private spec read allowed")
	}
	if _, e = scoped.Exec("UPDATE product_schema_migrations SET state='Applied' WHERE version=2"); e == nil {
		t.Fatal("runtime gained marker write")
	}
	if _, e = scoped.Exec("CREATE TABLE forbidden_runtime_ddl(id INT)"); e == nil {
		t.Fatal("runtime gained DDL")
	}
	exec("RENAME TABLE retained_release_snapshots TO saved_private_snapshots")
	defer admin.Exec("RENAME TABLE saved_private_snapshots TO retained_release_snapshots")
	if e = validateSchema(ctx, scoped); e == nil {
		t.Fatal("narrow metadata failed to detect missing private object")
	}
	if e = r.checkReady(ctx); e == nil || r.ctx.Err() == nil {
		t.Fatal("narrow running owner kept dispatch after shape loss")
	}
}
