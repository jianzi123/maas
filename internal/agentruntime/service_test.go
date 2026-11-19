package agentruntime

import (
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"net/http/httptest"
	"reflect"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"
)

// This store and scripted model are TEST DOUBLES, never production providers.
type memoryStore struct {
	mu   sync.Mutex
	docs map[string][]byte
}

func (m *memoryStore) Get(_ context.Context, id string) (Session, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	var v Session
	b, ok := m.docs[id]
	if !ok {
		return v, ErrNotFound
	}
	_ = json.Unmarshal(b, &v)
	return v, nil
}
func (m *memoryStore) List(ctx context.Context, owner string) ([]Session, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	v := []Session{}
	for _, b := range m.docs {
		var s Session
		_ = json.Unmarshal(b, &s)
		if s.Owner == owner && !s.Deleted {
			v = append(v, s)
		}
	}
	return v, nil
}
func (m *memoryStore) CompareAndSwap(_ context.Context, v Session, expected int64) error {
	m.mu.Lock()
	defer m.mu.Unlock()
	var old Session
	_ = json.Unmarshal(m.docs[v.ID], &old)
	if old.Revision != expected {
		return ErrConflict
	}
	b, _ := json.Marshal(v)
	m.docs[v.ID] = b
	return nil
}

type scriptedModel struct {
	f     func(context.Context, Request, func(string) error) (Response, error)
	calls atomic.Int32
}

func (m *scriptedModel) Supports(_ context.Context, v Model) error {
	if v.Protocol == "text-v1" || v.Protocol == "tools-v1" {
		return nil
	}
	return ErrCapability
}
func (m *scriptedModel) Generate(c context.Context, r Request, e func(string) error) (Response, error) {
	m.calls.Add(1)
	return m.f(c, r, e)
}
func known() Usage { t, m := int64(10), int64(3); return Usage{Tokens: &t, Money: &m, Currency: "TST"} }
func limits() Limits {
	return Limits{Currency: "TST", Steps: 4, Calls: 4, Tokens: 100, Money: 100, Duration: 5 * time.Second, ToolTimeout: time.Second, ApprovalTTL: time.Minute, InputBytes: 32768, OutputBytes: 8192, Events: 500}
}

var actor = Principal{ID: "owner-a", Revision: "auth-v1", Permissions: map[string]bool{"tools.calculate": true, "models.read": true, "tools.write": true}}

