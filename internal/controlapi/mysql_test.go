package controlapi

import (
	"bytes"
	"context"
	"crypto/sha256"
	"database/sql"
	"encoding/hex"
	"encoding/json"
	"github.com/go-sql-driver/mysql"
	"github.com/google/uuid"
	"github.com/jianzi123/maas/internal/kernel"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"strings"
	"testing"
	"time"
)

func TestMySQLSessionAPI(t *testing.T) {
	socket := os.Getenv("MAAS_MYSQL_TEST_SOCKET")
	if socket == "" {
		t.Skip("disposable MySQL required")
	}
	if os.Getenv("MAAS_DISPOSABLE_MYSQL") != "1" || !strings.HasPrefix(socket, "/tmp/maas11-mysql.") {
		t.Fatal("refuse non-disposable DB")
	}
	cfg := mysql.NewConfig()
	cfg.User = "root"
	cfg.Net = "unix"
	cfg.Addr = socket
	cfg.ParseTime = true
	cfg.Loc = time.UTC
	cfg.Timeout = 2 * time.Second
	cfg.ReadTimeout = 5 * time.Second
	cfg.WriteTimeout = 5 * time.Second
	admin, e := sql.Open("mysql", cfg.FormatDSN())
	if e != nil {
		t.Fatal(e)
	}
	defer admin.Close()
	name := "maas_api_test_" + strings.ReplaceAll(uuid.NewString(), "-", "")
	if _, e = admin.Exec("CREATE DATABASE `" + name + "`"); e != nil {
		t.Fatal(e)
	}
	defer admin.Exec("DROP DATABASE `" + name + "`")
	cfg.DBName = name
	db, _ := sql.Open("mysql", cfg.FormatDSN())
	defer db.Close()
	ctx := context.Background()
	if e = kernel.Migrate(ctx, db); e != nil {
		t.Fatal(e)
	}
	core, _ := kernel.New(db, "controlled-api", []byte(strings.Repeat("p", 32)), nil, nil)
	if e = core.Configure(ctx, kernel.RatePolicy{Revision: "test-rate-v1", Epoch: 1, WindowMS: 3600000, GlobalLimit: 100, KeyLimit: 100}, 1); e != nil {
		t.Fatal(e)
	}
	session, csrf := uuid.NewString()+uuid.NewString(), uuid.NewString()+uuid.NewString()
	digest := func(s string) string { x := sha256.Sum256([]byte(s)); return hex.EncodeToString(x[:]) }
	h := Handler{Core: core, Sessions: BootstrapSession{digest(session), digest(csrf), "https://console.test", time.Now().Add(time.Minute)}}
	server := httptest.NewServer(h)
	defer server.Close()
	call := func(method, path, body string, auth, validCSRF bool) (int, map[string]any, string) {
		t.Helper()
		r, _ := http.NewRequest(method, server.URL+path, strings.NewReader(body))
		r.Header.Set("Content-Type", "application/json")
		if auth {
			r.AddCookie(&http.Cookie{Name: "maas_session", Value: session})
		}
		if method != "GET" {
			r.Header.Set("Origin", "https://console.test")
			if validCSRF {
				r.Header.Set("X-CSRF-Token", csrf)
			}
		}
		resp, e := server.Client().Do(r)
		if e != nil {
			t.Fatal(e)
		}
		defer resp.Body.Close()
		b, _ := io.ReadAll(resp.Body)
		var value map[string]any
		_ = json.Unmarshal(b, &value)
		return resp.StatusCode, value, string(b)
	}
	create := `{"name":"explicit","budget_policy":{"window_kind":"utc_day","limits":{"requests":"2","tokens":null,"money":null}}}`
	if code, _, raw := call("POST", "/api/admin/v1/keys/"+uuid.NewString()+"/revoke", "", true, true); code != 404 {
		t.Fatal("missing Key", code, raw)
	}
	if code, _, _ := call("POST", "/api/admin/v1/keys", create, false, true); code != 401 {
		t.Fatal(code)
	}
	if code, _, _ := call("POST", "/api/admin/v1/keys", create, true, false); code != 403 {
		t.Fatal(code)
	}
	if code, _, _ := call("POST", "/api/admin/v1/keys", `{"name":"implicit"}`, true, true); code != 400 {
		t.Fatal("implicit default", code)
	}
	code, created, raw := call("POST", "/api/admin/v1/keys", create, true, true)
	if code != 201 {
		t.Fatal(code, raw)
	}
	secret := created["secret"].(string)
	key := created["key"].(map[string]any)
	id := key["id"].(string)
	revision := key["budget_policy"].(map[string]any)["revision"].(string)
	code, _, raw = call("GET", "/api/admin/v1/keys", "", true, false)
	if code != 200 || strings.Contains(raw, secret) || strings.Contains(raw, "verifier") {
		t.Fatal("metadata leak", code)
	}
	patch := `{"expected_revision":"` + revision + `","limits":{"requests":"0","tokens":null,"money":null}}`
	if code, _, raw = call("PATCH", "/api/admin/v1/keys/"+id, patch, true, true); code != 200 {
		t.Fatal(code, raw)
	}
	if code, _, _ := call("PATCH", "/api/admin/v1/keys/"+id, patch, true, true); code != 409 {
		t.Fatal("CAS", code)
	}
	if code, _, raw = call("POST", "/api/admin/v1/keys/"+id+"/revoke", "", true, true); code != 200 {
		t.Fatal(code, raw)
	}
	if _, _, e = core.Authenticate(ctx, secret); e == nil {
		t.Fatal("revocation")
	}
	if code, _, raw = call("GET", "/api/admin/v1/usage/requests?request_id="+uuid.NewString(), "", true, false); code != 200 || !strings.Contains(raw, `"resolution":"unknown"`) {
		t.Fatal(code, raw)
	}
	if code, _, _ := call("GET", "/api/admin/v1/usage/requests?request_id="+uuid.NewString()+"&page_size=20", "", true, false); code != 400 {
		t.Fatal(code)
	}
	if code, _, raw = call("GET", "/api/admin/v1/usage/summary", "", true, false); code != 200 {
		t.Fatal(code, raw)
	}
	if code, _, _ := call("GET", "/api/admin/v1/model-releases/n/m/revisions?cr_uid="+uuid.NewString(), "", true, false); code != 503 {
		t.Fatal("missing history cannot be empty success", code)
	}
	// Duplicate JSON keys cannot silently select a different budget.
	if code, _, _ := call("POST", "/api/admin/v1/keys", strings.Replace(create, `"name":"explicit"`, `"name":"a","name":"b"`, 1), true, true); code != 400 {
		t.Fatal(code)
	}
	if e = db.Close(); e != nil {
		t.Fatal(e)
	}
	if code, _, raw = call("GET", "/api/admin/v1/keys", "", true, false); code != 503 || bytes.Contains([]byte(raw), []byte(socket)) {
		t.Fatal("dependency failure", code)
	}
}
