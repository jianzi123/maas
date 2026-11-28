package app

import (
	"context"
	"encoding/json"
	"github.com/google/uuid"
	a "github.com/jianzi123/maas/internal/agentruntime"
	"github.com/jianzi123/maas/internal/kernel"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"
)

// Real MySQL: a marker is a separate barrier from physical DDL completion.
func TestProductRequiredMigrationBarrier(t *testing.T) {
	c, db := productFixture(t)
	ctx := context.Background()
	if e := Migrate(ctx, c); e != nil {
		t.Fatal(e)
	}
	exec := func(q string, args ...any) {
		t.Helper()
		if _, e := db.ExecContext(ctx, q, args...); e != nil {
			t.Fatal(e)
		}
	}
	var verifier []byte
	if e := db.QueryRow("SELECT verifier FROM product_admins WHERE admin_id=?", c.Auth.AdminID).Scan(&verifier); e != nil {
		t.Fatal(e)
	}
	for _, state := range []string{"Applying", "Failed", "Unknown"} {
		t.Run(state, func(t *testing.T) {
			exec("UPDATE product_schema_migrations SET state=? WHERE version=2", state)
			r, e := Open(ctx, c)
			if e == nil {
				r.Close()
				t.Fatal("incomplete required migration served")
			}
			if e.Error() != "product_schema_not_ready" {
				t.Fatal(e)
			}
			var actual string
			if e = db.QueryRow("SELECT state FROM product_schema_migrations WHERE version=2").Scan(&actual); e != nil || actual != state {
				t.Fatal("serve mutated marker", actual, e)
			}
			if e = Migrate(ctx, c); e == nil || e.Error() != "product_schema_needs_reconciliation" {
				t.Fatal("migration silently repaired partial state", e)
			}
		})
	}
	exec("DELETE FROM product_schema_migrations WHERE version=2")
	if r, e := Open(ctx, c); e == nil {
		r.Close()
		t.Fatal("missing marker served")
	}
	exec("INSERT INTO product_schema_migrations VALUES(2,?,'Applied')", sum(offlineMigration))
	exec("UPDATE product_schema_migrations SET sha256=REPEAT('0',64) WHERE version=2")
	if r, e := Open(ctx, c); e == nil {
		r.Close()
		t.Fatal("wrong migration bytes served")
	}
	exec("UPDATE product_schema_migrations SET sha256=? WHERE version=2", sum(offlineMigration))
	exec("RENAME TABLE product_offline_state TO saved_offline_state")
	if r, e := Open(ctx, c); e == nil {
		r.Close()
		t.Fatal("Applied marker hid missing required table")
	}
	exec("RENAME TABLE saved_offline_state TO product_offline_state")
	exec("ALTER TABLE product_offline_state RENAME COLUMN key_id TO saved_key_id")
	if r, e := Open(ctx, c); e == nil {
		r.Close()
		t.Fatal("missing required column served")
	}
	if e := ReconcileProduct002(ctx, c); e == nil {
		t.Fatal("partial schema reconciled")
	}
	exec("ALTER TABLE product_offline_state RENAME COLUMN saved_key_id TO key_id")
	exec("INSERT INTO product_schema_migrations VALUES(3,REPEAT('0',64),'Applied')")
	if r, e := Open(ctx, c); e == nil {
		r.Close()
		t.Fatal("unknown newer schema accepted by old binary")
	}
	exec("DELETE FROM product_schema_migrations WHERE version=3")
	exec("ALTER TABLE agent_sessions_v1 DROP INDEX owner_sessions")
	if r, e := Open(ctx, c); e == nil {
		r.Close()
		t.Fatal("missing Agent index served")
	}
	exec("ALTER TABLE agent_sessions_v1 ADD INDEX owner_sessions(owner_id,session_id)")
	for _, domain := range []string{"kernel", "release"} {
		for version := 1; version <= 3; version++ {
			t.Run(domain+"-"+string(rune('0'+version)), func(t *testing.T) {
				exec("UPDATE "+domain+"_schema_migrations SET state='Applying' WHERE version=?", version)
				if r, e := Open(ctx, c); e == nil {
					r.Close()
					t.Fatal("required module migration served")
				}
				exec("UPDATE "+domain+"_schema_migrations SET state='Applied' WHERE version=?", version)
			})
		}
	}
	// Operator reconciliation has restored the marker and table. No data reset,
	// password rotation or implicit DDL is needed to start or restart.
	for i := 0; i < 2; i++ {
		r, e := Open(ctx, c)
		if e != nil {
			t.Fatal("reconciled schema cannot serve", e)
		}
		r.Close()
	}
	var after []byte
	if e := db.QueryRow("SELECT verifier FROM product_admins WHERE admin_id=?", c.Auth.AdminID).Scan(&after); e != nil || string(after) != string(verifier) {
		t.Fatal("startup changed existing admin", e)
	}
	r, e := Open(ctx, c)
	if e != nil {
		t.Fatal(e)
	}
	defer r.Close()
	stopped, stop := context.WithCancel(ctx)
	stop()
	if e = r.checkReady(stopped); e == nil || r.ctx.Err() != nil {
		t.Fatal("caller cancellation retired healthy runtime", e)
	}
	exec("UPDATE product_schema_migrations SET state='Applying' WHERE version=2")
	response := httptest.NewRecorder()
	r.Handler.ServeHTTP(response, httptest.NewRequest(http.MethodGet, "/readyz", nil))
	if response.Code != 503 {
		t.Fatal("running readiness ignored migration drift", response.Code)
	}
	if _, e = r.Service.Reauthorize(ctx, a.Principal{ID: c.Auth.AdminID}); e == nil {
		t.Fatal("schema drift permitted new dispatch")
	}
	if r.ctx.Err() == nil {
		t.Fatal("schema drift did not retire scheduler")
	}
}

