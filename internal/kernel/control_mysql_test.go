package kernel

import (
	"context"
	"database/sql"
	"errors"
	"github.com/google/uuid"
	"github.com/jianzi123/maas/internal/protocol"
	"github.com/jianzi123/maas/internal/release"
	"github.com/jianzi123/maas/internal/release/mysqlstore"
	"net/url"
	"os"
	"strings"
	"testing"
	"time"
)

func TestMySQLQueriesAndCAS(t *testing.T) {
	f := setup(t, 2)
	ctx := context.Background()
	in := f.input(t)
	s := mustAdmit(t, f, in)
	fin := finalFor(s)
	if e := f.core.Finalize(ctx, fin); e != nil {
		t.Fatal(e)
	}
	check := func(schema string, v any) {
		t.Helper()
		if e := protocol.Validate(schema, v); e != nil {
			t.Fatalf("%s: %v %#v", schema, e, v)
		}
	}
	page, e := f.core.LookupRequest(ctx, in.RequestID)
	if e != nil {
		t.Fatal(e)
	}
	check("RequestLookupPage", page)
	lookup := page["lookup"].(map[string]any)
	if lookup["capacity"].(map[string]any)["state"] != "quarantined" {
		t.Fatal(page)
	}
	before := readCounter(t, f, "tokens")
	if e = f.core.Release(ctx, in.RequestID, uuid.NewString(), uuid.NewString()); e != nil {
		t.Fatal(e)
	}
	newer := mustAdmit(t, f, f.input(t))
	page, e = f.core.LookupRequest(ctx, in.RequestID)
	if e != nil {
		t.Fatal(e)
	}
	check("RequestLookupPage", page)
	if page["lookup"].(map[string]any)["capacity"].(map[string]any)["state"] != "released" {
		t.Fatal("read newer slot as old allocation", page)
	}
	if c := readCounter(t, f, "tokens"); c.Held != before.Held {
		t.Fatal("query/release refunded held", c)
	}
	page, e = f.core.LookupRequest(ctx, uuid.NewString())
	if e != nil {
		t.Fatal(e)
	}
	check("RequestLookupPage", page)
	if page["lookup"].(map[string]any)["resolution"] != "unknown" || page["data_complete"] != false {
		t.Fatal(page)
	}
	if _, e = f.core.ListRequests(ctx, url.Values{"request_id": {in.RequestID}, "page_size": {"20"}}); !errors.Is(e, ErrPolicy) {
		t.Fatal("exact/list conflict", e)
	}
	page, e = f.core.ListRequests(ctx, url.Values{"page_size": {"1"}})
	if e != nil {
		t.Fatal(e)
	}
	check("RequestPage", page)
	cursor := page["next_cursor"].(string)
	page, e = f.core.ListRequests(ctx, url.Values{"page_size": {"1"}, "cursor": {cursor}})
	if e != nil {
		t.Fatal(e)
	}
	check("RequestPage", page)
	if _, e = f.core.ListRequests(ctx, url.Values{"page_size": {"1"}, "key_id": {uuid.NewString()}, "cursor": {cursor}}); !errors.Is(e, ErrPolicy) {
		t.Fatal("cursor filter binding", e)
	}
	summary, e := f.core.Summary(ctx, url.Values{})
	if e != nil {
		t.Fatal(e)
	}
	check("SummaryPage", summary)
	meta, e := f.core.KeyView(ctx, f.key)
	if e != nil {
		t.Fatal(e)
	}
	check("Key", meta)
	policy := meta["budget_policy"].(Policy)
	limits := policy.Limits
	limits.Tokens = ptr("1")
	if e = f.core.PatchKey(ctx, f.key, policy.Revision, limits); e != nil {
		t.Fatal(e)
	}
	if e = f.core.PatchKey(ctx, f.key, policy.Revision, limits); !errors.Is(e, ErrConflict) {
		t.Fatal("stale CAS", e)
	}
	meta, e = f.core.KeyView(ctx, f.key)
	if e != nil {
		t.Fatal(e)
	}
	check("Key", meta)
	available := meta["budget_state"].(map[string]any)["available"].(map[string]any)
	if available["tokens"] != "0" {
		t.Fatal(meta)
	}
	assertSQL(t, f.db, "SELECT COUNT(*) FROM generation_requests", 2)
	assertSQL(t, f.db, "SELECT COUNT(*) FROM usage_events", 1)
	_ = newer
}

type witnessFixture struct{ w Witness }

