package kernel

// The database, ledger, capacity guard, admission, settlement and release gate
// are real implementation code. ONLY Redis and H1-H4 proof producers are fixtures.
import (
	"context"
	"database/sql"
	"database/sql/driver"
	"errors"
	"os"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"github.com/go-sql-driver/mysql"
	"github.com/google/uuid"
	api "github.com/jianzi123/maas/api/v1alpha1"
	"github.com/jianzi123/maas/internal/release"
	"github.com/jianzi123/maas/internal/release/mysqlstore"
)

type fixtureRate struct{ stale bool }

func (r *fixtureRate) Acquire(_ context.Context, request, key string, p RatePolicy) (Permit, error) {
	now := time.Now().UTC()
	start := time.UnixMilli(now.UnixMilli() / p.WindowMS * p.WindowMS)
	epoch := p.Epoch
	if r.stale {
		epoch--
	}
	return Permit{ID: uuid.NewString(), Epoch: epoch, PolicyID: p.Revision, Revision: p.Revision, Windows: []RateWindow{
		{Scope: "global", Start: start.Format(time.RFC3339Nano), End: start.Add(time.Duration(p.WindowMS) * time.Millisecond).Format(time.RFC3339Nano), Limit: decimal(p.GlobalLimit)},
		{Scope: "key/" + key, Start: start.Format(time.RFC3339Nano), End: start.Add(time.Duration(p.WindowMS) * time.Millisecond).Format(time.RFC3339Nano), Limit: decimal(p.KeyLimit)},
	}}, nil
}

type fixtureProofs struct {
	stale  bool
	noSend bool
	wrong  bool
}

func (p *fixtureProofs) Publication(ctx context.Context, tx *sql.Tx, pub mysqlstore.Publication) (mysqlstore.Evidence, error) {
	t, e := now(ctx, tx)
	if p.stale {
		t = t.Add(-time.Hour)
	}
	return mysqlstore.Evidence{Binding: pub.Binding, CRUID: pub.CRUID, FreshUntil: t.Add(time.Minute), RuntimeReady: true, GatewayApplied: true, AccountingReady: true, ValidationPassed: true, Refs: []string{"aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"}}, e
}
func (p *fixtureProofs) Closure(ctx context.Context, tx *sql.Tx, s Snapshot, ref string) (Closure, error) {
	t, e := now(ctx, tx)
	kind := "upstream_transport_closed"
	attempts := int64(1)
	if p.noSend {
		kind = "no_upstream_attempt"
		attempts = 0
	}
	c := Closure{ID: ref, Kind: kind, RequestID: s.Input.RequestID, TicketHash: s.Input.TicketHash, GatewayInstance: s.Input.Profile.GatewayInstance, GatewayEpoch: s.Input.Profile.GatewayEpoch, SlotID: s.SlotID, AllocationFence: s.AllocationFence, Sealed: true, Attempts: attempts, Observed: t}
	if p.wrong {
		c.AllocationFence++
	}
	return c, e
}

type fixture struct {
	db       *sql.DB
	config   *mysql.Config
	core     *Store
	gate     *mysqlstore.Store
	profile  Profile
	desired  release.Desired
	rate     *fixtureRate
	proofs   *fixtureProofs
	key, raw string
}

