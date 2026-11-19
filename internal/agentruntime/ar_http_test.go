package agentruntime

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"net/http/httptest"
	"os"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/google/uuid"
)

var arActor = Principal{ID: "4c421973-919f-4b8a-997f-909fc6fd010a", Revision: "policy-1", Permissions: map[string]bool{"tools.calculate": true, "models.read": true, "tools.write": true, "tools.approve": true}}

type arTestAuth struct {
	mu sync.Mutex
	p  Principal
}

func (a *arTestAuth) Authenticate(r *http.Request, write bool) (Principal, error) {
	a.mu.Lock()
	defer a.mu.Unlock()
	if write && r.Header.Get("X-CSRF-Token") != "controlled-verified" {
		return Principal{}, ErrForbidden
	}
	return a.p, nil
}

type arTestCatalog struct{}

func (arTestCatalog) Resolve(_ context.Context, _ Principal, alias, mode string) (Model, error) {
	if alias != "controlled" {
		return Model{}, ErrCapability
	}
	protocol := "text-v1"
	if mode == "agent" {
		protocol = "tools-v1"
	}
	return Model{Alias: alias, Source: "controlled-only", Revision: "test-v1", Protocol: protocol}, nil
}
func (arTestCatalog) Modes(context.Context, Principal) ([]map[string]any, error) {
	return []map[string]any{{"model_alias": "controlled", "text_protocol": "text-v1", "tools_protocol": "tools-v1", "capability_revision": "controlled-v1", "approval_state": "controlled"}}, nil
}
func arPolicy() ARLimits {
	return ARLimits{Steps: 4, Calls: 4, Tools: 8, Duration: 5000, ToolTimeout: 1000, OutputBytes: 8192, ContextTokens: 32768, NoProgress: 3, Tokens: "100", Money: "100", Currency: "TST"}
}
func arUsage() Usage {
	u := known()
	u.Complete = true
	u.Groups = []ARUsageGroup{{Currency: "TST", Price: "controlled-v1", KnownTokens: "10", KnownMoney: "3", HeldTokens: "0", InflightTokens: "0", HeldMoney: "0", InflightMoney: "0"}}
	return u
}
func arPlain(ctx context.Context, r Request, emit func(string) error) (Response, error) {
	if e := emit("你"); e != nil {
		return Response{}, e
	}
	if e := emit("🙂"); e != nil {
		return Response{}, e
	}
	return Response{RequestID: r.RequestID, TerminalConfirmed: true, Finish: "stop", Usage: arUsage()}, nil
}
func setupAR(t *testing.T, f func(context.Context, Request, func(string) error) (Response, error), store SessionStore, tools ...Tool) (*ARHandler, *scriptedModel, *arTestAuth) {
	t.Helper()
	if len(tools) == 0 {
		tools = []Tool{Calculator{}, ModelDirectory{Read: func(_ context.Context, p Principal) ([]string, error) { return []string{p.ID + "/visible"}, nil }}}
	}
	reg, e := NewRegistry(tools...)
	if e != nil {
		t.Fatal(e)
	}
	if store == nil {
		store = &memoryStore{docs: map[string][]byte{}}
	}
	model := &scriptedModel{f: f}
	s, e := NewService(store, model, reg, limits())
	if e != nil {
		t.Fatal(e)
	}
	// This byte counter is only approved for the deterministic controlled model.
	// Real adapters must supply the profile's verified tokenizer/upper bound.
	s.CountContext = func(_ context.Context, r Request) (int64, error) {
		b, _ := json.Marshal(struct {
			Messages []Message
			Tools    []ToolSpec
		}{r.Messages, r.Tools})
		return int64(len(b)), nil
	}
	b, e := os.ReadFile("../../docs/contracts/agent-runtime/ar1-draft2/openapi.json")
	if e != nil {
		t.Fatal(e)
	}
	auth := &arTestAuth{p: arActor}
	s.Reauthorize = func(_ context.Context, p Principal) (Principal, error) {
		auth.mu.Lock()
		defer auth.mu.Unlock()
		return auth.p, nil
	}
	h, e := NewARHandler(s, auth, arTestCatalog{}, arPolicy(), []byte(strings.Repeat("k", 32)), b, 100*time.Millisecond)
	if e != nil {
		t.Fatal(e)
	}
	return h, model, auth
}
func arHTTP(t *testing.T, h *ARHandler, method, path string, body any, etag, schema string, status int) *httptest.ResponseRecorder {
	t.Helper()
	var b []byte
	if body != nil {
		b, _ = json.Marshal(body)
	}
	r := httptest.NewRequest(method, "/api/agent/v1/"+path, strings.NewReader(string(b)))
	r.Header.Set("X-CSRF-Token", "controlled-verified")
	if etag != "" {
		r.Header.Set("If-Match", etag)
	}
	w := httptest.NewRecorder()
	h.ServeHTTP(w, r)
	if w.Code != status {
		t.Fatalf("%s %s: got %d want %d: %s", method, path, w.Code, status, w.Body.String())
	}
	if schema != "" {
		var v any
		if e := json.Unmarshal(w.Body.Bytes(), &v); e != nil {
			t.Fatal(e)
		}
		if e := h.Validate(schema, v); e != nil {
			t.Fatalf("%s %s invalid %s: %v\n%s", method, path, schema, e, w.Body.String())
		}
	}
	return w
}
func arDecode(t *testing.T, w *httptest.ResponseRecorder) map[string]any {
	t.Helper()
	var v map[string]any
	if e := json.Unmarshal(w.Body.Bytes(), &v); e != nil {
		t.Fatal(e)
	}
	return v
}
func arCreateSession(t *testing.T, h *ARHandler) (string, string) {
	t.Helper()
	w := arHTTP(t, h, "POST", "sessions", ARCreate{OperationID: uuid.NewString(), Title: "test", Alias: "controlled"}, "", "Conversation", 201)
	v := arDecode(t, w)
	return v["id"].(string), w.Header().Get("ETag")
}
func arInput(mode string) ARRunCreate {
	l := arPolicy()
	tools := []ARToolRef{}
	if mode == "chat" {
		l.Calls = 1
		l.Tools = 0
	} else {
		tools = []ARToolRef{{Name: "bounded_arithmetic", Revision: "1"}, {Name: "list_visible_models", Revision: "1"}}
	}
	text := "calculate"
	return ARRunCreate{OperationID: uuid.NewString(), Mode: mode, Operation: "send", Text: &text, Alias: "controlled", Limits: l, Tools: tools}
}
func arSubmit(t *testing.T, h *ARHandler, sid, etag string, in ARRunCreate) string {
	w := arHTTP(t, h, "POST", "sessions/"+sid+"/runs", in, etag, "RunAccepted", 202)
	return arDecode(t, w)["run"].(map[string]any)["id"].(string)
}