func (v witnessFixture) Verify(context.Context, []byte) (Witness, error) { return v.w, nil }
func TestMySQLDurableProofAndCandidateValidation(t *testing.T) {
	f := setup(t, 3)
	ctx := context.Background()
	f.desired.Generation++
	f.desired.Revision = strings.Repeat("e", 64)
	st, e := f.gate.Observe(ctx, f.desired)
	if e != nil {
		t.Fatal(e)
	}
	p := f.profile
	p.Binding = *st.Candidate
	if e = f.core.RegisterProfile(ctx, p); e != nil {
		t.Fatal(e)
	}
	f.core.proofs = DurableProofs{Cluster: "controlled-test"}
	gate, e := mysqlstore.New(f.db, "controlled-test", f.core)
	if e != nil {
		t.Fatal(e)
	}
	key, _, e := f.core.CreateValidationKey(ctx, "controlled-validation", Policy{Window: "utc_day", Revision: "test-budget-v1", Limits: Limits{Requests: ptr("10"), Tokens: ptr("1400"), Money: &MoneyLimit{"TST", "5200000"}}})
	if e != nil {
		t.Fatal(e)
	}
	v, e := f.core.PlanValidation(ctx, p, key, "validation-policy-v1", time.Now().UTC().Add(time.Minute))
	if e != nil {
		t.Fatal(e)
	}
	again, e := f.core.PlanValidation(ctx, p, key, "validation-policy-v1", time.Now().UTC().Add(2*time.Minute))
	if e != nil || again.RequestID != v.RequestID {
		t.Fatal("intent replay", e)
	}
	in := f.input(t)
	in.Profile = p
	in.KeyID = key
	in.Purpose = "validation"
	in.ValidationIntentID = v.ID
	in.RequestID = v.RequestID
	if _, e = f.core.Admit(ctx, gate, in); e == nil {
		t.Fatal("missing proof admitted candidate")
	}
	refs := []string{}
	for _, kind := range []string{"runtime", "gateway"} {
		w := Witness{ID: uuid.NewString(), PublicationID: p.Binding.PublicationID, Issuer: "fixture-only", Kind: kind, ProfileHash: hash(p), Observed: time.Now().UTC().Add(-time.Second), Expires: time.Now().UTC().Add(time.Minute)}
		if e = f.core.CaptureWitness(ctx, witnessFixture{w}, []byte(kind)); e != nil {
			t.Fatal(e)
		}
		refs = append(refs, w.ID)
	}
	plain := in
	plain.Purpose = "serving"
	if _, e = f.core.Admit(ctx, gate, plain); e == nil {
		t.Fatal("validation Key used for serving")
	}
	snap, e := f.core.Admit(ctx, gate, in)
	if e != nil {
		t.Fatal("candidate admission", e)
	}
	if _, e = f.core.Admit(ctx, gate, in); e == nil {
		t.Fatal("candidate generation replay")
	}
	fin := finalFor(snap)
	i, o, cached := int64(12), int64(7), int64(0)
	fin.Result = "succeeded"
	fin.Submitted = true
	fin.Usage = Usage{Input: &i, Output: &o, Cached: &cached, Source: "upstream"}
	if e = f.core.Finalize(ctx, fin); e != nil {
		t.Fatal(e)
	}
	st, e = gate.Read(ctx, f.desired.CRUID)
	if e != nil || !st.ValidationPassed {
		t.Fatal("durable validation", st, e)
	}
	target := p.Binding.PublicationID
	active := f.profile.Binding.PublicationID
	cmd := release.Command{ID: uuid.NewString(), Action: "Activate", CRUID: st.CRUID, Generation: st.Generation, Fence: st.Fence, ExpectedActive: &active, Target: &target, Revision: st.Revision, EvidenceRefs: st.EvidenceRefs}
	if e = gate.Apply(ctx, cmd); e != nil {
		t.Fatal("activate verified candidate", e)
	}
	servingIn := f.input(t)
	servingIn.Profile = p
	blocking := &blockingGate{gate: gate, locked: make(chan struct{}), resume: make(chan struct{})}
	result := make(chan error, 1)
	go func() { _, e := f.core.Admit(ctx, blocking, servingIn); result <- e }()
	<-blocking.locked
	if e = f.core.RevokeWitness(ctx, refs[1]); !errors.Is(e, ErrBusy) {
		t.Error("proof revocation overtook protected admission", e)
	}
	close(blocking.resume)
	if e = <-result; e != nil {
		t.Fatal(e)
	}
	if e = f.core.RevokeWitness(ctx, refs[1]); e != nil {
		t.Fatal(e)
	}
	serving := f.input(t)
	serving.Profile = p
	if _, e = f.core.Admit(ctx, gate, serving); e == nil {
		t.Fatal("revoked gateway receipt admitted")
	}
	// H2 is absent: a successful candidate still has quarantined capacity.
	assertSQL(t, f.db, "SELECT COUNT(*) FROM concurrency_slots WHERE request_id=? AND state='QUARANTINED'", 1, v.RequestID)
}