func setup(t *testing.T, slots int64) *fixture {
	return setupUsagePolicy(t, slots, &UsagePolicy{AdapterRevision: "controlled-test-v1", Mode: "cumulative_until_finish"})
}
func setupUsagePolicy(t *testing.T, slots int64, usagePolicy *UsagePolicy) *fixture {
	t.Helper()
	socket := os.Getenv("MAAS_MYSQL_TEST_SOCKET")
	if socket == "" {
		t.Skip("real MySQL not provided; run scripts/test-mysql.sh")
	}
	if os.Getenv("MAAS_DISPOSABLE_MYSQL") != "1" || !strings.HasPrefix(socket, "/tmp/maas11-mysql.") {
		t.Fatal("requires owned disposable server")
	}
	cfg := mysql.NewConfig()
	cfg.User = "root"
	cfg.Net = "unix"
	cfg.Addr = socket
	cfg.ParseTime = true
	cfg.Loc = time.UTC
	cfg.Timeout = 3 * time.Second
	cfg.ReadTimeout = 5 * time.Second
	cfg.WriteTimeout = 5 * time.Second
	admin, e := sql.Open("mysql", cfg.FormatDSN())
	if e != nil {
		t.Fatal(e)
	}
	name := "maas_kernel_test_" + strings.ReplaceAll(uuid.NewString(), "-", "")
	if _, e = admin.Exec("CREATE DATABASE `" + name + "`"); e != nil {
		t.Fatal(e)
	}
	cfg.DBName = name
	db, e := sql.Open("mysql", cfg.FormatDSN())
	if e != nil {
		t.Fatal(e)
	}
	db.SetMaxOpenConns(12)
	t.Cleanup(func() {
		db.Close()
		if _, e := admin.Exec("DROP DATABASE `" + name + "`"); e != nil {
			t.Error(e)
		}
		admin.Close()
	})
	ctx := context.Background()
	if e = Migrate(ctx, db); e != nil {
		t.Fatal("kernel migration", e)
	}
	if e = Migrate(ctx, db); e != nil {
		t.Fatal("migration repeat", e)
	}
	if e = mysqlstore.Migrate(ctx, db); e != nil {
		t.Fatal(e)
	}
	f := &fixture{db: db, config: cfg, rate: &fixtureRate{}, proofs: &fixtureProofs{}}
	f.core, e = New(db, "controlled-test", []byte(strings.Repeat("x", 32)), f.rate, f.proofs)
	if e != nil {
		t.Fatal(e)
	}
	if e = f.core.Configure(ctx, RatePolicy{Revision: "test-rate-v1", Epoch: 1, WindowMS: 3600000, GlobalLimit: 1000, KeyLimit: 1000}, slots); e != nil {
		t.Fatal(e)
	}
	if e = f.core.ConfigureDiagnostics(ctx, DiagnosticPolicy{64, 262144, "controlled-test-keep-with-request"}); e != nil {
		t.Fatal(e)
	}
	if e = f.core.ReadyRate(ctx, 1); e != nil {
		t.Fatal(e)
	} // fixture initialized its own epoch, not production recovery evidence.
	f.gate, e = mysqlstore.New(db, "controlled-test", f.core)
	if e != nil {
		t.Fatal(e)
	}
	f.desired = release.Desired{CRUID: uuid.NewString(), Namespace: "controlled", Name: "synthetic", Alias: "synthetic", Gateway: api.Ref{Name: "higress"}, Generation: 1, Revision: strings.Repeat("a", 64)}
	st, e := f.gate.Observe(ctx, f.desired)
	if e != nil {
		t.Fatal("observe", e)
	}
	f.profile = Profile{CRUID: f.desired.CRUID, Namespace: "controlled", Name: "synthetic", Alias: "synthetic", Binding: *st.Candidate, SourceID: uuid.NewString(), SourceType: "external", UpstreamModel: "controlled-upstream", ConfigRevision: "test-config-v1", CapabilityRevision: "test-cap-v1", RouteDigest: strings.Repeat("b", 64), RouteName: "test-route", GatewayBinding: "test-gateway-binding", GatewayInstance: uuid.NewString(), GatewayEpoch: 1, Host: "synthetic.internal", SafetyProfile: "test-unverified", ApprovalRef: "controlled-test-only", BoundVerified: true, InputUpper: 100, OutputUpper: 40}
	f.profile.Price = &Price{ID: uuid.NewString(), Version: "test-price-v1", Source: f.profile.SourceID, Model: f.profile.UpstreamModel, Currency: "TST", Scale: 9, Unit: 1000000, Effective: "2026-01-01T00:00:00Z", Input: "2000000000", Cached: "200000000", Output: "8000000000", Reasoning: "8000000000"}
	f.profile.UsagePolicy = usagePolicy
	if e = f.core.RegisterProfile(ctx, f.profile); e != nil {
		t.Fatal("profile", e)
	}
	st, e = f.gate.Read(ctx, f.desired.CRUID)
	if e != nil {
		t.Fatal(e)
	}
	target := st.Candidate.PublicationID
	if e = f.gate.Apply(ctx, release.Command{ID: uuid.NewString(), Action: "Activate", CRUID: st.CRUID, Generation: st.Generation, Fence: st.Fence, Target: &target, Revision: st.Revision, EvidenceRefs: st.EvidenceRefs}); e != nil {
		t.Fatal("activate", e)
	}
	policy := Policy{Window: "utc_day", Revision: "test-budget-v1", Limits: Limits{Requests: ptr("100"), Tokens: ptr("14000"), Money: &MoneyLimit{Currency: "TST", Limit: "52000000"}}}
	f.key, f.raw, e = f.core.CreateKey(ctx, policy)
	if e != nil {
		t.Fatal(e)
	}
	return f
}
func (f *fixture) input(t *testing.T) Input {
	t.Helper()
	p := Policy{Window: "utc_day", Revision: "test-budget-v1", Limits: Limits{Requests: ptr("100"), Tokens: ptr("14000"), Money: &MoneyLimit{Currency: "TST", Limit: "52000000"}}}
	plan, e := BuildPlan(f.profile, p, "test-rate-v1")
	if e != nil {
		t.Fatal(e)
	}
	n := time.Now().UTC().Add(-time.Second).Truncate(time.Millisecond)
	return Input{RequestID: uuid.NewString(), KeyID: f.key, KeyEpoch: 1, Owner: uuid.NewString(), TicketHash: strings.Repeat("c", 64), Profile: f.profile, Plan: plan, Received: n, Issued: n, Expires: n.Add(30 * time.Second), Deadline: n.Add(time.Minute)}
}
func mustAdmit(t *testing.T, f *fixture, in Input) Snapshot {
	t.Helper()
	s, e := f.core.Admit(context.Background(), f.gate, in)
	if e != nil {
		t.Fatal("admit", e)
	}
	return s
}
func finalFor(s Snapshot) Final {
	return Final{EventID: uuid.NewString(), RequestID: s.Input.RequestID, Owner: s.Input.Owner, OwnerFence: s.OwnerFence, Result: "cancelled", Usage: Usage{Source: "unavailable", Missing: ptr("not_provided")}}
}
func readCounter(t *testing.T, f *fixture, dim string) Counter {
	t.Helper()
	var c Counter
	if e := f.db.QueryRow("SELECT known_used,inflight_reserved,uncertainty_held FROM budget_windows WHERE key_id=? AND dimension=?", f.key, dim).Scan(&c.Known, &c.Reserved, &c.Held); e != nil {
		t.Fatal(e)
	}
	return c
}
func assertSQL(t *testing.T, db *sql.DB, q string, want int64, args ...any) {
	t.Helper()
	var got int64
	if e := db.QueryRow(q, args...).Scan(&got); e != nil {
		t.Fatal(e)
	}
	if got != want {
		t.Fatalf("%s got=%d want=%d", q, got, want)
	}
}
func TestMySQLKernel(t *testing.T) {
	ctx := context.Background()
	t.Run("atomic_three_dimensions_and_duplicate_ticket", func(t *testing.T) {
		f := setup(t, 2)
		in := f.input(t)
		mustAdmit(t, f, in)
		if _, e := f.core.Admit(ctx, f.gate, in); !errors.Is(e, ErrConflict) {
			t.Fatal(e)
		}
		if c := readCounter(t, f, "tokens"); c.Reserved != "140" || c.Known != "0" {
			t.Fatal(c)
		}
		if c := readCounter(t, f, "money"); c.Reserved != "520000" {
			t.Fatal(c)
		}
		assertSQL(t, f.db, "SELECT COUNT(*) FROM generation_requests", 1)
		assertSQL(t, f.db, "SELECT SUM(grants) FROM rate_window_grants", 2)
	})
	t.Run("two_replicas_one_global_slot", func(t *testing.T) {
		f := setup(t, 1)
		other, _ := New(f.db, "controlled-test", f.core.pepper, f.rate, f.proofs)
		inputs := []Input{f.input(t), f.input(t)}
		cores := []*Store{f.core, other}
		start := make(chan struct{})
		results := make(chan error, 2)
		for i := range cores {
			go func(i int) { <-start; _, e := cores[i].Admit(ctx, f.gate, inputs[i]); results <- e }(i)
		}
		close(start)
		wins := 0
		for range cores {
			e := <-results
			if e == nil {
				wins++
			} else if !errors.Is(e, ErrBusy) && !errors.Is(e, ErrCapacity) {
				t.Fatal(e)
			}
		}
		if wins != 1 {
			t.Fatal("winners", wins)
		}
		assertSQL(t, f.db, "SELECT COUNT(*) FROM generation_requests", 1)
	})
	t.Run("revocation_visible_to_other_replica", func(t *testing.T) {
		f := setup(t, 2)
		in := f.input(t)
		if _, _, e := f.core.Authenticate(ctx, f.raw); e != nil {
			t.Fatal(e)
		}
		if e := f.core.Revoke(ctx, f.key); e != nil {
			t.Fatal(e)
		}
		other, _ := New(f.db, "controlled-test", f.core.pepper, f.rate, f.proofs)
		if _, e := other.Admit(ctx, f.gate, in); !errors.Is(e, ErrKey) {
			t.Fatal(e)
		}
		if _, _, e := other.Authenticate(ctx, f.raw); !errors.Is(e, ErrKey) {
			t.Fatal(e)
		}
		assertSQL(t, f.db, "SELECT COUNT(*) FROM generation_requests", 0)
	})
	t.Run("token_rejection_rolls_back_every_dimension", func(t *testing.T) {
		f := setup(t, 2)
		p := Policy{Window: "utc_day", Revision: "small-v1", Limits: Limits{Requests: ptr("10"), Tokens: ptr("139")}}
		if e := f.core.UpdatePolicy(ctx, f.key, p); e != nil {
			t.Fatal(e)
		}
		in := f.input(t)
		in.Plan, _ = BuildPlan(f.profile, p, "test-rate-v1")
		if _, e := f.core.Admit(ctx, f.gate, in); !errors.Is(e, ErrTokens) {
			t.Fatal(e)
		}
		assertSQL(t, f.db, "SELECT COUNT(*) FROM generation_requests", 0)
		assertSQL(t, f.db, "SELECT COUNT(*) FROM budget_windows", 0)
	})
	t.Run("unknown_usage_duplicate_event_late_close_does_not_refund", func(t *testing.T) {
		f := setup(t, 1)
		s := mustAdmit(t, f, f.input(t))
		fin := finalFor(s)
		if e := f.core.Finalize(ctx, fin); e != nil {
			t.Fatal("finalize", e)
		}
		if e := f.core.Finalize(ctx, fin); e != nil {
			t.Fatal("duplicate", e)
		}
		conflicting := fin
		conflicting.Result = "failed"
		if e := f.core.Finalize(ctx, conflicting); !errors.Is(e, ErrConflict) {
			t.Fatal(e)
		}
		c := readCounter(t, f, "tokens")
		if c.Held != "140" || c.Reserved != "0" || c.Known != "0" {
			t.Fatal(c)
		}
		assertSQL(t, f.db, "SELECT COUNT(*) FROM concurrency_slots WHERE state='QUARANTINED'", 1)
		ref := uuid.NewString()
		if e := f.core.Release(ctx, s.Input.RequestID, uuid.NewString(), ref); e != nil {
			t.Fatal(e)
		}
		if e := f.core.Release(ctx, s.Input.RequestID, uuid.NewString(), ref); e != nil {
			t.Fatal(e)
		}
		if c2 := readCounter(t, f, "tokens"); c2 != c {
			t.Fatal("release altered budget", c2)
		}
		assertSQL(t, f.db, "SELECT COUNT(*) FROM usage_events", 1)
		assertSQL(t, f.db, "SELECT SUM(finalized_total) FROM usage_daily", 1)
		assertSQL(t, f.db, "SELECT COUNT(*) FROM slot_release_log", 1)
	})
	t.Run("known_usage_uses_frozen_price_and_rounds_once", func(t *testing.T) {
		f := setup(t, 1)
		s := mustAdmit(t, f, f.input(t))
		fin := finalFor(s)
		in, out, cached, reason := int64(12), int64(7), int64(4), int64(3)
		fin.Result = "succeeded"
		fin.Submitted = true
		fin.EvidenceRef = uuid.NewString()
		fin.Usage = Usage{Input: &in, Output: &out, Cached: &cached, Reasoning: &reason, Source: "upstream"}
		if e := f.core.Finalize(ctx, fin); e != nil {
			t.Fatal(e)
		}
		if c := readCounter(t, f, "tokens"); c.Known != "19" || c.Reserved != "0" || c.Held != "0" {
			t.Fatal(c)
		}
		if c := readCounter(t, f, "money"); c.Known != "72800" {
			t.Fatal(c)
		}
		assertSQL(t, f.db, "SELECT COUNT(*) FROM concurrency_slots WHERE state='FREE'", 1)
	})
	t.Run("no_send_only_from_bound_proof", func(t *testing.T) {
		f := setup(t, 1)
		s := mustAdmit(t, f, f.input(t))
		f.proofs.noSend = true
		fin := finalFor(s)
		fin.Result = "failed"
		fin.EvidenceRef = uuid.NewString()
		f.proofs.wrong = true
		if e := f.core.Finalize(ctx, fin); !errors.Is(e, ErrConflict) {
			t.Fatal(e)
		}
		f.proofs.wrong = false
		if e := f.core.Finalize(ctx, fin); e != nil {
			t.Fatal(e)
		}
		if c := readCounter(t, f, "requests"); c.Known != "0" || c.Reserved != "0" || c.Held != "0" {
			t.Fatal(c)
		}
	})
	t.Run("pause_delete_and_stale_epoch", func(t *testing.T) {
		f := setup(t, 2)
		in := f.input(t)
		s := mustAdmit(t, f, in)
		f.desired.Generation++
		f.desired.Paused = true
		if _, e := f.gate.Observe(ctx, f.desired); e != nil {
			t.Fatal(e)
		}
		if _, e := f.core.Admit(ctx, f.gate, f.input(t)); e == nil {
			t.Fatal("paused admitted")
		}
		safe, e := f.gate.Drain(ctx, f.desired.CRUID, "")
		if e != nil || safe {
			t.Fatal("drain", safe, e)
		}
		fin := finalFor(s)
		fin.EvidenceRef = uuid.NewString()
		if e = f.core.Finalize(ctx, fin); e != nil {
			t.Fatal(e)
		}
		safe, e = f.gate.Drain(ctx, f.desired.CRUID, "")
		if e != nil || !safe {
			t.Fatal("drain", safe, e)
		}
		f.desired.Deleting = true
		if _, e = f.gate.Observe(ctx, f.desired); e != nil {
			t.Fatal(e)
		}
		f.desired.Deleting = false
		f.desired.Paused = false
		f.desired.Generation++
		if _, e = f.gate.Observe(ctx, f.desired); e == nil {
			t.Fatal("tombstone resurrected")
		}
	})
	t.Run("publish_close_cannot_overtake_admission_commit", func(t *testing.T) {
		f := setup(t, 2)
		gate := &blockingGate{gate: f.gate, locked: make(chan struct{}), resume: make(chan struct{})}
		result := make(chan error, 1)
		in := f.input(t)
		go func() { _, e := f.core.Admit(ctx, gate, in); result <- e }()
		<-gate.locked
		f.desired.Generation++
		f.desired.Paused = true
		if _, e := f.gate.Observe(ctx, f.desired); e == nil {
			t.Error("close passed exclusive capacity lock")
		}
		close(gate.resume)
		if e := <-result; e != nil {
			t.Fatal(e)
		}
		if _, e := f.gate.Observe(ctx, f.desired); e != nil {
			t.Fatal(e)
		}
		if _, e := f.core.Admit(ctx, f.gate, f.input(t)); e == nil {
			t.Fatal("post-close admitted")
		}
	})
	t.Run("restart_fences_owner_and_preserves_unknown_hold", func(t *testing.T) {
		f := setup(t, 1)
		in := f.input(t)
		in.Expires = time.Now().UTC().Add(200 * time.Millisecond)
		in.Deadline = in.Expires.Add(200 * time.Millisecond)
		s := mustAdmit(t, f, in)
		old := finalFor(s)
		if e := f.core.Recover(ctx, s.Input.RequestID, uuid.NewString()); !errors.Is(e, ErrBusy) {
			t.Fatal("not past original deadline", e)
		}
		time.Sleep(time.Until(in.Deadline.Add(10 * time.Millisecond)))
		restarted, _ := New(f.db, "controlled-test", f.core.pepper, f.rate, f.proofs)
		if e := restarted.Recover(ctx, s.Input.RequestID, uuid.NewString()); e != nil {
			t.Fatal("recover", e)
		}
		if e := f.core.Finalize(ctx, old); !errors.Is(e, ErrConflict) {
			t.Fatal("old owner", e)
		}
		if e := restarted.Release(ctx, s.Input.RequestID, uuid.NewString(), uuid.NewString()); e != nil {
			t.Fatal(e)
		}
		if c := readCounter(t, f, "tokens"); c.Held != "140" {
			t.Fatal(c)
		}
	})
	t.Run("rate_epoch_and_missing_or_expired_dependencies_fail_closed", func(t *testing.T) {
		f := setup(t, 1)
		f.rate.stale = true
		if _, e := f.core.Admit(ctx, f.gate, f.input(t)); e == nil {
			t.Fatal("old epoch")
		}
		f.rate.stale = false
		f.proofs.stale = true
		if _, e := f.core.Admit(ctx, f.gate, f.input(t)); e == nil {
			t.Fatal("expired proof")
		}
		f.proofs.stale = false
		missing, _ := New(f.db, "controlled-test", f.core.pepper, nil, nil)
		missingGate, _ := mysqlstore.New(f.db, "controlled-test", missing)
		if _, e := missing.Admit(ctx, missingGate, f.input(t)); e == nil {
			t.Fatal("missing Redis/proofs")
		}
		assertSQL(t, f.db, "SELECT COUNT(*) FROM generation_requests", 0)
	})
	t.Run("late_proof_cannot_release_reallocated_slot", func(t *testing.T) {
		f := setup(t, 1)
		s := mustAdmit(t, f, f.input(t))
		fin := finalFor(s)
		fin.EvidenceRef = uuid.NewString()
		if e := f.core.Finalize(ctx, fin); e != nil {
			t.Fatal(e)
		}
		newer := mustAdmit(t, f, f.input(t))
		if newer.AllocationFence != s.AllocationFence+1 {
			t.Fatal("fence did not increase")
		}
		if e := f.core.Release(ctx, s.Input.RequestID, uuid.NewString(), fin.EvidenceRef); e != nil {
			t.Fatal("old log idempotence", e)
		}
		assertSQL(t, f.db, "SELECT COUNT(*) FROM concurrency_slots WHERE state='HELD' AND request_id=?", 1, newer.Input.RequestID)
	})
	t.Run("real_commit_ack_loss_never_reauthorizes", func(t *testing.T) {
		f := setup(t, 1)
		connector, e := mysql.NewConnector(f.config)
		if e != nil {
			t.Fatal(e)
		}
		fault := &ackConnector{Connector: connector}
		db := sql.OpenDB(fault)
		defer db.Close()
		core, _ := New(db, "controlled-test", f.core.pepper, f.rate, f.proofs)
		in := f.input(t)
		fault.lose.Store(true)
		if _, e = core.Admit(ctx, f.gate, in); !errors.Is(e, ErrCommitUnknown) {
			t.Fatal(e)
		}
		snap, state, e := core.ReadRequest(ctx, in.RequestID)
		if e != nil || state != "in_progress" {
			t.Fatal(state, e)
		}
		if _, e = core.Admit(ctx, f.gate, in); !errors.Is(e, ErrConflict) {
			t.Fatal(e)
		}
		fin := finalFor(snap)
		fault.lose.Store(true)
		if e = core.Finalize(ctx, fin); !errors.Is(e, ErrCommitUnknown) {
			t.Fatal(e)
		}
		if e = core.Finalize(ctx, fin); e != nil {
			t.Fatal(e)
		}
		assertSQL(t, f.db, "SELECT COUNT(*) FROM usage_events", 1)
		if c := readCounter(t, f, "tokens"); c.Held != "140" {
			t.Fatal(c)
		}
	})
	t.Run("budget_bound_breach_records_actual_and_blocks", func(t *testing.T) {
		f := setup(t, 1)
		s := mustAdmit(t, f, f.input(t))
		fin := finalFor(s)
		in, out := int64(150), int64(50)
		fin.Usage = Usage{Input: &in, Output: &out, Source: "upstream"}
		fin.Result = "succeeded"
		fin.Submitted = true
		if e := f.core.Finalize(ctx, fin); e != nil {
			t.Fatal(e)
		}
		if c := readCounter(t, f, "tokens"); c.Known != "200" {
			t.Fatal(c)
		}
		assertSQL(t, f.db, "SELECT COUNT(*) FROM platform_keys WHERE blocked=TRUE", 1)
		f.desired.Generation++
		f.desired.Revision = strings.Repeat("d", 64)
		next, e := f.gate.Observe(ctx, f.desired)
		if e != nil {
			t.Fatal(e)
		}
		p := f.profile
		p.Binding = *next.Candidate
		if e = f.core.RegisterProfile(ctx, p); !errors.Is(e, ErrBound) {
			t.Fatal("breached capability cannot be reintroduced in another publication", e)
		}
	})
}

