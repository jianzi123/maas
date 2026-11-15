package publisher

import (
	"context"
	"database/sql"
	"errors"
	"io"
	"log"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/go-sql-driver/mysql"
	"github.com/google/uuid"
	api "github.com/jianzi123/maas/api/v1alpha1"
	"github.com/jianzi123/maas/internal/kernel"
	"github.com/jianzi123/maas/internal/release"
	"github.com/jianzi123/maas/internal/release/mysqlstore"
)

// All identities/data below are created in an owned, network-disabled temporary
// server. The new runtime uses the real store/core read port, never proof fixtures.
func TestPublisherMySQLService(t *testing.T) {
	socket := os.Getenv("MAAS_MYSQL_TEST_SOCKET")
	if socket == "" {
		t.Skip("owned temporary MySQL not supplied")
	}
	if os.Getenv("MAAS_DISPOSABLE_MYSQL") != "1" || !strings.HasPrefix(socket, "/tmp/maas11-mysql.") {
		t.Fatal("owned temporary socket required")
	}
	ctx := context.Background()
	cfg := mysql.NewConfig()
	cfg.User = "root"
	cfg.Net = "unix"
	cfg.Addr = socket
	cfg.ParseTime = true
	cfg.Loc = time.UTC
	cfg.Timeout = time.Second * 3
	cfg.ReadTimeout = time.Second * 5
	cfg.WriteTimeout = time.Second * 5
	cfg.Params = map[string]string{"time_zone": "'+00:00'"}
	admin, e := sql.Open("mysql", cfg.FormatDSN())
	if e != nil {
		t.Fatal(e)
	}
	defer admin.Close()
	name := "publisher_test_" + strings.ReplaceAll(uuid.NewString(), "-", "")
	if _, e = admin.Exec("CREATE DATABASE `" + name + "`"); e != nil {
		t.Fatal(e)
	}
	defer admin.Exec("DROP DATABASE `" + name + "`")
	cfg.DBName = name
	db, e := sql.Open("mysql", cfg.FormatDSN())
	if e != nil {
		t.Fatal(e)
	}
	defer db.Close()
	if e = kernel.Migrate(ctx, db); e != nil {
		t.Fatal(e)
	}
	if e = mysqlstore.Migrate(ctx, db); e != nil {
		t.Fatal(e)
	}
	core, e := kernel.New(db, "publisher-local", []byte(strings.Repeat("x", 32)), nil, nil)
	if e != nil {
		t.Fatal(e)
	}
	if e = core.Configure(ctx, kernel.RatePolicy{Revision: "owned-test-only", Epoch: 1, WindowMS: 1000, GlobalLimit: 1, KeyLimit: 1}, 1); e != nil {
		t.Fatal(e)
	}
	// Apply only the original publisher grants in this disposable server.
	for _, file := range []string{"release-permissions.sql", "kernel-permissions.sql"} {
		b, e := os.ReadFile("../../config/mysql/" + file)
		if e != nil {
			t.Fatal(e)
		}
		var lines []string
		for _, l := range strings.Split(string(b), "\n") {
			if !strings.HasPrefix(strings.TrimSpace(l), "--") {
				lines = append(lines, l)
			}
		}
		for _, q := range strings.Split(strings.Join(lines, "\n"), ";") {
			if !strings.Contains(q, "maas_release_publisher") {
				continue
			}
			q = strings.ReplaceAll(q, "__MAAS_DATABASE__", "`"+name+"`")
			if _, e = db.Exec(q); e != nil {
				t.Fatal(e)
			}
		}
	}
	defer db.Exec("DROP ROLE maas_release_publisher")
	user := "pub_" + strings.ReplaceAll(uuid.NewString(), "-", "")[:16]
	if _, e = db.Exec("CREATE USER '" + user + "'@'localhost'"); e != nil {
		t.Fatal(e)
	}
	defer db.Exec("DROP USER '" + user + "'@'localhost'")
	for _, q := range []string{"GRANT maas_release_publisher TO '" + user + "'@'localhost'", "SET DEFAULT ROLE maas_release_publisher TO '" + user + "'@'localhost'"} {
		if _, e = db.Exec(q); e != nil {
			t.Fatal(e)
		}
	}
	cfg.User = user
	secret := filepath.Join(t.TempDir(), "publisher.dsn")
	if e = os.WriteFile(secret, []byte(cfg.FormatDSN()), 0600); e != nil {
		t.Fatal(e)
	}
	c := Config{Cluster: "publisher-local", DSNFile: secret}
	runtime, e := c.Open(ctx)
	if e != nil {
		t.Fatal(e)
	}
	defer runtime.Close()
	state, e := runtime.Store.Observe(ctx, release.Desired{CRUID: uuid.NewString(), Namespace: "controlled", Name: "model", Alias: "model", Gateway: api.Ref{Name: "higress"}, Generation: 1, Revision: strings.Repeat("a", 64)})
	if e != nil || state.Candidate == nil || !state.AdmissionClosed {
		t.Fatal(state, e)
	}
	t.Log("real independent publisher connection/default role; Observe persisted a closed candidate")
	serverTLS, clientTLS, _ := certificates(t)
	server := httptest.NewUnstartedServer(Handler{Control: runtime.Store, OperatorIdentity: operatorID})
	server.TLS = serverTLS
	server.Config.ErrorLog = log.New(io.Discard, "", 0)
	server.StartTLS()
	defer server.Close()
	caller, e := release.NewCommandClient(server.URL, clientTLS)
	if e != nil {
		t.Fatal(e)
	}
	target := state.Candidate.PublicationID
	activate := release.Command{ID: uuid.NewString(), Action: "Activate", CRUID: state.CRUID, Generation: state.Generation, Fence: state.Fence, Revision: state.Revision, Target: &target, EvidenceRefs: []string{}}
	if e = caller.Send(ctx, activate); e == nil {
		t.Fatal("missing real producers activated release")
	}
	var n int
	if e = db.QueryRow("SELECT COUNT(*) FROM release_operations WHERE command_id=?", activate.ID).Scan(&n); e != nil || n != 0 {
		t.Fatal("rejected activation committed", e)
	}
	t.Log("real mTLS -> factory -> same-transaction kernel read port -> missing evidence rejects activation without audit/active mutation")
	close := activate
	close.ID = uuid.NewString()
	close.Action = "CloseAdmission"
	close.Target = nil
	if e = caller.Send(ctx, close); e != nil {
		t.Fatal(e)
	}
	if e = caller.Send(ctx, close); e != nil {
		t.Fatal(e)
	}
	if e = db.QueryRow("SELECT COUNT(*) FROM release_operations WHERE command_id=?", close.ID).Scan(&n); e != nil || n != 1 {
		t.Fatal("command replay duplicated durable operation", e)
	}
	conflicting := close
	conflicting.Fence++
	if e = caller.Send(ctx, conflicting); !errors.Is(e, release.ErrConflict) {
		t.Fatal("same ID conflicting payload accepted", e)
	}
	t.Log("CloseAdmission via real command client committed once; same-ID replay confirms durable result; changed hash conflicts")
	for _, q := range []string{"UPDATE platform_keys SET revoked=FALSE", "UPDATE budget_windows SET uncertainty_held=0", "DELETE FROM usage_events", "UPDATE release_management_operations SET action='Delete'", "CREATE TABLE forbidden_publisher(id INT)"} {
		_, e = runtime.DB.Exec(q)
		var denied *mysql.MySQLError
		if !errors.As(e, &denied) || (denied.Number != 1142 && denied.Number != 1143) {
			t.Fatal("least-privilege denial missing", e)
		}
		t.Log("runtime forbidden SQL denied", denied.Number)
	}
	if _, e = db.Exec("REVOKE UPDATE(state) ON `" + name + "`.release_management_operations FROM maas_release_publisher"); e != nil {
		t.Fatal(e)
	}
	denied := close
	denied.ID = uuid.NewString()
	if e = caller.Send(ctx, denied); e == nil {
		t.Fatal("completion hook bypassed")
	}
	if e = db.QueryRow("SELECT COUNT(*) FROM release_operations WHERE command_id=?", denied.ID).Scan(&n); e != nil || n != 0 {
		t.Fatal("permission failure left half commit", e)
	}
	if _, e = db.Exec("GRANT UPDATE(state) ON `" + name + "`.release_management_operations TO maas_release_publisher"); e != nil {
		t.Fatal(e)
	}
	if e = caller.Send(ctx, denied); e != nil {
		t.Fatal("original failed command not recoverable", e)
	}
	// Same process restart, same identity and durable result; never replay generation.
	if e = runtime.Close(); e != nil {
		t.Fatal(e)
	}
	restarted, e := c.Open(ctx)
	if e != nil {
		t.Fatal(e)
	}
	defer restarted.Close()
	if e = restarted.Store.Apply(ctx, close); e != nil {
		t.Fatal("restart lost command identity", e)
	}
	if e = db.QueryRow("SELECT COUNT(*) FROM release_operations WHERE command_id=?", close.ID).Scan(&n); e != nil || n != 1 {
		t.Fatal(n, e)
	}
	for _, table := range []string{"generation_requests", "usage_events", "budget_windows"} {
		if e = db.QueryRow("SELECT COUNT(*) FROM " + table).Scan(&n); e != nil || n != 0 {
			t.Fatal("publisher touched business ledger", table, e)
		}
	}
	t.Log("completion permission failure rolls back; reopen recovers original command; business ledgers remain untouched")
	transport := &http.Transport{TLSClientConfig: clientTLS}
	defer transport.CloseIdleConnections()
	checkPublisherProcess(t, c, transport, serverTLS.Certificates[0].Certificate, serverTLS.Certificates[0].PrivateKey, close)
}