func TestMySQLLastBudgetTwoReplicas(t *testing.T) {
	f := setup(t, 2)
	ctx := context.Background()
	meta, e := f.core.KeyView(ctx, f.key)
	if e != nil {
		t.Fatal(e)
	}
	p := meta["budget_policy"].(Policy)
	limits := p.Limits
	limits.Requests = ptr("1")
	if e = f.core.PatchKey(ctx, f.key, p.Revision, limits); e != nil {
		t.Fatal(e)
	}
	meta, _ = f.core.KeyView(ctx, f.key)
	p = meta["budget_policy"].(Policy)
	one, two := f.input(t), f.input(t)
	one.Plan, _ = BuildPlan(f.profile, p, "test-rate-v1")
	two.Plan = one.Plan
	replica, _ := New(f.db, "controlled-test", f.core.pepper, f.rate, f.proofs)
	start := make(chan struct{})
	results := make(chan error, 2)
	for _, v := range []struct {
		s  *Store
		in Input
	}{{f.core, one}, {replica, two}} {
		go func(v struct {
			s  *Store
			in Input
		}) {
			<-start
			_, e := v.s.Admit(ctx, f.gate, v.in)
			results <- e
		}(v)
	}
	close(start)
	wins := 0
	for i := 0; i < 2; i++ {
		e := <-results
		if e == nil {
			wins++
		} else if !errors.Is(e, ErrBusy) && !errors.Is(e, ErrBudget) {
			t.Fatal(e)
		}
	}
	if wins != 1 {
		t.Fatal("last budget admitted twice", wins)
	}
	assertSQL(t, f.db, "SELECT COUNT(*) FROM generation_requests", 1)
	assertSQL(t, f.db, "SELECT COUNT(*) FROM concurrency_slots WHERE state='HELD'", 1)
}
func TestMySQLRedisCompleteRebuild(t *testing.T) {
	socket := os.Getenv("MAAS_REDIS_TEST_SOCKET")
	if socket == "" {
		t.Skip("real disposable Redis required")
	}
	f := setup(t, 2)
	ctx := context.Background()
	r := &RedisGate{Network: "unix", Address: socket, Prefix: f.config.DBName, Timeout: 2 * time.Second}
	f.core.rate = r
	epoch, e := f.core.BlockRate(ctx)
	if e != nil {
		t.Fatal(e)
	}
	if e = f.core.RebuildRate(ctx, r, epoch); e != nil {
		t.Fatal(e)
	}
	p, e := f.core.readRate(ctx)
	if e != nil || !p.Ready || p.RedisIdentity == "" || p.RebuildNonce == "" {
		t.Fatal(p, e)
	}
	s := mustAdmit(t, f, f.input(t))
	fin := finalFor(s)
	fin.EvidenceRef = uuid.NewString()
	if e = f.core.Finalize(ctx, fin); e != nil {
		t.Fatal(e)
	}
	epoch, e = f.core.BlockRate(ctx)
	if e != nil {
		t.Fatal(e)
	}
	if e = f.core.RebuildRate(ctx, r, epoch); e != nil {
		t.Fatal(e)
	}
	p, e = f.core.readRate(ctx)
	if e != nil {
		t.Fatal(e)
	}
	c, e := r.connect(ctx)
	if e != nil {
		t.Fatal(e)
	}
	defer c.Close()
	bucket := r.Prefix + "{maas-rate}:" + decimal(epoch) + ":" + p.Revision + ":" + decimal(time.Now().UnixMilli()/p.WindowMS*p.WindowMS) + ":"
	reply, e := command(c, "GET", bucket+"global")
	if e != nil || reply.text != "1" {
		t.Fatal("durable lower bound", reply, e)
	}
	if e = f.core.RebuildRate(ctx, r, epoch); !errors.Is(e, ErrConflict) {
		t.Fatal("ready epoch must not be reset", e)
	}
	if _, e = command(c, "DEL", r.Prefix+"{maas-rate}:epoch"); e != nil {
		t.Fatal(e)
	}
	if _, e = f.core.Admit(ctx, f.gate, f.input(t)); e == nil {
		t.Fatal("missing rebuilt marker")
	}
}
func TestMySQLLateExpiryAndCluster(t *testing.T) {
	f := setup(t, 1)
	in := f.input(t)
	in.Expires = time.Now().UTC().Add(500 * time.Millisecond)
	g := &delayGate{ActiveGate: f.gate}
	if _, e := f.core.Admit(context.Background(), g, in); e == nil {
		t.Fatal("post-write expiry")
	}
	assertSQL(t, f.db, "SELECT COUNT(*) FROM generation_requests", 0)
	if g.calls != 2 {
		t.Fatal("test must reach post-write gate", g.calls)
	}
	wrong, _ := New(f.db, "other-cluster", f.core.pepper, f.rate, f.proofs)
	if _, e := wrong.Admit(context.Background(), f.gate, f.input(t)); e == nil {
		t.Fatal("cross-cluster")
	}
}

type delayGate struct {
	ActiveGate
	calls int
}

func (g *delayGate) LockActive(ctx context.Context, tx *sql.Tx, uid string) (release.Binding, error) {
	b, e := g.ActiveGate.LockActive(ctx, tx, uid)
	g.calls++
	if g.calls == 2 {
		time.Sleep(600 * time.Millisecond)
	}
	return b, e
}
