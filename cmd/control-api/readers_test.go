package main

import (
	"context"
	"database/sql"
	"github.com/go-sql-driver/mysql"
	"github.com/google/uuid"
	"github.com/jianzi123/maas/internal/release/history"
	"github.com/jianzi123/maas/internal/release/mysqlstore"
	"net/url"
	"os"
	"strings"
	"testing"
	"time"
)

func TestProjectionMissingDoesNotFallback(t *testing.T) {
	db, e := openProjectionDB("")
	if db != nil || e != nil {
		t.Fatal("missing projection inherited a connection")
	}
}
func TestMySQLProjectionIdentity(t *testing.T) {
	socket := os.Getenv("MAAS_MYSQL_TEST_SOCKET")
	if socket == "" {
		t.Skip("disposable MySQL required")
	}
	if os.Getenv("MAAS_DISPOSABLE_MYSQL") != "1" || !strings.HasPrefix(socket, "/tmp/maas11-mysql.") {
		t.Fatal("refuse existing DB")
	}
	cfg := mysql.NewConfig()
	cfg.User = "root"
	cfg.Net = "unix"
	cfg.Addr = socket
	cfg.ParseTime = true
	cfg.Loc = time.UTC
	admin, _ := sql.Open("mysql", cfg.FormatDSN())
	defer admin.Close()
	nonce := strings.ReplaceAll(uuid.NewString(), "-", "")
	schema := "maas_read_" + nonce
	account := "reader_" + nonce[:12]
	if _, e := admin.Exec("CREATE DATABASE " + schema); e != nil {
		t.Fatal(e)
	}
	defer admin.Exec("DROP DATABASE " + schema)
	cfg.DBName = schema
	db, _ := sql.Open("mysql", cfg.FormatDSN())
	defer db.Close()
	if e := mysqlstore.Migrate(context.Background(), db); e != nil {
		t.Fatal(e)
	}
	if _, e := admin.Exec("CREATE USER '" + account + "'@'localhost'"); e != nil {
		t.Fatal(e)
	}
	defer admin.Exec("DROP USER '" + account + "'@'localhost'")
	for _, table := range []string{"release_history_directory", "release_history_projection", "release_history_completeness", "release_links", "publications"} {
		if _, e := admin.Exec("GRANT SELECT ON " + schema + "." + table + " TO '" + account + "'@'localhost'"); e != nil {
			t.Fatal(e)
		}
	}
	cfg.User = account
	projection, e := openProjectionDB(cfg.FormatDSN())
	if e != nil {
		t.Fatal(e)
	}
	defer projection.Close()
	var user string
	if projection.QueryRow("SELECT CURRENT_USER()").Scan(&user) != nil || !strings.HasPrefix(user, account+"@") {
		t.Fatal("wrong identity", user)
	}
	r := &history.Reader{DB: projection, Cluster: "test", CursorKey: []byte(strings.Repeat("c", 32)), Access: history.NamespaceAccess{Namespaces: map[string]bool{"models": true}, ScopeID: "test"}}
	_, e = r.ReadRevisions(context.Background(), "models", "model", url.Values{"cr_uid": {uuid.NewString()}})
	if e != history.ErrNotFound {
		t.Fatal("projection could not read permitted views", e)
	}
	for _, q := range []string{"SELECT spec_bytes FROM retained_release_snapshots", "UPDATE release_links SET admission_closed=FALSE", "INSERT INTO release_management_operations(cluster_id) VALUES('bad')", "CREATE TABLE denied(id INT)"} {
		rows, err := projection.Query(q)
		if rows != nil {
			rows.Close()
		}
		if err == nil {
			t.Fatal("reader escaped privileges", q)
		}
	}
}
