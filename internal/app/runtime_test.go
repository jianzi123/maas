package app

import (
	"bytes"
	"context"
	"database/sql"
	"encoding/json"
	"io"
	"net/http"
	"net/http/cookiejar"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"sync/atomic"
	"testing"
	"time"

	"github.com/go-sql-driver/mysql"
	"github.com/google/uuid"
	a "github.com/jianzi123/maas/internal/agentruntime"
	"github.com/jianzi123/maas/internal/kernel"
)

type testModel struct{ calls atomic.Int32 }

func (m *testModel) Supports(context.Context, a.Model) error { return nil }
func (m *testModel) Generate(_ context.Context, r a.Request, emit func(string) error) (a.Response, error) {
	m.calls.Add(1)
	if e := emit("持久历史🙂"); e != nil {
		return a.Response{}, e
	}
	return a.Response{RequestID: r.RequestID, Finish: "stop", TerminalConfirmed: true, Usage: a.Usage{Currency: "USD"}}, nil
}

type testCatalogue struct{}

func (testCatalogue) Resolve(_ context.Context, _ a.Principal, alias, mode string) (a.Model, error) {
	return a.Model{Alias: alias, Source: "controlled-test-only", Revision: "1", Protocol: "text-v1"}, nil
}
func (testCatalogue) Modes(context.Context, a.Principal) ([]map[string]any, error) {
	return []map[string]any{}, nil
}

