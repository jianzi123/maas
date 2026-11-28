package app

import (
	"bytes"
	"context"
	"encoding/json"
	"io"
	"net/http"
	"net/http/cookiejar"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/google/uuid"
	a "github.com/jianzi123/maas/internal/agentruntime"
)

func TestProductARDependency503PreservesAuthAndLedger(t *testing.T) {
	c, db := productFixture(t)
	ctx := context.Background()
	if e := Migrate(ctx, c); e != nil {
		t.Fatal(e)
	}
	site := httptest.NewUnstartedServer(nil)
	c.Origin = "http://" + site.Listener.Addr().String()
	runtime, e := Open(ctx, c)
	if e != nil {
		t.Fatal(e)
	}
	defer runtime.Close()
	model := &testModel{}
	runtime.Service.Model = model
	site.Config.Handler = runtime.Handler
	site.Start()
	defer site.Close()
	jar, _ := cookiejar.New(nil)
	client := &http.Client{Jar: jar, Timeout: 5 * time.Second}
	csrf := ""
	do := func(method, path string, body any, token string, status int) (map[string]any, http.Header) {
		t.Helper()
		b, _ := json.Marshal(body)
		q, _ := http.NewRequest(method, site.URL+path, bytes.NewReader(b))
		q.Header.Set("Origin", c.Origin)
		q.Header.Set("Content-Type", "application/json")
		if token != "" {
			q.Header.Set("X-CSRF-Token", token)
		}
		response, e := client.Do(q)
		if e != nil {
			t.Fatal(e)
		}
		defer response.Body.Close()
		raw, e := io.ReadAll(response.Body)
		if e != nil {
			t.Fatal(e)
		}
		if response.StatusCode != status {
			t.Fatalf("%s %s: %d want %d: %s", method, path, response.StatusCode, status, raw)
		}
		var value map[string]any
		if e = json.Unmarshal(raw, &value); e != nil {
			t.Fatal(e)
		}
		if strings.HasPrefix(path, "/api/agent/v1/") && status >= 400 {
			if e = runtime.Agent.Validate("Error", value); e != nil {
				t.Fatal("official error schema", e)
			}
			errorValue := value["error"].(map[string]any)
			if errorValue["http_request_id"] != response.Header.Get("X-Request-ID") || errorValue["retryable"] != (method == "GET" && status == 503) {
				t.Fatal("wrong request correlation/retry policy", errorValue)
			}
			if _, e = uuid.Parse(response.Header.Get("X-Request-ID")); e != nil {
				t.Fatal(e)
			}
			if status == 503 && errorValue["code"] != "dependency_unavailable" {
				t.Fatal("dependency misclassified", errorValue)
			}
			if strings.Contains(string(raw), "usage_events") {
				t.Fatal("internal shape message leaked")
			}
		}
		return value, response.Header
	}
	do("GET", "/api/agent/v1/capabilities", nil, "", 401)
	login, _ := do("POST", "/api/admin/v1/session", map[string]string{"username": c.Auth.Username, "password": "test-only-password-12345"}, "", 200)
	csrf = login["csrf_token"].(string)
	do("GET", "/api/agent/v1/capabilities", nil, "", 200)
	command := a.ARCreate{OperationID: uuid.NewString(), Title: "must not be created", Alias: "not-configured"}
	do("POST", "/api/agent/v1/sessions", command, "wrong-csrf", 403)
	counts := func() [3]int {
		t.Helper()
		var result [3]int
		for i, table := range []string{"generation_requests", "usage_events", "agent_sessions_v1"} {
			if e := db.QueryRow("SELECT COUNT(*) FROM " + table).Scan(&result[i]); e != nil {
				t.Fatal(e)
			}
		}
		return result
	}
	before := counts()
	if _, e = db.Exec("RENAME TABLE usage_events TO obs_saved_usage_events"); e != nil {
		t.Fatal(e)
	}
	restored := false
	defer func() {
		if !restored {
			db.Exec("RENAME TABLE obs_saved_usage_events TO usage_events")
		}
	}()
	do("GET", "/api/agent/v1/capabilities", nil, "", 503)
	do("POST", "/api/agent/v1/sessions", command, csrf, 503)
	do("GET", "/api/agent/v1/sessions/"+uuid.NewString()+"/runs/"+uuid.NewString()+"/events/stream", nil, "", 503)
	if runtime.ctx.Err() == nil {
		t.Fatal("bad shape did not retire owner")
	}
	if _, e = db.Exec("RENAME TABLE obs_saved_usage_events TO usage_events"); e != nil {
		t.Fatal(e)
	}
	restored = true
	if after := counts(); after != before || model.calls.Load() != 0 {
		t.Fatal("dependency/auth failure changed business data", before, after, model.calls.Load())
	}
}
