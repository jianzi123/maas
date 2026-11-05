package kernel

import (
	"context"
	"database/sql"
	"github.com/google/uuid"
	"github.com/jianzi123/maas/internal/release"
	"github.com/jianzi123/maas/internal/release/mysqlstore"
	"strings"
	"testing"
)

func TestMySQLPublisherCannotWriteRealLedger(t *testing.T) {
	f := setup(t, 1)
	ctx := context.Background()
	s := mustAdmit(t, f, f.input(t))
	if e := f.core.Finalize(ctx, finalFor(s)); e != nil {
		t.Fatal(e)
	}
	username := "pub_" + strings.ReplaceAll(uuid.NewString(), "-", "")[:16]
	password := uuid.NewString()
	// CREATE USER password syntax is not a server-prepared placeholder. Both
	// interpolated values here are generated UUID-derived test-only literals.
	if _, e := f.db.Exec("CREATE USER '" + username + "'@'localhost' IDENTIFIED BY '" + password + "'"); e != nil {
		t.Fatal(e)
	}
	t.Cleanup(func() {
		if _, e := f.db.Exec("DROP USER '" + username + "'@'localhost'"); e != nil {
			t.Error(e)
		}
	})
	for _, grant := range []string{
		"SELECT,INSERT,UPDATE ON release_links", "SELECT,INSERT ON release_revisions", "SELECT,INSERT ON publish_intents", "SELECT,INSERT,UPDATE ON publications", "SELECT,INSERT,UPDATE,DELETE ON active_model_bindings", "SELECT,INSERT,UPDATE ON resource_inventory", "SELECT,INSERT ON release_operations",
		"SELECT ON kernel_guard", "SELECT ON invocation_profiles", "SELECT(publication_id,result) ON generation_requests", "SELECT(publication_id,state) ON concurrency_slots",
	} {
		parts := strings.SplitN(grant, " ON ", 2)
		q := "GRANT " + parts[0] + " ON `" + f.config.DBName + "`." + parts[1] + " TO '" + username + "'@'localhost'"
		if _, e := f.db.Exec(q); e != nil {
			t.Fatal(e)
		}
	}
	cfg := f.config.Clone()
	cfg.User = username
	cfg.Passwd = password
	low, e := sql.Open("mysql", cfg.FormatDSN())
	if e != nil {
		t.Fatal(e)
	}
	defer low.Close()
	publisher, e := mysqlstore.New(low, "controlled-test", f.core)
	if e != nil {
		t.Fatal(e)
	}
	st, e := publisher.Read(ctx, f.desired.CRUID)
	if e != nil {
		t.Fatal("real guard/profile SELECT-only lock", e)
	}
	active := st.Active.PublicationID
	if e = publisher.Apply(ctx, release.Command{ID: uuid.NewString(), Action: "CloseAdmission", CRUID: st.CRUID, Generation: st.Generation, Fence: st.Fence, ExpectedActive: &active, Revision: st.Revision, EvidenceRefs: []string{}}); e != nil {
		t.Fatal("close", e)
	}
	safe, e := publisher.Drain(ctx, st.CRUID, "")
	if e != nil || safe {
		t.Fatal("real unsafe slot must block cleanup", safe, e)
	}
	for _, q := range []string{"UPDATE platform_keys SET revoked=FALSE", "UPDATE budget_windows SET uncertainty_held=0", "UPDATE concurrency_slots SET allocation_fence=0", "UPDATE generation_requests SET result='succeeded'", "DELETE FROM usage_events", "CREATE TABLE forbidden(id INT)"} {
		if _, e = low.Exec(q); e == nil {
			t.Fatal("publisher permission violation", q)
		}
	}
	if e = f.core.Release(ctx, s.Input.RequestID, uuid.NewString(), uuid.NewString()); e != nil {
		t.Fatal(e)
	}
	safe, e = publisher.Drain(ctx, st.CRUID, "")
	if e != nil || !safe {
		t.Fatal("safe slot drain", safe, e)
	}
	if c := readCounter(t, f, "tokens"); c.Held != "140" {
		t.Fatal("unknown hold modified", c)
	}
}