func TestAR1CreationACKRecoveryIsolationAndDeletion(t *testing.T) {
	h, m, auth := setupAR(t, arPlain, nil)
	in := ARCreate{OperationID: uuid.NewString(), Title: "original", Alias: "controlled"}
	w := arHTTP(t, h, "POST", "sessions", in, "", "Conversation", 201)
	sid := arDecode(t, w)["id"].(string)
	etag := w.Header().Get("ETag")
	// Simulate lost POST ACK: recovery only uses original operation ID and GET.
	lookup := "session-creation-commands/" + in.OperationID
	got := arDecode(t, arHTTP(t, h, "GET", lookup, nil, "", "SessionCreationCommand", 200))
	if got["session_id"] != sid {
		t.Fatal(got)
	}
	got = arDecode(t, arHTTP(t, h, "POST", "sessions", in, "", "Conversation", 200))
	if got["id"] != sid {
		t.Fatal(got)
	}
	in.Title = "conflict"
	arHTTP(t, h, "POST", "sessions", in, "", "Error", 409)
	arHTTP(t, h, "GET", "session-creation-commands/"+uuid.NewString(), nil, "", "Error", 404)
	auth.mu.Lock()
	auth.p.ID = uuid.NewString()
	auth.mu.Unlock()
	arHTTP(t, h, "GET", lookup, nil, "", "Error", 404)
	auth.mu.Lock()
	auth.p = arActor
	auth.mu.Unlock()
	arHTTP(t, h, "DELETE", "sessions/"+sid, nil, etag, "", 204)
	arHTTP(t, h, "GET", lookup, nil, "", "SessionCreationCommand", 200)
	arHTTP(t, h, "GET", "sessions/"+sid, nil, "", "Error", 404)
	in.Title = "original"
	arHTTP(t, h, "POST", "sessions", in, "", "Error", 409)
	if m.calls.Load() != 0 {
		t.Fatal("read/create executed model")
	}
	all, _ := h.Service.Store.List(context.Background(), arActor.ID)
	if len(all) > 0 {
		t.Fatal("deleted row exposed")
	}
}
func TestAR1LiveHTTPAgentEventsSchemaUTF8AndReadOnlyReplay(t *testing.T) {
	h, model, _ := setupAR(t, func(ctx context.Context, r Request, emit func(string) error) (Response, error) {
		for _, m := range r.Messages {
			if m.Role == "tool" && m.Parts[0].Name == "list_visible_models" {
				return arPlain(ctx, r, emit)
			}
		}
		return Response{RequestID: r.RequestID, TerminalConfirmed: true, Finish: "tool_calls", Usage: arUsage(), Calls: []Call{{ID: "provider-1", Name: "bounded_arithmetic", Arguments: json.RawMessage(`{"a":6,"b":7,"op":"multiply"}`)}, {ID: "provider-2", Name: "list_visible_models", Arguments: json.RawMessage(`{}`)}}}, nil
	}, nil)
	arHTTP(t, h, "GET", "capabilities", nil, "", "Capabilities", 200)
	sid, etag := arCreateSession(t, h)
	in := arInput("agent")
	rid := arSubmit(t, h, sid, etag, in)
	// The same command matches before stale If-Match; changed body conflicts.
	if again := arSubmit(t, h, sid, etag, in); again != rid {
		t.Fatal("duplicate run")
	}
	bad := in
	text := "changed"
	bad.Text = &text
	arHTTP(t, h, "POST", "sessions/"+sid+"/runs", bad, etag, "Error", 409)
	if e := h.Service.Drive(context.Background(), arActor, sid, rid); e != nil {
		t.Fatal(e)
	}
	base := "sessions/" + sid + "/runs/" + rid
	runBody := arDecode(t, arHTTP(t, h, "GET", base, nil, "", "Run", 200))
	if runBody["state"] != "completed" || runBody["aggregation_complete"] != true || len(runBody["child_request_ids"].([]any)) != 2 {
		t.Fatal(runBody)
	}
	for _, endpoint := range []struct{ path, schema string }{{"steps", "StepPage"}, {"tool-calls", "ToolCallPage"}, {"checkpoint", "Checkpoint"}} {
		arHTTP(t, h, "GET", base+"/"+endpoint.path, nil, "", endpoint.schema, 200)
	}
	arHTTP(t, h, "GET", "sessions/"+sid, nil, "", "Snapshot", 200)
	arHTTP(t, h, "GET", "sessions/"+sid+"/commands/"+in.OperationID, nil, "", "Command", 200)
	events := arDecode(t, arHTTP(t, h, "GET", base+"/events?page_size=100", nil, "", "EventPage", 200))["data"].([]any)
	created := map[string]bool{}
	offsets := map[string]int{}
	last := ""
	seq := 0
	for _, item := range events {
		ev := item.(map[string]any)
		seq++
		if ev["seq"] != fmt.Sprint(seq) {
			t.Fatal(ev)
		}
		if e := h.Validate("SessionEvent", ev); e != nil {
			t.Fatal(e)
		}
		last = ev["cursor"].(string)
		data := ev["data"].(map[string]any)
		switch ev["type"] {
		case "message.created":
			created[data["id"].(string)] = true
		case "message.delta":
			id := data["message_id"].(string)
			if !created[id] || data["offset"] != fmt.Sprint(offsets[id]) {
				t.Fatal(ev)
			}
			offsets[id] += len(data["text"].(string))
		}
	}
	if last != runBody["resume_cursor"] {
		t.Fatal("snapshot watermark mismatch")
	}
	replay := arHTTP(t, h, "GET", base+"/events?page_size=100", nil, "", "EventPage", 200)
	if len(arDecode(t, replay)["data"].([]any)) != len(events) {
		t.Fatal("replay changed")
	}
	stream := arHTTP(t, h, "GET", base+"/events/stream", nil, "", "", 200).Body.String()
	for _, item := range events {
		ev := item.(map[string]any)
		if !strings.Contains(stream, "id: "+ev["cursor"].(string)+"\nevent: "+ev["type"].(string)) {
			t.Fatal("SSE envelope mismatch")
		}
	}
	arHTTP(t, h, "GET", base+"/events?after="+last, nil, "", "EventPage", 200)
	arHTTP(t, h, "GET", base+"/events?after=1", nil, "", "Error", 400)
	r := httptest.NewRequest("GET", "/api/agent/v1/"+base+"/events/stream?after="+last, nil)
	r.Header.Set("Last-Event-ID", last)
	w := httptest.NewRecorder()
	h.ServeHTTP(w, r)
	if w.Code != 400 {
		t.Fatal(w.Code)
	}
	page := arDecode(t, arHTTP(t, h, "GET", base+"/events?page_size=2", nil, "", "EventPage", 200))
	arHTTP(t, h, "GET", base+"/events?after="+page["next_cursor"].(string), nil, "", "EventPage", 200)
	if model.calls.Load() != 2 {
		t.Fatal("GET replay executed model", model.calls.Load())
	}
	if os.Getenv("MAAS_AR_EVIDENCE") != "" {
		b, _ := json.MarshalIndent(map[string]any{"run": runBody, "events": events}, "", "  ")
		if e := os.WriteFile(os.Getenv("MAAS_AR_EVIDENCE"), b, 0600); e != nil {
			t.Fatal(e)
		}
	}
}
func TestAR1LimitsAndCapabilityRejectionsPrecedeDispatch(t *testing.T) {
	h, m, _ := setupAR(t, arPlain, nil)
	sid, etag := arCreateSession(t, h)
	for _, test := range []struct {
		name   string
		change func(*ARRunCreate)
		status int
	}{{"wire10001", func(v *ARRunCreate) { v.Limits.Calls = 10001 }, 400}, {"policy", func(v *ARRunCreate) { v.Limits.Calls = 5 }, 422}, {"chat2", func(v *ARRunCreate) { v.Mode = "chat"; v.Tools = []ARToolRef{}; v.Limits.Calls = 2 }, 400}, {"unknownTool", func(v *ARRunCreate) { v.Tools = []ARToolRef{{Name: "shell", Revision: "1"}} }, 422}, {"unknownModel", func(v *ARRunCreate) { v.Alias = "unapproved" }, 422}} {
		t.Run(test.name, func(t *testing.T) {
			in := arInput("agent")
			test.change(&in)
			arHTTP(t, h, "POST", "sessions/"+sid+"/runs", in, etag, "Error", test.status)
		})
	}
	if m.calls.Load() != 0 {
		t.Fatal(m.calls.Load())
	}
	doc, _ := h.Service.Get(context.Background(), arActor, sid)
	if len(doc.Runs) != 0 {
		t.Fatal("rejection persisted run")
	}
	// Exact capacity is accepted only under an explicit matching installation cap.
	h.Service.Limits.Calls = 10000
	h.Policy.Calls = 10000
	in := arInput("agent")
	in.Limits.Calls = 10000
	rid := arSubmit(t, h, sid, etag, in)
	body := arDecode(t, arHTTP(t, h, "GET", "sessions/"+sid+"/runs/"+rid, nil, "", "Run", 200))
	if body["limits"].(map[string]any)["max_model_calls"] != float64(10000) {
		t.Fatal(body)
	}
	// Synthetic retained-record capacity only: no 10,000 model calls are made.
	_, e := h.Service.mutate(context.Background(), arActor, sid, func(v *Session) error {
		r := run(v, rid)
		for len(r.Steps) < 10000 {
			r.Steps = append(r.Steps, Step{ID: uuid.NewString(), Number: len(r.Steps) + 1, RequestID: uuid.NewString(), State: "unknown", InputHash: strings.Repeat("a", 64)})
		}
		return nil
	})
	if e != nil {
		t.Fatal(e)
	}
	body = arDecode(t, arHTTP(t, h, "GET", "sessions/"+sid+"/runs/"+rid, nil, "", "Run", 200))
	if len(body["child_request_ids"].([]any)) != 10000 {
		t.Fatal("truncated children")
	}
	_, e = h.Service.mutate(context.Background(), arActor, sid, func(v *Session) error {
		r := run(v, rid)
		r.Steps = append(r.Steps, Step{RequestID: uuid.NewString()})
		return nil
	})
	if e != nil {
		t.Fatal(e)
	}
	arHTTP(t, h, "GET", "sessions/"+sid+"/runs/"+rid, nil, "", "Error", 503)
}
func TestAR1ApprovalDecisionIdempotencyAndUnknownWrite(t *testing.T) {
	tool := controlledTool(true)
	tool.f = func(context.Context) (string, error) { return "", errors.New("lost response") }
	h, model, _ := setupAR(t, toolResponse, nil, tool)
	sid, etag := arCreateSession(t, h)
	in := arInput("agent")
	in.Tools = []ARToolRef{{Name: tool.Spec().Name, Revision: "1"}}
	rid := arSubmit(t, h, sid, etag, in)
	if e := h.Service.Drive(context.Background(), arActor, sid, rid); e != nil {
		t.Fatal(e)
	}
	v, _ := h.Service.Get(context.Background(), arActor, sid)
	r := run(&v, rid)
	if r.Status != "waiting_approval" {
		t.Fatal(r.Status, r.Reason)
	}
	call := r.Steps[0].Calls[0]
	base := "sessions/" + sid + "/runs/" + rid + "/approvals/" + call.ApprovalID
	arHTTP(t, h, "GET", base, nil, "", "Approval", 200)
	d := ARDecision{ID: uuid.NewString(), Decision: "allow", ArgsHash: call.ArgsHash, ToolRevision: "1", PolicyRevision: arActor.Revision}
	bad := d
	bad.ArgsHash = strings.Repeat("0", 64)
	arHTTP(t, h, "POST", base+"/decision", bad, "", "Error", 409)
	arHTTP(t, h, "POST", base+"/decision", d, "", "Approval", 200)
	arHTTP(t, h, "POST", base+"/decision", d, "", "Approval", 200)
	bad = d
	bad.ID = uuid.NewString()
	arHTTP(t, h, "POST", base+"/decision", bad, "", "Error", 409)
	if e := h.Service.Drive(context.Background(), arActor, sid, rid); e != nil {
		t.Fatal(e)
	}
	v, _ = h.Service.Get(context.Background(), arActor, sid)
	if run(&v, rid).Status != "needs_confirmation" || tool.calls.Load() != 1 || model.calls.Load() != 1 {
		t.Fatal(v.Runs)
	}
	arHTTP(t, h, "GET", "sessions/"+sid+"/runs/"+rid+"/events?page_size=100", nil, "", "EventPage", 200)
}