func setupService(t *testing.T, f func(context.Context, Request, func(string) error) (Response, error), tools ...Tool) (*Service, *scriptedModel, Session) {
	t.Helper()
	if len(tools) == 0 {
		tools = []Tool{Calculator{}, ModelDirectory{Read: func(_ context.Context, p Principal) ([]string, error) { return []string{p.ID + "-visible"}, nil }}}
	}
	reg, e := NewRegistry(tools...)
	if e != nil {
		t.Fatal(e)
	}
	model := &scriptedModel{f: f}
	s, e := NewService(&memoryStore{docs: map[string][]byte{}}, model, reg, limits())
	if e != nil {
		t.Fatal(e)
	}
	session, e := s.Create(context.Background(), actor, "test")
	if e != nil {
		t.Fatal(e)
	}
	return s, model, session
}
func input(mode string) Submit {
	protocol := "text-v1"
	if mode == "agent" {
		protocol = "tools-v1"
	}
	return Submit{ClientID: "client-1", Text: "calculate", Mode: mode, Model: Model{Alias: "controlled", Source: "test-only", Revision: "1", Protocol: protocol}}
}
func send(t *testing.T, s *Service, v Session, in Submit) Run {
	t.Helper()
	r, e := s.Submit(context.Background(), actor, v.ID, in)
	if e != nil {
		t.Fatal(e)
	}
	return r
}
func readRun(t *testing.T, s *Service, v Session, r Run) Run {
	t.Helper()
	doc, e := s.Get(context.Background(), actor, v.ID)
	if e != nil {
		t.Fatal(e)
	}
	return *run(&doc, r.ID)
}
func plain(_ context.Context, r Request, emit func(string) error) (Response, error) {
	if e := emit("hello"); e != nil {
		return Response{}, e
	}
	return Response{RequestID: r.RequestID, TerminalConfirmed: true, Finish: "stop", Usage: known()}, nil
}
func TestChatPersistenceIdempotencyAndReplay(t *testing.T) {
	s, m, v := setupService(t, plain)
	r := send(t, s, v, input("chat"))
	if r.Limits.Calls != 1 || r.Limits.Steps != 1 {
		t.Fatal("chat must use one model call", r.Limits)
	}
	same := send(t, s, v, input("chat"))
	if same.ID != r.ID {
		t.Fatal("duplicate run")
	}
	in := input("chat")
	in.Text = "different"
	if _, e := s.Submit(context.Background(), actor, v.ID, in); !errors.Is(e, ErrConflict) {
		t.Fatal(e)
	}
	if e := s.Drive(context.Background(), actor, v.ID, r.ID); e != nil {
		t.Fatal(e)
	}
	got := readRun(t, s, v, r)
	if got.Status != "completed" || *got.Usage.Tokens != 10 {
		t.Fatal(got)
	}
	a, e := s.Events(context.Background(), actor, v.ID, r.ID, 0)
	if e != nil {
		t.Fatal(e)
	}
	b, _ := s.Events(context.Background(), actor, v.ID, r.ID, 0)
	if !reflect.DeepEqual(a, b) || m.calls.Load() != 1 {
		t.Fatal("replay executed work")
	}
	if e = s.Drive(context.Background(), actor, v.ID, r.ID); !errors.Is(e, ErrConflict) {
		t.Fatal(e)
	}
	other := actor
	other.ID = "owner-b"
	if _, e = s.Get(context.Background(), other, v.ID); !errors.Is(e, ErrNotFound) {
		t.Fatal("owner isolation", e)
	}
	if e = s.Cancel(context.Background(), other, v.ID, r.ID); !errors.Is(e, ErrNotFound) {
		t.Fatal(e)
	}
	// A new Service reads the same durable projection (memory store here is a test double).
	s2, _ := NewService(s.Store, m, s.Tools, s.Limits)
	got2, e := s2.Get(context.Background(), actor, v.ID)
	if e != nil || len(got2.Messages) != 2 {
		t.Fatal(e, got2)
	}
}
func TestAgentExecutesRealToolsThenObservesResults(t *testing.T) {
	s, m, v := setupService(t, func(_ context.Context, r Request, emit func(string) error) (Response, error) {
		for _, msg := range r.Messages {
			if msg.Role == "tool" && msg.Parts[0].Name == "list_visible_models" {
				if msg.Parts[0].Text != `["owner-a-visible"]` {
					t.Fatal(msg)
				}
				_ = emit("42; catalog visible")
				return Response{RequestID: r.RequestID, TerminalConfirmed: true, Finish: "stop", Usage: known()}, nil
			}
		}
		return Response{RequestID: r.RequestID, TerminalConfirmed: true, Finish: "tool_calls", Usage: known(), Calls: []Call{{ID: "calc-1", Name: "bounded_arithmetic", Arguments: json.RawMessage(`{"a":6,"b":7,"op":"multiply"}`)}, {ID: "catalog-1", Name: "list_visible_models", Arguments: json.RawMessage(`{}`)}}}, nil
	})
	r := send(t, s, v, input("agent"))
	if e := s.Drive(context.Background(), actor, v.ID, r.ID); e != nil {
		t.Fatal(e)
	}
	got := readRun(t, s, v, r)
	if got.Status != "completed" || len(got.Steps) != 2 || m.calls.Load() != 2 || got.Steps[0].Calls[0].Result != "42" || *got.Usage.Tokens != 20 {
		t.Fatal(got)
	}
	events, _ := s.Events(context.Background(), actor, v.ID, r.ID, 0)
	b, _ := json.MarshalIndent(events, "", "  ")
	t.Log("CONTROLLED MODEL / REAL TOOLS TRACE", string(b))
}
func TestToolProtocolAndLimits(t *testing.T) {
	cases := []struct {
		name   string
		calls  []Call
		finish string
		usage  Usage
		reason string
	}{
		{"unknown", []Call{{ID: "1", Name: "shell", Arguments: json.RawMessage(`{}`)}}, "tool_calls", known(), "tool_forbidden"},
		{"schema", []Call{{ID: "1", Name: "bounded_arithmetic", Arguments: json.RawMessage(`{"a":"bad"}`)}}, "tool_calls", known(), "invalid_tool_call"},
		{"duplicate", []Call{{ID: "1", Name: "list_visible_models", Arguments: json.RawMessage(`{}`)}, {ID: "1", Name: "list_visible_models", Arguments: json.RawMessage(`{}`)}}, "tool_calls", known(), "invalid_tool_call"},
		{"eof", nil, "", known(), "model_protocol_error"},
		{"empty_tools", nil, "tool_calls", known(), "model_protocol_error"},
		{"unknown_usage", []Call{{ID: "1", Name: "list_visible_models", Arguments: json.RawMessage(`{}`)}}, "tool_calls", Usage{}, "usage_unknown"},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			s, _, v := setupService(t, func(_ context.Context, r Request, _ func(string) error) (Response, error) {
				return Response{RequestID: r.RequestID, TerminalConfirmed: true, Finish: tc.finish, Usage: tc.usage, Calls: tc.calls}, nil
			})
			r := send(t, s, v, input("agent"))
			if e := s.Drive(context.Background(), actor, v.ID, r.ID); e != nil {
				t.Fatal(e)
			}
			got := readRun(t, s, v, r)
			if got.Reason != tc.reason {
				t.Fatal(got)
			}
		})
	}
	t.Run("steps", func(t *testing.T) {
		var n int
		s, _, v := setupService(t, func(_ context.Context, r Request, _ func(string) error) (Response, error) {
			n++
			return Response{RequestID: r.RequestID, TerminalConfirmed: true, Finish: "tool_calls", Usage: known(), Calls: []Call{{ID: strings.Repeat("x", n), Name: "list_visible_models", Arguments: json.RawMessage(`{}`)}}}, nil
		})
		s.Limits.Steps = 1
		r := send(t, s, v, input("agent"))
		_ = s.Drive(context.Background(), actor, v.ID, r.ID)
		if readRun(t, s, v, r).Reason != "step_or_call_limit" {
			t.Fatal(readRun(t, s, v, r))
		}
	})
	t.Run("permission", func(t *testing.T) {
		s, _, v := setupService(t, plain)
		p := actor
		p.Permissions = map[string]bool{}
		r, e := s.Submit(context.Background(), p, v.ID, input("agent"))
		if e != nil {
			t.Fatal(e)
		}
		s.Model = &scriptedModel{f: func(_ context.Context, r Request, _ func(string) error) (Response, error) {
			if len(r.Tools) != 0 {
				t.Fatal("unauthorized schemas")
			}
			return Response{RequestID: r.RequestID, TerminalConfirmed: true, Finish: "tool_calls", Calls: []Call{{ID: "x", Name: "list_visible_models", Arguments: json.RawMessage(`{}`)}}}, nil
		}}
		_ = s.Drive(context.Background(), p, v.ID, r.ID)
		if readRun(t, s, v, r).Reason != "tool_forbidden" {
			t.Fatal(readRun(t, s, v, r))
		}
	})
}

