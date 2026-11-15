package mysqlstore

import (
	"context"
	"database/sql"
	"github.com/google/uuid"
	"github.com/jianzi123/maas/internal/release/history"
	"net/url"
	"strings"
	"testing"
)

func TestMySQLHistoryProjectionRole(t *testing.T) {
	f := databaseFixture(t)
	ctx := context.Background()
	d := historyDesired(t)
	observe(t, testStore(t, f.db, nil), d)
	role := "histrole_" + strings.ReplaceAll(uuid.NewString(), "-", "")[:12]
	user := "histuser_" + strings.ReplaceAll(uuid.NewString(), "-", "")[:12]
	password := uuid.NewString()
	if _, e := f.db.Exec("CREATE ROLE '" + role + "'"); e != nil {
		t.Fatal(e)
	}
	defer f.db.Exec("DROP ROLE '" + role + "'")
	if _, e := f.db.Exec("CREATE USER '" + user + "'@'localhost' IDENTIFIED BY '" + password + "'"); e != nil {
		t.Fatal(e)
	}
	defer f.db.Exec("DROP USER '" + user + "'@'localhost'")
	for _, table := range []string{"release_history_directory", "release_history_projection", "release_history_completeness", "release_links", "publications"} {
		if _, e := f.db.Exec("GRANT SELECT ON `" + f.name + "`." + table + " TO '" + role + "'"); e != nil {
			t.Fatal(e)
		}
	}
	_, _ = f.db.Exec("GRANT '" + role + "' TO '" + user + "'@'localhost'")
	_, _ = f.db.Exec("SET DEFAULT ROLE '" + role + "' TO '" + user + "'@'localhost'")
	cfg := f.config.Clone()
	cfg.User = user
	cfg.Passwd = password
	low, e := sql.Open("mysql", cfg.FormatDSN())
	if e != nil {
		t.Fatal(e)
	}
	defer low.Close()
	r := historyReader(f, d, &historyLive{state: history.LiveState{State: "unknown"}})
	r.DB = low
	r.PayloadDB = nil
	r.Evaluator = nil
	if _, e = r.ReadRevisions(ctx, d.Namespace, d.Name, url.Values{"cr_uid": {d.CRUID}}); e != nil {
		t.Fatal("view-only reader", e)
	}
	for _, q := range []string{"SELECT spec_bytes FROM retained_release_snapshots", "SELECT revision_input_bytes FROM retained_release_snapshots", "UPDATE release_history_projection SET model_alias='other'", "DELETE FROM release_history_owners", "SELECT * FROM test_core_unknown_hold"} {
		if _, e := low.Exec(q); e == nil {
			t.Fatal("history reader privilege leak", q)
		}
	}
}