func TestProductMigrationRecoveryPreservesUnknownHeldAndHistory(t *testing.T) {
	c, db := productFixture(t)
	ctx := context.Background()
	c.Offline = OfflineConfig{Enabled: true}
	if e := Migrate(ctx, c); e != nil {
		t.Fatal(e)
	}
	r, e := Open(ctx, c)
	if e != nil {
		t.Fatal(e)
	}
	defer r.Close()
	m := r.models.(*OfflineModel)
	if e := ReconcileProduct002(ctx, c); e == nil || e.Error() != "product_reconciliation_requires_maintenance" {
		t.Fatal("reconciliation bypassed active scheduler", e)
	}
	key, epoch, e := m.Core.Authenticate(ctx, string(m.Key))
	if e != nil {
		t.Fatal(e)
	}
	policy, rate, e := m.Core.AdmissionConfiguration(ctx, key)
	if e != nil {
		t.Fatal(e)
	}
	plan, e := kernel.BuildPlan(m.Profile, policy, rate.Revision)
	if e != nil {
		t.Fatal(e)
	}
	n := time.Now().UTC().Add(-time.Second).Truncate(time.Millisecond)
	in := kernel.Input{Purpose: "serving", RequestID: uuid.NewString(), KeyID: key, KeyEpoch: epoch, Owner: uuid.NewString(), TicketHash: sum("unknown-held-test"), Profile: m.Profile, Plan: plan, Received: n, Issued: n, Expires: n.Add(30 * time.Second), Deadline: n.Add(time.Minute)}
	snap, e := m.Core.Admit(ctx, m.Gate, in)
	if e != nil {
		t.Fatal(e)
	}
	missing := "not_provided"
	if e = m.Core.Finalize(ctx, kernel.Final{EventID: uuid.NewString(), RequestID: in.RequestID, Owner: in.Owner, OwnerFence: snap.OwnerFence, Result: "cancelled", Usage: kernel.Usage{Source: "unavailable", Missing: &missing}}); e != nil {
		t.Fatal(e)
	}
	projection := &Models{Core: r.Core}
	before, e := projection.usage(ctx, in.RequestID)
	if e != nil || before.Tokens != nil || len(before.Groups) != 1 || before.Groups[0].HeldTokens == "0" {
		t.Fatal("fixture did not create true unknown-held", before, e)
	}
	store := a.MySQLStore{DB: db}
	session := a.Session{Version: a.Version, ID: uuid.NewString(), Owner: c.Auth.AdminID, Revision: 1, Title: "preserve", Messages: []a.Message{{ID: uuid.NewString(), Role: "user", Status: "committed", Parts: []a.Part{{Type: "text", Text: "历史🙂"}}}}}
	if e = store.CompareAndSwap(ctx, session, 0); e != nil {
		t.Fatal(e)
	}
	var original []byte
	if e = db.QueryRow("SELECT document FROM agent_sessions_v1 WHERE session_id=?", session.ID).Scan(&original); e != nil {
		t.Fatal(e)
	}
	r.Close()
	if _, e = db.Exec("UPDATE product_schema_migrations SET state='Applying' WHERE version=2"); e != nil {
		t.Fatal(e)
	}
	if opened, e := Open(ctx, c); e == nil {
		opened.Close()
		t.Fatal("incomplete marker served existing data")
	}
	// Use the real explicit maintenance operation, not a runtime marker repair.
	if e = ReconcileProduct002(ctx, c); e != nil {
		t.Fatal(e)
	}
	if e = ReconcileProduct002(ctx, c); e != nil {
		t.Fatal("repeat reconciliation", e)
	}
	if e = Migrate(ctx, c); e != nil {
		t.Fatal(e)
	}
	for i := 0; i < 2; i++ {
		opened, e := Open(ctx, c)
		if e != nil {
			t.Fatal(e)
		}
		after, e := (&Models{Core: opened.Core}).usage(ctx, in.RequestID)
		opened.Close()
		if e != nil {
			t.Fatal(e)
		}
		b, _ := json.Marshal(before)
		next, _ := json.Marshal(after)
		if string(b) != string(next) {
			t.Fatal("restart changed held accounting", string(next))
		}
	}
	var after []byte
	if e = db.QueryRow("SELECT document FROM agent_sessions_v1 WHERE session_id=?", session.ID).Scan(&after); e != nil || string(after) != string(original) {
		t.Fatal("startup changed persistent history", e)
	}
	var requests, events int
	if e = db.QueryRow("SELECT COUNT(*) FROM generation_requests").Scan(&requests); e != nil {
		t.Fatal(e)
	}
	if e = db.QueryRow("SELECT COUNT(*) FROM usage_events").Scan(&events); e != nil || requests != 1 || events != 1 {
		t.Fatal("recovery replayed generation or settlement", requests, events, e)
	}
}