type testTool struct {
	spec  ToolSpec
	f     func(context.Context) (string, error)
	calls atomic.Int32
}

func (t *testTool) Spec() ToolSpec { return t.spec }
func (t *testTool) Execute(ctx context.Context, _ Principal, _ string, _ json.RawMessage) (string, error) {
	t.calls.Add(1)
	return t.f(ctx)
}
func controlledTool(write bool) *testTool {
	effect, permission := "read", "models.read"
	if write {
		effect, permission = "write", "tools.write"
	}
	return &testTool{spec: ToolSpec{Name: "controlled_tool", Version: "1", Permission: permission, Effect: effect, Approval: write, Schema: json.RawMessage(`{"type":"object","additionalProperties":false}`)}, f: func(context.Context) (string, error) { return "ok", nil }}
}
func toolResponse(_ context.Context, r Request, _ func(string) error) (Response, error) {
	for _, m := range r.Messages {
		if m.Role == "tool" {
			return Response{RequestID: r.RequestID, TerminalConfirmed: true, Finish: "stop", Usage: known()}, nil
		}
	}
	return Response{RequestID: r.RequestID, TerminalConfirmed: true, Finish: "tool_calls", Usage: known(), Calls: []Call{{ID: "tool-1", Name: "controlled_tool", Arguments: json.RawMessage(`{}`)}}}, nil
}
func TestApprovalBindingExpiryAndResume(t *testing.T) {
	tool := controlledTool(true)
	s, m, v := setupService(t, toolResponse, tool)
	r := send(t, s, v, input("agent"))
	_ = s.Drive(context.Background(), actor, v.ID, r.ID)
	got := readRun(t, s, v, r)
	if got.Status != "waiting_approval" || tool.calls.Load() != 0 {
		t.Fatal(got)
	}
	c := got.Steps[0].Calls[0]
	if e := s.Approve(context.Background(), actor, v.ID, r.ID, c.ID, "wrong", true); !errors.Is(e, ErrConflict) {
		t.Fatal(e)
	}
	changed := actor
	changed.Revision = "revoked"
	if e := s.Approve(context.Background(), changed, v.ID, r.ID, c.ID, c.Hash, true); !errors.Is(e, ErrConflict) {
		t.Fatal(e)
	}
	if e := s.Approve(context.Background(), actor, v.ID, r.ID, c.ID, c.Hash, true); e != nil {
		t.Fatal(e)
	}
	if e := s.Approve(context.Background(), actor, v.ID, r.ID, c.ID, c.Hash, true); !errors.Is(e, ErrConflict) {
		t.Fatal(e)
	}
	s2, _ := NewService(s.Store, m, s.Tools, s.Limits)
	if e := s2.Drive(context.Background(), actor, v.ID, r.ID); e != nil {
		t.Fatal(e)
	}
	if readRun(t, s, v, r).Status != "completed" || tool.calls.Load() != 1 || m.calls.Load() != 2 {
		t.Fatal(readRun(t, s, v, r))
	}
	t.Run("expired", func(t *testing.T) {
		tool := controlledTool(true)
		s, _, v := setupService(t, toolResponse, tool)
		r := send(t, s, v, input("agent"))
		_ = s.Drive(context.Background(), actor, v.ID, r.ID)
		_, _ = s.mutate(context.Background(), actor, v.ID, func(v *Session) error {
			run(v, r.ID).Steps[0].Calls[0].ApprovalExpires = time.Now().Add(-time.Second)
			return nil
		})
		c := readRun(t, s, v, r).Steps[0].Calls[0]
		if e := s.Approve(context.Background(), actor, v.ID, r.ID, c.ID, c.Hash, true); !errors.Is(e, ErrConflict) {
			t.Fatal(e)
		}
	})
}
func TestCancelWaitsForActualTransportStop(t *testing.T) {
	started, release := make(chan struct{}), make(chan struct{})
	s, _, v := setupService(t, func(ctx context.Context, r Request, _ func(string) error) (Response, error) {
		close(started)
		<-ctx.Done()
		<-release
		return Response{}, ctx.Err()
	})
	r := send(t, s, v, input("chat"))
	done := make(chan error)
	go func() { done <- s.Drive(context.Background(), actor, v.ID, r.ID) }()
	<-started
	if e := s.Cancel(context.Background(), actor, v.ID, r.ID); e != nil {
		t.Fatal(e)
	}
	got := readRun(t, s, v, r)
	if got.Status != "running" || !got.CancelRequested {
		t.Fatal("early terminal", got)
	}
	close(release)
	if e := <-done; e != nil {
		t.Fatal(e)
	}
	if readRun(t, s, v, r).Status != "cancelled" {
		t.Fatal(readRun(t, s, v, r))
	}
}
func TestConcurrentClaimAndRecoveryNeverReplaysUnknown(t *testing.T) {
	started, release := make(chan struct{}), make(chan struct{})
	s, m, v := setupService(t, func(ctx context.Context, r Request, emit func(string) error) (Response, error) {
		close(started)
		<-release
		return plain(ctx, r, emit)
	})
	r := send(t, s, v, input("chat"))
	done := make(chan error)
	go func() { done <- s.Drive(context.Background(), actor, v.ID, r.ID) }()
	<-started
	if e := s.Drive(context.Background(), actor, v.ID, r.ID); !errors.Is(e, ErrConflict) {
		t.Fatal(e)
	}
	in := input("chat")
	in.ClientID = "second"
	if _, e := s.Submit(context.Background(), actor, v.ID, in); !errors.Is(e, ErrConflict) {
		t.Fatal(e)
	}
	// Simulate administrative confirmation the old executor is dead, then fence
	// its late response to check it cannot commit or cause another model call.
	if e := s.Recover(context.Background(), actor, v.ID, r.ID); e != nil {
		t.Fatal(e)
	}
	if readRun(t, s, v, r).Status != "needs_confirmation" {
		t.Fatal(readRun(t, s, v, r))
	}
	close(release)
	<-done
	if e := s.Drive(context.Background(), actor, v.ID, r.ID); !errors.Is(e, ErrConflict) {
		t.Fatal(e)
	}
	if m.calls.Load() != 1 {
		t.Fatal("unknown model replay")
	}
	for _, phase := range []string{"tool_inflight", "ready", "tools"} {
		t.Run(phase, func(t *testing.T) {
			s, m, v := setupService(t, plain)
			r := send(t, s, v, input("chat"))
			_, _ = s.mutate(context.Background(), actor, v.ID, func(v *Session) error {
				rr := run(v, r.ID)
				rr.Status = "running"
				rr.Executor = "dead"
				rr.Checkpoint.Phase = phase
				return nil
			})
			_ = s.Recover(context.Background(), actor, v.ID, r.ID)
			got := readRun(t, s, v, r)
			want := "accepted"
			if phase == "tool_inflight" {
				want = "needs_confirmation"
			}
			if got.Status != want || m.calls.Load() != 0 {
				t.Fatal(got)
			}
		})
	}
}
func TestToolTimeoutAndOutputBound(t *testing.T) {
	for _, mode := range []string{"timeout", "oversize"} {
		t.Run(mode, func(t *testing.T) {
			tool := controlledTool(false)
			tool.f = func(ctx context.Context) (string, error) {
				if mode == "timeout" {
					<-ctx.Done()
					return "", ctx.Err()
				}
				return strings.Repeat("x", 9000), nil
			}
			s, _, v := setupService(t, toolResponse, tool)
			s.Limits.ToolTimeout = time.Millisecond
			r := send(t, s, v, input("agent"))
			_ = s.Drive(context.Background(), actor, v.ID, r.ID)
			got := readRun(t, s, v, r)
			want := "tool_timeout"
			if mode == "oversize" {
				want = "tool_output_limit"
			}
			if got.Reason != want {
				t.Fatal(got)
			}
		})
	}
}