func productFixture(t *testing.T) (Config, *sql.DB) {
	t.Helper()
	socket := os.Getenv("MAAS_MYSQL_TEST_SOCKET")
	if socket == "" {
		t.Skip("real disposable MySQL required")
	}
	if os.Getenv("MAAS_DISPOSABLE_MYSQL") != "1" || !strings.HasPrefix(socket, "/tmp/maas11-mysql.") {
		t.Fatal("refusing non-disposable database")
	}
	ctx := context.Background()
	raw, e := os.ReadFile("../../config/product.example.json")
	if e != nil {
		t.Fatal(e)
	}
	var c Config
	if e = json.Unmarshal(raw, &c); e != nil {
		t.Fatal(e)
	}
	driver := mysql.NewConfig()
	driver.User = "root"
	driver.Net = "unix"
	driver.Addr = socket
	driver.ParseTime = true
	admin, e := sql.Open("mysql", driver.FormatDSN())
	if e != nil {
		t.Fatal(e)
	}
	name := "product_" + strings.ReplaceAll(uuid.NewString(), "-", "")
	if _, e = admin.ExecContext(ctx, "CREATE DATABASE "+name); e != nil {
		t.Fatal(e)
	}
	t.Cleanup(func() { admin.Exec("DROP DATABASE " + name); admin.Close() })
	driver.DBName = name
	dir := t.TempDir()
	write := func(name, value string) string {
		file := filepath.Join(dir, name)
		if e := os.WriteFile(file, []byte(value), 0600); e != nil {
			t.Fatal(e)
		}
		return file
	}
	c.MySQL.RuntimeDSNFile = write("runtime-dsn", driver.FormatDSN())
	c.MySQL.MigrationDSNFile = write("migration-dsn", driver.FormatDSN())
	c.Auth.PasswordFile = write("bootstrap-password", "test-only-password-12345")
	c.Secrets.PepperFile = write("pepper", strings.Repeat("p", 32))
	c.Secrets.CursorKeyFile = write("cursor", strings.Repeat("c", 32))
	c.ContractFile, e = filepath.Abs("../../docs/contracts/agent-runtime/ar1-draft2/openapi.json")
	if e != nil {
		t.Fatal(e)
	}
	c.StaticDir = dir
	c.Cluster = "product-test"
	c.Models = []ModelConfig{}
	db, e := sql.Open("mysql", driver.FormatDSN())
	if e != nil {
		t.Fatal(e)
	}
	t.Cleanup(func() { db.Close() })
	return c, db
}
func TestProductMySQLSharedLoginRestartAndNoReplay(t *testing.T) {
	c, db := productFixture(t)
	ctx := context.Background()
	if e := Migrate(ctx, c); e != nil {
		t.Fatal(e)
	}
	if e := Migrate(ctx, c); e != nil {
		t.Fatal("idempotent migration", e)
	}
	server := httptest.NewUnstartedServer(nil)
	c.Origin = "http://" + server.Listener.Addr().String()
	r, e := Open(ctx, c)
	if e != nil {
		t.Fatal(e)
	}
	t.Cleanup(r.Close)
	var currentHandler atomic.Value
	currentHandler.Store(r.Handler)
	server.Config.Handler = http.HandlerFunc(func(w http.ResponseWriter, q *http.Request) { currentHandler.Load().(http.Handler).ServeHTTP(w, q) })
	server.Start()
	t.Cleanup(server.Close)
	if _, ok := r.Service.Store.(a.MySQLStore); !ok {
		t.Fatal("normal service did not use MySQL")
	}
	jar, _ := cookiejar.New(nil)
	client := &http.Client{Jar: jar, Timeout: 5 * time.Second}
	csrf := ""
	do := func(method, path string, body any, etag string) (int, []byte, http.Header) {
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
		return res.StatusCode, raw, res.Header
	}
	if status, _, _ := do("GET", "/healthz", nil, ""); status != 200 {
		t.Fatal(status)
	}
	if status, _, _ := do("GET", "/api/admin/v1/session", nil, ""); status == 200 {
		t.Fatal("anonymous session")
	}
	status, raw, _ := do("POST", "/api/admin/v1/session", map[string]string{"username": "admin", "password": "test-only-password-12345"}, "")
	if status != 200 {
		t.Fatal("login failed", status)
	}
	var session struct {
		CSRF string `json:"csrf_token"`
	}
	if json.Unmarshal(raw, &session) != nil {
		t.Fatal("bad login response")
	}
	csrf = session.CSRF
	if status, _, _ := do("GET", "/api/agent/v1/capabilities", nil, ""); status != 200 {
		t.Fatal("shared AR session", status)
	}
	if status, _, _ := do("GET", "/api/admin/v1/keys", nil, ""); status != 200 {
		t.Fatal("shared admin session", status)
	}
	// This injection is test-only. The normal binary cannot select these fakes.
	m := &testModel{}
	r.Agent.Catalog = testCatalogue{}
	r.Service.Model = m
	r.Service.CountContext = func(context.Context, a.Request) (int64, error) { return 1, nil }
	status, raw, headers := do("POST", "/api/agent/v1/sessions", a.ARCreate{OperationID: uuid.NewString(), Title: "MySQL", Alias: "test-only"}, "")
	if status != 201 {
		t.Fatal("create", status, string(raw))
	}
	var conversation map[string]any
	json.Unmarshal(raw, &conversation)
	sid := conversation["id"].(string)
	etag := headers.Get("ETag")
	text := "hello"
	limits := c.Agent.Limits
	limits.Calls = 1
	limits.Tools = 0
	in := a.ARRunCreate{OperationID: uuid.NewString(), Mode: "chat", Operation: "send", Text: &text, Alias: "test-only", Limits: limits, Tools: []a.ARToolRef{}}
	status, raw, _ = do("POST", "/api/agent/v1/sessions/"+sid+"/runs", in, etag)
	if status != 202 {
		t.Fatal("run", status, string(raw))
	}
	var accepted map[string]any
	json.Unmarshal(raw, &accepted)
	rid := accepted["run"].(map[string]any)["id"].(string)
	deadline := time.Now().Add(3 * time.Second)
	for {
		status, raw, _ = do("GET", "/api/agent/v1/sessions/"+sid+"/runs/"+rid, nil, "")
		var run map[string]any
		json.Unmarshal(raw, &run)
		if status == 200 && run["state"] == "completed" {
			break
		}
		if time.Now().After(deadline) {
			t.Fatal("run not complete", status, string(raw))
		}
		time.Sleep(5 * time.Millisecond)
	}
	status, before, _ := do("GET", "/api/agent/v1/sessions/"+sid+"/runs/"+rid+"/events", nil, "")
	if status != 200 {
		t.Fatal(status)
	}
	requests := "10"
	if _, _, e = r.Core.CreateManagedKey(ctx, "retained", kernel.Policy{Window: "utc_day", Revision: "test-v1", Limits: kernel.Limits{Requests: &requests}}); e != nil {
		t.Fatal(e)
	}
	r.Close()
	if e = Migrate(ctx, c); e != nil {
		t.Fatal(e)
	}
	reopened, e := Open(ctx, c)
	if e != nil {
		t.Fatal(e)
	}
	t.Cleanup(reopened.Close)
	currentHandler.Store(reopened.Handler)
	status, _, _ = do("GET", "/api/admin/v1/session", nil, "")
	if status != 200 {
		t.Fatal("login did not survive restart", status)
	}
	status, after, _ := do("GET", "/api/agent/v1/sessions/"+sid+"/runs/"+rid+"/events", nil, "")
	if status != 200 || !bytes.Equal(before, after) {
		t.Fatal("event replay changed after restart", status)
	}
	if m.calls.Load() != 1 {
		t.Fatal("restart replayed model")
	}
	var count int
	if e = db.QueryRow("SELECT COUNT(*) FROM platform_keys").Scan(&count); e != nil || count != 1 {
		t.Fatal("migration reset or recreated key", count, e)
	}
	if status, _, _ = do("DELETE", "/api/admin/v1/session", nil, ""); status != 204 {
		t.Fatal(status)
	}
}

func TestProductServeRequiresMigratedMySQL(t *testing.T) {
	c, _ := productFixture(t)
	if r, e := Open(context.Background(), c); e == nil {
		r.Close()
		t.Fatal("unmigrated serve started")
	}
	if e := os.WriteFile(c.MySQL.RuntimeDSNFile, []byte("sqlite::memory:"), 0600); e != nil {
		t.Fatal(e)
	}
	if _, e := openDB(context.Background(), c.MySQL.RuntimeDSNFile); e == nil {
		t.Fatal("non-MySQL accepted")
	}
}
