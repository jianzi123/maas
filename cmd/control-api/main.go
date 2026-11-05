// The controlled management API has no inference listener or production proof
// adapter. It does not migrate/configure a database or provision any cluster.
package main

import (
	"context"
	"database/sql"
	"fmt"
	_ "github.com/go-sql-driver/mysql"
	"github.com/jianzi123/maas/internal/controlapi"
	"github.com/jianzi123/maas/internal/kernel"
	"net"
	"net/http"
	"os"
	"os/signal"
	"strings"
	"syscall"
	"time"
)

func run() error {
	address := os.Getenv("MAAS_CONTROL_LISTEN")
	host, _, e := net.SplitHostPort(address)
	if e != nil || (host != "127.0.0.1" && host != "::1") {
		return fmt.Errorf("explicit loopback listen address required")
	}
	expires, e := time.Parse(time.RFC3339, os.Getenv("MAAS_ADMIN_EXPIRES"))
	if e != nil || !time.Now().Before(expires) {
		return fmt.Errorf("explicit bootstrap session expiry required")
	}
	if len(os.Getenv("MAAS_ADMIN_SESSION_SHA256")) != 64 || len(os.Getenv("MAAS_ADMIN_CSRF_SHA256")) != 64 || !strings.HasPrefix(os.Getenv("MAAS_ADMIN_ORIGIN"), "http") {
		return fmt.Errorf("session digests and approved origin required")
	}
	db, e := sql.Open("mysql", os.Getenv("MAAS_MYSQL_DSN"))
	if e != nil {
		return fmt.Errorf("database configuration unavailable")
	}
	defer db.Close()
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	if db.PingContext(ctx) != nil {
		return fmt.Errorf("primary unavailable")
	}
	core, e := kernel.New(db, os.Getenv("MAAS_CLUSTER_ID"), []byte(os.Getenv("MAAS_KEY_PEPPER")), nil, nil)
	if e != nil {
		return e
	}
	h := controlapi.Handler{Core: core, Sessions: controlapi.BootstrapSession{SessionSHA256: os.Getenv("MAAS_ADMIN_SESSION_SHA256"), CSRFSHA256: os.Getenv("MAAS_ADMIN_CSRF_SHA256"), Origin: os.Getenv("MAAS_ADMIN_ORIGIN"), Expires: expires}}
	server := &http.Server{Addr: address, Handler: h, ReadHeaderTimeout: 5 * time.Second, ReadTimeout: 10 * time.Second, WriteTimeout: 15 * time.Second, IdleTimeout: 30 * time.Second}
	signals, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	done := make(chan struct{})
	go func() {
		select {
		case <-signals.Done():
			ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
			defer cancel()
			_ = server.Shutdown(ctx)
		case <-done:
		}
	}()
	defer close(done)
	e = server.ListenAndServe()
	if e == http.ErrServerClosed {
		return nil
	}
	return fmt.Errorf("control API stopped")
}
func main() {
	if e := run(); e != nil {
		fmt.Fprintln(os.Stderr, e)
		os.Exit(1)
	}
}