type testAuth struct{}

func (testAuth) Authenticate(r *http.Request, write bool) (Principal, error) {
	if write && r.Header.Get("X-CSRF-Token") != "verified" {
		return Principal{}, ErrForbidden
	}
	return actor, nil
}
func TestHTTPStrictIdentityAndReadOnlyReplay(t *testing.T) {
	s, m, v := setupService(t, plain)
	h := ControlledHandler{Service: s, Auth: testAuth{}}
	rr := httptest.NewRecorder()
	req := httptest.NewRequest("POST", "/__maas/controlled-agent/v0/sessions", strings.NewReader(`{"title":"x","owner":"other"}`))
	req.Header.Set("X-CSRF-Token", "verified")
	h.ServeHTTP(rr, req)
	if rr.Code != 400 {
		t.Fatal(rr.Code)
	}
	r := send(t, s, v, input("chat"))
	_ = s.Drive(context.Background(), actor, v.ID, r.ID)
	for i := 0; i < 2; i++ {
		rr = httptest.NewRecorder()
		req = httptest.NewRequest("GET", "/__maas/controlled-agent/v0/sessions/"+v.ID+"/runs/"+r.ID+"/events", nil)
		req.Header.Set("Accept", "text/event-stream")
		h.ServeHTTP(rr, req)
		if rr.Code != 200 || !strings.Contains(rr.Body.String(), "event: run.completed") || m.calls.Load() != 1 {
			t.Fatal(rr.Code, rr.Body)
		}
	}
}
