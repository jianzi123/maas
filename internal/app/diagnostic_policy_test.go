package app

import (
	"context"
	a "github.com/jianzi123/maas/internal/agentruntime"
	"testing"
)

func TestProductRelayDiagnosticPolicyIsExplicitAndNeverReset(t *testing.T) {
	m := testConfiguredModel(t, true)
	ctx := context.Background()
	db := m.DB
	expected, e := readDiagnosticPolicy(ctx, db)
	if e != nil {
		t.Fatal(e)
	}
	if e = m.Open(); e != nil {
		t.Fatal("configured policy unavailable", e)
	}
	for i := 0; i < 2; i++ {
		if e = Migrate(ctx, m.Config); e != nil {
			t.Fatal(e)
		}
	}
	actual, e := readDiagnosticPolicy(ctx, db)
	if e != nil || actual != expected {
		t.Fatal("repeat migration changed policy", actual, e)
	}
	if _, e = db.Exec("DELETE FROM diagnostic_policy WHERE id=1"); e != nil {
		t.Fatal(e)
	}
	if e = m.Open(); e == nil {
		t.Fatal("runtime silently initialized missing policy")
	}
	if _, e = m.prepare(ctx, a.Request{}); e == nil {
		t.Fatal("missing policy allowed prepare")
	}
	var count int
	if e = db.QueryRow("SELECT COUNT(*) FROM diagnostic_policy").Scan(&count); e != nil || count != 0 {
		t.Fatal("runtime repaired policy", count, e)
	}
	if e = Migrate(ctx, m.Config); e != nil {
		t.Fatal("explicit migration cannot initialize missing policy", e)
	}
	if _, e = db.Exec("UPDATE diagnostic_policy SET max_records=max_records+1 WHERE id=1"); e != nil {
		t.Fatal(e)
	}
	if e = m.Open(); e == nil {
		t.Fatal("mismatched policy accepted")
	}
	if e = Migrate(ctx, m.Config); e == nil || e.Error() != "relay_diagnostic_policy_conflict" {
		t.Fatal("migration reset an existing different policy", e)
	}
	actual, e = readDiagnosticPolicy(ctx, db)
	if e != nil || actual.MaxRecords != expected.MaxRecords+1 {
		t.Fatal("conflicting policy was overwritten", actual, e)
	}
	if e = db.QueryRow("SELECT COUNT(*) FROM generation_requests").Scan(&count); e != nil || count != 0 {
		t.Fatal("policy validation dispatched model", count, e)
	}
	config := m.Config
	config.Ledger.Diagnostics = nil
	if config.Validate() == nil {
		t.Fatal("formal model accepted implicit diagnostic policy")
	}
}
