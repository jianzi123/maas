package app

import (
	"bytes"
	"context"
	"encoding/json"
	"io"
	"net/http"
	"net/http/cookiejar"
	"net/http/httptest"
	"sync/atomic"
	"testing"
	"time"

	"github.com/google/uuid"
	a "github.com/jianzi123/maas/internal/agentruntime"
)

func TestProductOfflineSameEntryToolsApprovalLedgerAndRestart(t *testing.T) {
	c, db := productFixture(t)
	c.Offline = OfflineConfig{Enabled: true, RequireApproval: true, StepDelayMS: 20}
	c.Ledger.WindowMS = 3600000
	c.Ledger.GlobalLimit = 1000
	c.Ledger.KeyLimit = 1000
	if e := Migrate(context.Background(), c); e != nil {
		t.Fatal("offline migrate", e)
	}
	if e := Migrate(context.Background(), c); e != nil {
		t.Fatal("offline repeat", e)
	}
	server := httptest.NewUnstartedServer(nil)
	c.Origin = "http://" + server.Listener.Addr().String()
	r, e := Open(context.Background(), c)
	if e != nil {
		t.Fatal("offline open", e)
	}
	t.Cleanup(r.Close)
	var active atomic.Value
	active.Store(r.Handler)
	server.Config.Handler = http.HandlerFunc(func(w http.ResponseWriter, q *http.Request) { active.Load().(http.Handler).ServeHTTP(w, q) })
	server.Start()
	t.Cleanup(server.Close)
	jar, _ := cookiejar.New(nil)
	client := &http.Client{Jar: jar, Timeout: 10 * time.Second}
	csrf := ""
	do := func(method, path string, body any, etag string, status int) (map[string]any, http.Header) {
		t.Helper()
		b, _ := json.Marshal(body)
		req, _ := http.NewRequest(method, server.URL+path, bytes.NewReader(b))
		req.Header.Set("Origin", c.Origin)
		req.Header.Set("Content-Type", "application/json")
		if csrf != "" {
			req.Header.Set("X-CSRF-Token", csrf)
		}
		if etag != "" {
			req.Header.Set("If-Match", etag)
		}
		res, e := client.Do(req)
		if e != nil {
			t.Fatal(e)
		}
		raw, e := io.ReadAll(res.Body)
		res.Body.Close()
		if e != nil {
			t.Fatal(e)
		}
		if res.StatusCode != status {
			t.Fatalf("%s %s status=%d want=%d body=%s", method, path, res.StatusCode, status, raw)
		}
		var v map[string]any
		if len(raw) > 0 {
			if e = json.Unmarshal(raw, &v); e != nil {
				t.Fatal(e)
			}
		}
		return v, res.Header
	}
	login, _ := do("POST", "/api/admin/v1/session", map[string]string{"username": "admin", "password": "test-only-password-12345"}, "", 200)
	csrf = login["csrf_token"].(string)
	caps, _ := do("GET", "/api/agent/v1/capabilities", nil, "", 200)
	mode := caps["model_modes"].([]any)[0].(map[string]any)
	if mode["approval_state"] != "controlled" || mode["tools_protocol"] != "tools-v1" {
		t.Fatal(caps)
	}
	created, header := do("POST", "/api/agent/v1/sessions", a.ARCreate{OperationID: uuid.NewString(), Title: "offline SQL", Alias: OfflineAlias}, "", 201)
	sid := created["id"].(string)
	text := "计算6乘7，读取可见模型"
	in := a.ARRunCreate{OperationID: uuid.NewString(), Mode: "agent", Operation: "send", Text: &text, Alias: OfflineAlias, Limits: c.Agent.Limits, Tools: []a.ARToolRef{{Name: "bounded_arithmetic", Revision: "1"}, {Name: "list_visible_models", Revision: "1"}}}
	accepted, _ := do("POST", "/api/agent/v1/sessions/"+sid+"/runs", in, header.Get("ETag"), 202)
	rid := accepted["run"].(map[string]any)["id"].(string)
	base := "/api/agent/v1/sessions/" + sid + "/runs/" + rid
	deadline := time.Now().Add(10 * time.Second)
	for {
		state, _ := do("GET", base, nil, "", 200)
		if state["state"] == "waiting_approval" {
			break
		}
		if state["state"] == "failed" || state["state"] == "needs_confirmation" {
			t.Fatal(state)
		}
		if time.Now().After(deadline) {
			t.Fatal("approval never reached", state)
		}
		time.Sleep(10 * time.Millisecond)
	}
	page, _ := do("GET", base+"/events?page_size=100", nil, "", 200)
	var approval map[string]any
	for _, raw := range page["data"].([]any) {
		event := raw.(map[string]any)
		if event["type"] == "approval.required" {
			approval = event["data"].(map[string]any)
		}
	}
	if approval == nil {
		t.Fatal("approval event missing")
	}
	decision := a.ARDecision{ID: uuid.NewString(), Decision: "allow", ArgsHash: approval["args_sha256"].(string), ToolRevision: approval["tool_revision"].(string), PolicyRevision: approval["policy_revision"].(string)}
	do("POST", base+"/approvals/"+approval["id"].(string)+"/decision", decision, "", 200)
	for {
		state, _ := do("GET", base, nil, "", 200)
		if state["state"] == "completed" {
			if state["aggregation_complete"] != true {
				t.Fatal("accounting incomplete", state)
			}
			groups := state["usage_groups"].([]any)
			if len(groups) != 1 || groups[0].(map[string]any)["known_tokens"] != "20" {
				t.Fatal(state)
			}
			break
		}
		if state["state"] == "failed" || state["state"] == "needs_confirmation" {
			t.Fatal(state)
		}
		if time.Now().After(deadline) {
			t.Fatal("run not complete", state)
		}
		time.Sleep(10 * time.Millisecond)
	}
	tools, _ := do("GET", base+"/tool-calls", nil, "", 200)
	if len(tools["data"].([]any)) != 2 {
		t.Fatal(tools)
	}
	before, _ := do("GET", base+"/events?page_size=100", nil, "", 200)
	encodedBefore, _ := json.Marshal(before)
	var requests, usage int
	db.QueryRow("SELECT COUNT(*) FROM generation_requests").Scan(&requests)
	db.QueryRow("SELECT COUNT(*) FROM usage_events").Scan(&usage)
	if requests != 2 || usage != 2 {
		t.Fatal("not original unique child ledger", requests, usage)
	}
	r.Close()
	fresh, e := Open(context.Background(), c)
	if e != nil {
		t.Fatal(e)
	}
	t.Cleanup(fresh.Close)
	active.Store(fresh.Handler)
	do("GET", "/api/admin/v1/session", nil, "", 200)
	after, _ := do("GET", base+"/events?page_size=100", nil, "", 200)
	encodedAfter, _ := json.Marshal(after)
	if !bytes.Equal(encodedBefore, encodedAfter) {
		t.Fatal("restart replay changed")
	}
	db.QueryRow("SELECT COUNT(*) FROM generation_requests").Scan(&requests)
	db.QueryRow("SELECT COUNT(*) FROM usage_events").Scan(&usage)
	if requests != 2 || usage != 2 {
		t.Fatal("restart repeated ledger", requests, usage)
	}
	// Stop a genuinely admitted synthetic child through the same public API.
	fresh.models.(*OfflineModel).Config.Offline.StepDelayMS = 250
	_, latest := do("GET", "/api/agent/v1/sessions/"+sid, nil, "", 200)
	chat := in
	chat.OperationID = uuid.NewString()
	chat.Mode = "chat"
	chat.Tools = []a.ARToolRef{}
	chat.Limits.Calls = 1
	chat.Limits.Tools = 0
	started, _ := do("POST", "/api/agent/v1/sessions/"+sid+"/runs", chat, latest.Get("ETag"), 202)
	stopID := started["run"].(map[string]any)["id"].(string)
	stopBase := "/api/agent/v1/sessions/" + sid + "/runs/" + stopID
	deadline = time.Now().Add(5 * time.Second)
	for {
		var running int
		db.QueryRow("SELECT COUNT(*) FROM generation_requests WHERE result='in_progress'").Scan(&running)
		if running == 1 {
			break
		}
		if time.Now().After(deadline) {
			t.Fatal("stop child not admitted")
		}
		time.Sleep(5 * time.Millisecond)
	}
	do("POST", stopBase+"/cancel", nil, "", 202)
	for {
		state, _ := do("GET", stopBase, nil, "", 200)
		if state["state"] == "cancelled" {
			break
		}
		if state["state"] == "failed" || state["state"] == "needs_confirmation" {
			t.Fatal(state)
		}
		if time.Now().After(deadline) {
			t.Fatal("cancel not complete", state)
		}
		time.Sleep(5 * time.Millisecond)
	}
	db.QueryRow("SELECT COUNT(*) FROM generation_requests").Scan(&requests)
	db.QueryRow("SELECT COUNT(*) FROM usage_events").Scan(&usage)
	if requests != 3 || usage != 3 {
		t.Fatal("stop duplicated or lost terminal", requests, usage)
	}
	t.Logf("REAL MYSQL OFFLINE: original children=%d, unique terminals=%d; real tools=2; approved=1; restart/replay added 0", requests, usage)
}

func TestProductOfflineDefaultDisabledAndNoMixedSources(t *testing.T) {
	c, _ := productFixture(t)
	if c.Offline.Enabled {
		t.Fatal("demo default enabled")
	}
	c.Offline.Enabled = true
	c.Models = []ModelConfig{{Alias: "real"}}
	if c.Validate() == nil {
		t.Fatal("mixed real/demo source accepted")
	}
}
