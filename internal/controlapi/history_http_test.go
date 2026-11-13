package controlapi

import (
	"context"
	"crypto/sha256"
	"database/sql"
	"encoding/hex"
	"encoding/json"
	"github.com/go-sql-driver/mysql"
	"github.com/google/uuid"
	api "github.com/jianzi123/maas/api/v1alpha1"
	"github.com/jianzi123/maas/internal/kernel"
	"github.com/jianzi123/maas/internal/release"
	"github.com/jianzi123/maas/internal/release/history"
	"github.com/jianzi123/maas/internal/release/mysqlstore"
	"net/http"
	"net/http/httptest"
	"os"
	"sigs.k8s.io/yaml"
	"strings"
	"testing"
	"time"
)

func TestMySQLHistoryHTTP(t *testing.T) {
	socket := os.Getenv("MAAS_MYSQL_TEST_SOCKET")
	if socket == "" {
		t.Skip("disposable MySQL required")
	}
	if os.Getenv("MAAS_DISPOSABLE_MYSQL") != "1" || !strings.HasPrefix(socket, "/tmp/maas11-mysql.") {
		t.Fatal("refuse existing database")
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
	admin, _ := sql.Open("mysql", cfg.FormatDSN())
	defer admin.Close()
	name := "maas_history_http_" + strings.ReplaceAll(uuid.NewString(), "-", "")
	if _, e := admin.Exec("CREATE DATABASE `" + name + "`"); e != nil {
		t.Fatal(e)
	}
	defer admin.Exec("DROP DATABASE `" + name + "`")
	cfg.DBName = name
	db, _ := sql.Open("mysql", cfg.FormatDSN())
	defer db.Close()
	ctx := context.Background()
	if e := kernel.Migrate(ctx, db); e != nil {
		t.Fatal(e)
	}
	if e := mysqlstore.Migrate(ctx, db); e != nil {
		t.Fatal(e)
	}
	core, _ := kernel.New(db, "api-history", []byte(strings.Repeat("x", 32)), nil, nil)
	if e := core.Configure(ctx, kernel.RatePolicy{Revision: "test", Epoch: 1, WindowMS: 1000, GlobalLimit: 100, KeyLimit: 100}, 1); e != nil {
		t.Fatal(e)
	}
	b, e := os.ReadFile("../../config/samples/MAAS-2-modelrelease-externalapi-v0.4.example.yaml")
	if e != nil {
		t.Fatal(e)
	}
	var m api.ModelRelease
	_ = yaml.Unmarshal(b, &m)
	uid := uuid.NewString()
	resolution := release.Resolution{Versions: map[string]string{"authorization_domain": "old-domain"}, CredentialHandle: "not-for-public"}
	desired := release.Desired{CRUID: uid, Namespace: m.Namespace, Name: m.Name, Alias: m.Spec.ModelAlias, Gateway: m.Spec.GatewayRef, Generation: 1, Revision: release.Revision(m.Spec, resolution), History: &release.HistoryCapture{Spec: m.Spec, Resolution: resolution, ResourceVersion: "1", AuthorizationDomain: "old-domain"}}
	publisher, _ := mysqlstore.New(db, "api-history", core)
	if _, e = publisher.Observe(ctx, desired); e != nil {
		t.Fatal(e)
	}
	token := uuid.NewString() + uuid.NewString()
	sum := sha256.Sum256([]byte(token))
	h := Handler{Core: core, Sessions: BootstrapSession{SessionSHA256: hex.EncodeToString(sum[:]), Expires: time.Now().Add(time.Minute)}, Revisions: &history.Reader{DB: db, Cluster: "api-history", CursorKey: []byte(strings.Repeat("k", 32)), Access: history.NamespaceAccess{Namespaces: map[string]bool{m.Namespace: true}, Domains: map[string]bool{"old-domain": true}, ScopeID: "session"}}}
	server := httptest.NewServer(h)
	defer server.Close()
	path := server.URL + "/api/admin/v1/model-releases/" + m.Namespace + "/" + m.Name + "/revisions?cr_uid=" + uid
	call := func(url string) (int, map[string]any) {
		r, _ := http.NewRequest("GET", url, nil)
		r.AddCookie(&http.Cookie{Name: "maas_session", Value: token})
		response, e := server.Client().Do(r)
		if e != nil {
			t.Fatal(e)
		}
		defer response.Body.Close()
		var v map[string]any
		_ = json.NewDecoder(response.Body).Decode(&v)
		return response.StatusCode, v
	}
	status, value := call(path)
	if status != 200 || value["requested_cr_uid"] != uid || value["resource_state"] != "unknown" {
		t.Fatal(status, value)
	}
	if len(value["data"].([]any)) != 1 {
		t.Fatal(value)
	}
	row := value["data"].([]any)[0].(map[string]any)
	if row["rollback_eligibility"].(map[string]any)["state"] != "unknown" {
		t.Fatal("manufactured eligible", value)
	}
	status, _ = call(path + "&page_size=0")
	if status != 400 {
		t.Fatal(status)
	}
	status, _ = call(strings.Replace(path, uid, uuid.NewString(), 1))
	if status != 404 {
		t.Fatal(status)
	}
	if _, e = db.Exec("UPDATE retained_release_snapshots SET summary_sha256=REPEAT('0',64)"); e != nil {
		t.Fatal(e)
	}
	status, _ = call(path)
	if status != 503 {
		t.Fatal("corrupt history reported success", status)
	}
}
