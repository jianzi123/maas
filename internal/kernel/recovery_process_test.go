package kernel

import (
	"bytes"
	"context"
	"database/sql"
	"encoding/json"
	"errors"
	"github.com/go-sql-driver/mysql"
	"github.com/google/uuid"
	"github.com/jianzi123/maas/internal/release/mysqlstore"
	"net"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func TestMySQLManagedACKRecovery(t *testing.T) {
	f := setup(t, 1)
	ctx := context.Background()
	connector, _ := mysql.NewConnector(f.config)
	fault := &ackConnector{Connector: connector}
	db := sql.OpenDB(fault)
	defer db.Close()
	core, _ := New(db, "controlled-test", f.core.pepper, f.rate, f.proofs)
	policy := Policy{Window: "utc_day", Revision: "explicit", Limits: Limits{Requests: ptr("10")}}
	fault.lose.Store(true)
	id, raw, e := core.CreateManagedKey(ctx, "ack-unknown", policy)
	if !errors.Is(e, ErrCommitUnknown) || raw != "" {
		t.Fatal("secret cannot be recovered/replayed", e)
	}
	meta, e := core.KeyView(ctx, id)
	if e != nil {
		t.Fatal(e)
	}
	revision := meta["budget_policy"].(Policy).Revision
	fault.lose.Store(true)
	if e = core.PatchKey(ctx, id, revision, Limits{Requests: ptr("0")}); !errors.Is(e, ErrCommitUnknown) {
		t.Fatal(e)
	}
	if e = core.PatchKey(ctx, id, revision, Limits{Requests: ptr("0")}); !errors.Is(e, ErrConflict) {
		t.Fatal("stale retry", e)
	}
	fault.lose.Store(true)
	if e = core.Revoke(ctx, id); !errors.Is(e, ErrCommitUnknown) {
		t.Fatal(e)
	}
	meta, e = core.KeyView(ctx, id)
	if e != nil || meta["state"] != "revoked" {
		t.Fatal(meta, e)
	}
}
func TestMySQLRedisActualRestart(t *testing.T) {
	base := os.Getenv("MAAS_TEST_REDIS_BASEDIR")
	if base == "" {
		t.Skip("portable Redis required")
	}
	f := setup(t, 2)
	ctx := context.Background()
	dir := t.TempDir()
	socket := filepath.Join(dir, "redis.sock")
	binary := filepath.Join(base, "usr/bin/redis-server")
	var process *exec.Cmd
	stop := func() {
		if process != nil {
			_ = process.Process.Signal(os.Interrupt)
			_ = process.Wait()
			process = nil
		}
	}
	start := func() {
		t.Helper()
		_ = os.Remove(socket)
		process = exec.Command(binary, "--port", "0", "--unixsocket", socket, "--save", "", "--appendonly", "no", "--daemonize", "no", "--dir", dir)
		if e := process.Start(); e != nil {
			t.Fatal(e)
		}
		until := time.Now().Add(5 * time.Second)
		for time.Now().Before(until) {
			c, e := net.DialTimeout("unix", socket, 50*time.Millisecond)
			if e == nil {
				c.Close()
				return
			}
			time.Sleep(10 * time.Millisecond)
		}
		t.Fatal("owned Redis not ready")
	}
	defer stop()
	start()
	r := &RedisGate{Network: "unix", Address: socket, Prefix: f.config.DBName, Timeout: 2 * time.Second}
	f.core.rate = r
	epoch, e := f.core.BlockRate(ctx)
	if e != nil {
		t.Fatal(e)
	}
	if e = f.core.RebuildRate(ctx, r, epoch); e != nil {
		t.Fatal(e)
	}
	old, _ := f.core.readRate(ctx)
	mustAdmit(t, f, f.input(t))
	stop()
	start()
	if _, e = f.core.Admit(ctx, f.gate, f.input(t)); e == nil {
		t.Fatal("restarted Redis admitted without rebuild")
	}
	epoch, e = f.core.BlockRate(ctx)
	if e != nil {
		t.Fatal(e)
	}
	if e = f.core.RebuildRate(ctx, r, epoch); e != nil {
		t.Fatal(e)
	}
	current, _ := f.core.readRate(ctx)
	if current.RedisIdentity == old.RedisIdentity {
		t.Fatal("instance identity unchanged")
	}
	mustAdmit(t, f, f.input(t))
	assertSQL(t, f.db, "SELECT COUNT(*) FROM generation_requests", 2)
}
func TestOwnerCrashChild(t *testing.T) {
	if os.Getenv("MAAS_OWNER_CRASH_CHILD") != "1" {
		t.Skip("internal subprocess entry")
	}
	socket := os.Getenv("MAAS_MYSQL_TEST_SOCKET")
	if os.Getenv("MAAS_DISPOSABLE_MYSQL") != "1" || !strings.HasPrefix(socket, "/tmp/maas11-mysql.") {
		t.Fatal("disposable server required")
	}
	var in Input
	if json.NewDecoder(os.Stdin).Decode(&in) != nil {
		os.Exit(21)
	}
	cfg := mysql.NewConfig()
	cfg.User = "root"
	cfg.Net = "unix"
	cfg.Addr = socket
	cfg.DBName = os.Getenv("MAAS_CHILD_SCHEMA")
	cfg.ParseTime = true
	cfg.Loc = time.UTC
	cfg.Timeout = time.Second
	cfg.ReadTimeout = 3 * time.Second
	cfg.WriteTimeout = 3 * time.Second
	db, _ := sql.Open("mysql", cfg.FormatDSN())
	core, _ := New(db, "controlled-test", []byte(strings.Repeat("x", 32)), &fixtureRate{}, &fixtureProofs{})
	gate, _ := mysqlstore.New(db, "controlled-test", core)
	if _, e := core.Admit(context.Background(), gate, in); e != nil {
		os.Exit(22)
	}
	os.Exit(23) // abrupt owner exit AFTER durable admission; no terminal cleanup.
}
func TestMySQLOwnerProcessRecovery(t *testing.T) {
	f := setup(t, 1)
	in := f.input(t)
	in.Expires = time.Now().UTC().Add(1500 * time.Millisecond)
	in.Deadline = in.Expires.Add(500 * time.Millisecond)
	b, _ := json.Marshal(in)
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	cmd := exec.CommandContext(ctx, os.Args[0], "-test.run=^TestOwnerCrashChild$")
	cmd.Env = append(os.Environ(), "MAAS_OWNER_CRASH_CHILD=1", "MAAS_CHILD_SCHEMA="+f.config.DBName)
	cmd.Stdin = bytes.NewReader(b)
	e := cmd.Run()
	var exit *exec.ExitError
	if !errors.As(e, &exit) || exit.ExitCode() != 23 {
		t.Fatal("owner did not exit after commit", e)
	}
	assertSQL(t, f.db, "SELECT COUNT(*) FROM generation_requests WHERE result='in_progress'", 1)
	time.Sleep(time.Until(in.Deadline.Add(20 * time.Millisecond)))
	restarted, _ := New(f.db, "controlled-test", f.core.pepper, f.rate, f.proofs)
	if e = restarted.Recover(context.Background(), in.RequestID, uuid.NewString()); e != nil {
		t.Fatal(e)
	}
	assertSQL(t, f.db, "SELECT COUNT(*) FROM generation_requests WHERE result='interrupted'", 1)
	if c := readCounter(t, f, "tokens"); c.Held != "140" || c.Reserved != "0" {
		t.Fatal(c)
	}
}