type blockingGate struct {
	gate           ActiveGate
	locked, resume chan struct{}
	once           sync.Once
}

func (g *blockingGate) LockActive(ctx context.Context, tx *sql.Tx, uid string) (release.Binding, error) {
	b, e := g.gate.LockActive(ctx, tx, uid)
	g.once.Do(func() { close(g.locked); <-g.resume })
	return b, e
}

type ackConnector struct {
	driver.Connector
	lose atomic.Bool
}

func (c *ackConnector) Connect(ctx context.Context) (driver.Conn, error) {
	v, e := c.Connector.Connect(ctx)
	if e != nil {
		return nil, e
	}
	return &ackConn{Conn: v, c: c}, nil
}

type ackConn struct {
	driver.Conn
	c *ackConnector
}

func (c *ackConn) BeginTx(ctx context.Context, o driver.TxOptions) (driver.Tx, error) {
	v, e := c.Conn.(driver.ConnBeginTx).BeginTx(ctx, o)
	if e != nil {
		return nil, e
	}
	return &ackTx{Tx: v, c: c.c}, nil
}
func (c *ackConn) ExecContext(ctx context.Context, q string, a []driver.NamedValue) (driver.Result, error) {
	return c.Conn.(driver.ExecerContext).ExecContext(ctx, q, a)
}
func (c *ackConn) QueryContext(ctx context.Context, q string, a []driver.NamedValue) (driver.Rows, error) {
	return c.Conn.(driver.QueryerContext).QueryContext(ctx, q, a)
}

type ackTx struct {
	driver.Tx
	c *ackConnector
}

func (tx *ackTx) Commit() error {
	if e := tx.Tx.Commit(); e != nil {
		return e
	}
	if tx.c.lose.Swap(false) {
		return errors.New("test-only ACK loss after real commit")
	}
	return nil
}
