package kernel

import (
	"context"
	"encoding/json"
	"strconv"
	"testing"
	"time"

	"github.com/google/uuid"
	a "github.com/jianzi123/maas/internal/agentruntime"
)

// Controlled model and H1-H4/rate producers, REAL MySQL admission, settlement,
// session store and calculator. This does not claim a real model/Higress call.
type agentLedgerModel struct {
	t     *testing.T
	f     *fixture
	calls int
}

func (m *agentLedgerModel) Supports(context.Context, a.Model) error { return nil }
func (m *agentLedgerModel) Generate(ctx context.Context, r a.Request, emit func(string) error) (a.Response, error) {
	m.calls++
	in := m.f.input(m.t)
	in.RequestID = r.RequestID
	snap, e := m.f.core.Admit(ctx, m.f.gate, in)
	if e != nil {
		return a.Response{}, e
	}
	fin := finalFor(snap)
	i, o, total := int64(12), int64(7), int64(19)
	fin.Result = "succeeded"
	fin.Submitted = true
	fin.EvidenceRef = uuid.NewString()
	zero := int64(0)
	fin.Usage = Usage{Input: &i, Output: &o, Total: &total, Cached: &zero, Reasoning: &zero, Source: "upstream"}
	if e = m.f.core.Finalize(ctx, fin); e != nil {
		return a.Response{}, e
	}
	if e = m.f.core.Finalize(ctx, fin); e != nil {
		return a.Response{}, e
	}
	u := a.Usage{Tokens: &total, Currency: "TST"}
	var amount string
	if e = m.f.db.QueryRowContext(ctx, "SELECT JSON_UNQUOTE(JSON_EXTRACT(event_json,'$.budget_accounting.cost_actual_atomic')) FROM usage_events WHERE request_id=?", r.RequestID).Scan(&amount); e != nil {
		return a.Response{}, e
	}
	money, e := strconv.ParseInt(amount, 10, 64)
	if e != nil {
		return a.Response{}, e
	}
	u.Money = &money
	u.Complete = true
	u.Groups = []a.ARUsageGroup{{Currency: "TST", Price: m.f.profile.Price.Version, KnownTokens: "19", KnownMoney: amount, HeldTokens: "0", InflightTokens: "0", HeldMoney: "0", InflightMoney: "0"}}
	res := a.Response{RequestID: r.RequestID, Usage: u, TerminalConfirmed: true}
	if m.calls == 1 {
		res.Finish = "tool_calls"
		res.Calls = []a.Call{{ID: "calc", Name: "bounded_arithmetic", Arguments: json.RawMessage(`{"a":6,"b":7,"op":"multiply"}`)}}
	} else {
		res.Finish = "stop"
		if e = emit("42"); e != nil {
			return res, e
		}
	}
	return res, nil
}
func TestMySQLAgentChildrenUseOneLedger(t *testing.T) {
	f := setup(t, 2)
	ctx := context.Background()
	if e := a.Migrate(ctx, f.db); e != nil {
		t.Fatal(e)
	}
	model := &agentLedgerModel{t: t, f: f}
	reg, _ := a.NewRegistry(a.Calculator{})
	limits := a.Limits{Currency: "TST", Steps: 4, Calls: 4, Tokens: 1000, Money: 10000000, Duration: 10 * time.Second, ToolTimeout: time.Second, ApprovalTTL: time.Minute, InputBytes: 32768, OutputBytes: 8192, Events: 500}
	s, e := a.NewService(a.MySQLStore{DB: f.db}, model, reg, limits)
	if e != nil {
		t.Fatal(e)
	}
	p := a.Principal{ID: "75b49016-0aa4-42fc-ac6d-9f67318c1dce", Revision: "1", Permissions: map[string]bool{"tools.calculate": true}}
	s.Reauthorize = func(_ context.Context, p a.Principal) (a.Principal, error) { return p, nil }
	v, e := s.Create(ctx, p, "unique ledger")
	if e != nil {
		t.Fatal(e)
	}
	in := a.Submit{ClientID: uuid.NewString(), Text: "multiply", Mode: "agent", Model: a.Model{Alias: "controlled", Source: "controlled-test", Revision: "1", Protocol: "tools-v1"}}
	s.CountContext = func(_ context.Context, r a.Request) (int64, error) {
		b, _ := json.Marshal(r)
		return int64(len(b)), nil
	}
	in.AR = &a.ARExecution{Limits: a.ARLimits{Steps: 4, Calls: 4, Tools: 4, Duration: 10000, ToolTimeout: 1000, OutputBytes: 8192, ContextTokens: 32768, NoProgress: 3, Tokens: "1000", Money: "10000000", Currency: "TST"}, Tools: []a.ARToolRef{{Name: "bounded_arithmetic", Revision: "1"}}, Created: time.Now().UTC(), Fence: 1, PolicyRevision: "controlled-policy"}
	r, e := s.Submit(ctx, p, v.ID, in)
	if e != nil {
		t.Fatal(e)
	}
	if e = s.Drive(ctx, p, v.ID, r.ID); e != nil {
		t.Fatal(e)
	}
	// Recreate service to read persisted events and re-submit the same identity.
	s2, _ := a.NewService(a.MySQLStore{DB: f.db}, model, reg, limits)
	same, e := s2.Submit(ctx, p, v.ID, in)
	if e != nil || same.ID != r.ID {
		t.Fatal(e)
	}
	for i := 0; i < 2; i++ {
		if _, e = s2.Events(ctx, p, v.ID, r.ID, 0); e != nil {
			t.Fatal(e)
		}
	}
	got, e := s2.Get(ctx, p, v.ID)
	if e != nil || len(got.Runs) != 1 || got.Runs[0].Status != "completed" || model.calls != 2 {
		t.Fatal(e, got)
	}
	assertSQL(t, f.db, "SELECT COUNT(*) FROM generation_requests", 2)
	assertSQL(t, f.db, "SELECT COUNT(*) FROM usage_events", 2)
	assertSQL(t, f.db, "SELECT SUM(finalized_total) FROM usage_daily", 2)
	if c := readCounter(t, f, "tokens"); c.Known != "38" || c.Held != "0" || c.Reserved != "0" {
		t.Fatal(c)
	}
	for _, step := range got.Runs[0].Steps {
		assertSQL(t, f.db, "SELECT COUNT(*) FROM usage_events WHERE request_id=?", 1, step.RequestID)
	}
	// A stale document must not overwrite the durable revision.
	if e = (a.MySQLStore{DB: f.db}).CompareAndSwap(ctx, v, 0); e != a.ErrConflict {
		t.Fatal("CAS", e)
	}
}
