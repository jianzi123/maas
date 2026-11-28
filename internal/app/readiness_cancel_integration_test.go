package app

import (
	"bytes"
	"context"
	"database/sql"
	"errors"
	"net"
	"os"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"github.com/go-sql-driver/mysql"
	"github.com/google/uuid"
)

// Delay only the actual lease-check reply, after its command reached the owned
// MySQL. Caller cancellation must not close the scheduler's lock connection.
type readinessDelayedConn struct {
	net.Conn
	entered        chan struct{}
	release        <-chan struct{}
	closed         chan struct{}
	wait           atomic.Bool
	isLease        atomic.Bool
	once           *sync.Once
	closeOnce      sync.Once
	leaseClosed    chan struct{}
	leaseCloseOnce *sync.Once
}

func (c *readinessDelayedConn) Write(p []byte) (int, error) {
	n, err := c.Conn.Write(p)
	if err == nil && bytes.Contains(p, []byte("GET_LOCK")) {
		c.isLease.Store(true)
	}
	if err == nil && bytes.Contains(p, []byte("IS_USED_LOCK")) {
		c.wait.Store(true)
		c.once.Do(func() { close(c.entered) })
	}
	return n, err
}
func (c *readinessDelayedConn) Read(p []byte) (int, error) {
	if c.wait.Swap(false) {
		select {
		case <-c.release:
		case <-c.closed:
			return 0, net.ErrClosed
		}
	}
	return c.Conn.Read(p)
}
func (c *readinessDelayedConn) Close() error {
	c.closeOnce.Do(func() { close(c.closed) })
	if c.isLease.Load() {
		c.leaseCloseOnce.Do(func() { close(c.leaseClosed) })
	}
	return c.Conn.Close()
}

func TestReadinessInFlightCallerCancellationPreservesLease(t *testing.T) {
	cfg, db := productFixture(t)
	if err := Migrate(context.Background(), cfg); err != nil {
		t.Fatal(err)
	}
	raw, err := os.ReadFile(cfg.MySQL.RuntimeDSNFile)
	if err != nil {
		t.Fatal(err)
	}
	dsn, err := mysql.ParseDSN(string(raw))
	if err != nil {
		t.Fatal("owned fixture DSN invalid")
	}
	socket := dsn.Addr
	entered, release, closed := make(chan struct{}), make(chan struct{}), make(chan struct{})
	var releaseOnce, leaseCloseOnce, enteredOnce sync.Once
	unblock := func() { releaseOnce.Do(func() { close(release) }) }
	defer unblock()
	name := "owned-ready-" + uuid.NewString()
	mysql.RegisterDialContext(name, func(ctx context.Context, _ string) (net.Conn, error) {
		conn, err := (&net.Dialer{}).DialContext(ctx, "unix", socket)
		if err != nil {
			return nil, err
		}
		return &readinessDelayedConn{Conn: conn, once: &enteredOnce, entered: entered, release: release, closed: make(chan struct{}), leaseClosed: closed, leaseCloseOnce: &leaseCloseOnce}, nil
	})
	defer mysql.DeregisterDialContext(name)
	dsn.Net = name
	leaseDB, err := sql.Open("mysql", dsn.FormatDSN())
	if err != nil {
		t.Fatal(err)
	}
	defer leaseDB.Close()
	lease, err := leaseDB.Conn(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	defer lease.Close()
	var own int
	if err = lease.QueryRowContext(context.Background(), "SELECT GET_LOCK(CONCAT('maas-product-runtime:',DATABASE()),0)").Scan(&own); err != nil || own != 1 {
		t.Fatal("fixture did not own scheduler lease", err)
	}
	var leaseID int64
	if err = lease.QueryRowContext(context.Background(), "SELECT CONNECTION_ID()").Scan(&leaseID); err != nil {
		t.Fatal(err)
	}
	root, stop := context.WithCancel(context.Background())
	defer stop()
	// Match Open's real saved identity. Both pool and lease use the delayed
	// transport; only closing the actual GET_LOCK connection is a failure.
	runtime := &Runtime{DB: leaseDB, lease: lease, leaseID: leaseID, ctx: root, cancel: stop}
	caller, cancel := context.WithCancel(root)
	defer cancel()
	done := make(chan error, 1)
	go func() { done <- runtime.checkReady(caller) }()
	select {
	case <-entered:
	case <-time.After(5 * time.Second):
		unblock()
		t.Fatal("actual lease check was not reached")
	}
	cancel()
	select {
	case err = <-done:
	case <-time.After(500 * time.Millisecond):
		unblock()
		select {
		case err = <-done:
		case <-time.After(5 * time.Second):
			t.Fatal("lease check exceeded bound")
		}
	}
	unblock()
	if err != nil && !errors.Is(err, context.Canceled) {
		t.Fatal("caller cancellation became a service failure", err)
	}
	select {
	case <-closed:
		t.Fatal("caller cancellation closed the physical scheduler lease")
	default:
	}
	if root.Err() != nil {
		t.Fatal("caller cancellation retired the healthy runtime")
	}
	var owner sql.NullInt64
	if err = db.QueryRow("SELECT IS_USED_LOCK(CONCAT('maas-product-runtime:',DATABASE()))").Scan(&owner); err != nil || !owner.Valid || owner.Int64 != leaseID {
		t.Fatal("caller cancellation released scheduler ownership", err)
	}
	if _, err = lease.ExecContext(context.Background(), "SELECT RELEASE_LOCK(CONCAT('maas-product-runtime:',DATABASE()))"); err != nil {
		t.Fatal("original lease connection is not usable", err)
	}
	other, err := db.Conn(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	defer other.Close()
	if err = other.QueryRowContext(context.Background(), "SELECT GET_LOCK(CONCAT('maas-product-runtime:',DATABASE()),0)").Scan(&own); err != nil || own != 1 {
		t.Fatal("different-owner control failed to acquire lease", err)
	}
	defer other.ExecContext(context.Background(), "SELECT RELEASE_LOCK(CONCAT('maas-product-runtime:',DATABASE()))")
	if err = runtime.checkReady(context.Background()); err == nil || root.Err() == nil {
		t.Fatal("different scheduler owner did not retire the runtime", err)
	}
}
