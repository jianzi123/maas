package agentruntime

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
	"github.com/jianzi123/maas/internal/workbench"
)

type workbenchARAuth struct{ session *workbench.LocalSession }

func (a workbenchARAuth) Authenticate(r *http.Request, write bool) (Principal, error) {
	if e := a.session.Authorize(r, write); e != nil {
		return Principal{}, e
	}
	return arActor, nil
}

// Real loopback HTTP, existing session/CSRF middleware, managed Host and durable
// core. Model is controlled; tools are real. No provider/target environment.
func TestAR1LoopbackCookieCSRFAndLiveSSE(t *testing.T) {
	h, model, _ := setupAR(t, arPlain, nil)
	host, e := NewHost(context.Background(), h.Service, 1, h.Service.Reauthorize)
	if e != nil {
		t.Fatal(e)
	}
	defer host.Close()
	h.Dispatch = host.Schedule
	server := httptest.NewUnstartedServer(nil)
	origin := "http://" + server.Listener.Addr().String()
	session := workbench.NewLocalSession(origin)
	h.Auth = workbenchARAuth{session}
	server.Config.Handler = workbench.Handler(h, session, t.TempDir(), nil)
	server.Start()
	defer server.Close()
	jar, _ := cookiejar.New(nil)
	client := &http.Client{Jar: jar, Timeout: 5 * time.Second}
	do := func(method, path string, body any, csrf, etag string) (*http.Response, []byte) {
		t.Helper()
		b, _ := json.Marshal(body)
		req, _ := http.NewRequest(method, origin+path, bytes.NewReader(b))
		req.Header.Set("Origin", origin)
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
		_ = res.Body.Close()
		if e != nil {
			t.Fatal(e)
		}
		return res, raw
	}
	res, _ := do("GET", "/api/agent/v1/capabilities", nil, "", "")
	if res.StatusCode != 401 {
		t.Fatal("anonymous access", res.StatusCode)
	}
	res, raw := do("POST", "/__maas/local-session", nil, "", "")
	if res.StatusCode != 200 {
		t.Fatal(res.StatusCode)
	}
	var bootstrap struct {
		CSRF string `json:"csrf_token"`
	}
	if json.Unmarshal(raw, &bootstrap) != nil || bootstrap.CSRF == "" {
		t.Fatal("session bootstrap failed")
	}
	create := ARCreate{OperationID: uuid.NewString(), Title: "HTTP", Alias: "controlled"}
	res, _ = do("POST", "/api/agent/v1/sessions", create, "wrong", "")
	if res.StatusCode != 403 {
		t.Fatal("CSRF bypass", res.StatusCode)
	}
	res, raw = do("POST", "/api/agent/v1/sessions", create, bootstrap.CSRF, "")
	if res.StatusCode != 201 {
		t.Fatal(res.StatusCode, string(raw))
	}
	var conversation map[string]any
	_ = json.Unmarshal(raw, &conversation)
	sid := conversation["id"].(string)
	etag := res.Header.Get("ETag")
	res, raw = do("POST", "/api/agent/v1/sessions/"+sid+"/runs", arInput("chat"), bootstrap.CSRF, etag)
	if res.StatusCode != 202 {
		t.Fatal(res.StatusCode, string(raw))
	}
	var accepted map[string]any
	_ = json.Unmarshal(raw, &accepted)
	rid := accepted["run"].(map[string]any)["id"].(string)
	res, raw = do("GET", "/api/agent/v1/sessions/"+sid+"/runs/"+rid+"/events/stream", nil, "", "")
	if res.StatusCode != 200 || !strings.Contains(string(raw), "event: run.completed") || !strings.Contains(string(raw), "你") {
		t.Fatal(res.StatusCode, string(raw))
	}
	if model.calls.Load() != 1 {
		t.Fatal(model.calls.Load())
	}
	res, raw = do("GET", "/api/agent/v1/sessions/"+sid, nil, "", "")
	var snapshot any
	if res.StatusCode != 200 || json.Unmarshal(raw, &snapshot) != nil || h.Validate("Snapshot", snapshot) != nil {
		t.Fatal("snapshot invalid")
	}
	res, _ = do("DELETE", "/__maas/local-session", nil, "", "")
	if res.StatusCode != 204 {
		t.Fatal(res.StatusCode)
	}
	res, _ = do("GET", "/api/agent/v1/sessions/"+sid, nil, "", "")
	if res.StatusCode != 401 {
		t.Fatal("revoked session visible", res.StatusCode)
	}
}
