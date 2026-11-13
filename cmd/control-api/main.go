// The controlled management API has no inference listener or production proof
// adapter. It does not migrate/configure a database or provision any cluster.
package main

import (
	"bytes"
	"context"
	"database/sql"
	"encoding/json"
	"fmt"
	_ "github.com/go-sql-driver/mysql"
	api "github.com/jianzi123/maas/api/v1alpha1"
	"github.com/jianzi123/maas/internal/controlapi"
	"github.com/jianzi123/maas/internal/kernel"
	"github.com/jianzi123/maas/internal/protocol"
	"github.com/jianzi123/maas/internal/release/history"
	"github.com/jianzi123/maas/internal/release/management"
	"github.com/jianzi123/maas/internal/release/mysqlstore"
	"k8s.io/apimachinery/pkg/runtime"
	"k8s.io/client-go/tools/clientcmd"
	"net"
	"net/http"
	"os"
	"os/signal"
	"sigs.k8s.io/controller-runtime/pkg/client"
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
	// Projection readers never implicitly inherit the core runtime identity.
	openReader := func(variable string) (*sql.DB, error) {
		return openProjectionDB(os.Getenv(variable))
	}
	historyDB, e := openReader("MAAS_HISTORY_READER_DSN")
	if e != nil {
		return e
	}
	if historyDB != nil {
		defer historyDB.Close()
	}
	operationsDB, e := openReader("MAAS_OPERATIONS_DSN")
	if e != nil {
		return e
	}
	if operationsDB != nil {
		defer operationsDB.Close()
	}
	h := controlapi.Handler{Core: core, Sessions: controlapi.BootstrapSession{SessionSHA256: os.Getenv("MAAS_ADMIN_SESSION_SHA256"), CSRFSHA256: os.Getenv("MAAS_ADMIN_CSRF_SHA256"), Origin: os.Getenv("MAAS_ADMIN_ORIGIN"), Expires: expires}}
	if namespaces := os.Getenv("MAAS_HISTORY_NAMESPACES"); namespaces != "" {
		scope := os.Getenv("MAAS_HISTORY_SCOPE")
		domains := os.Getenv("MAAS_HISTORY_DOMAINS")
		key := []byte(os.Getenv("MAAS_HISTORY_CURSOR_KEY"))
		if scope == "" || domains == "" || len(key) < 32 {
			return fmt.Errorf("explicit original-domain visibility and cursor key required")
		}
		allowed := map[string]bool{}
		for _, n := range strings.Split(namespaces, ",") {
			allowed[n] = true
		}
		owned := map[string]bool{}
		for _, n := range strings.Split(domains, ",") {
			owned[n] = true
		}
		hr := &history.Reader{DB: historyDB, Cluster: os.Getenv("MAAS_CLUSTER_ID"), Access: history.NamespaceAccess{Namespaces: allowed, Domains: owned, ScopeID: scope}, CursorKey: key}
		access := history.NamespaceAccess{Namespaces: allowed, Domains: owned, ScopeID: scope}
		var kube client.Client
		if configPath := os.Getenv("MAAS_HISTORY_KUBECONFIG"); configPath != "" {
			cfg, err := clientcmd.BuildConfigFromFlags("", configPath)
			if err != nil {
				return fmt.Errorf("history API reader unavailable")
			}
			scheme := runtime.NewScheme()
			_ = api.AddToScheme(scheme)
			reader, err := client.New(cfg, client.Options{Scheme: scheme})
			if err != nil {
				return fmt.Errorf("history API reader unavailable")
			}
			hr.Live = history.KubeLive{Reader: reader}
			kube = reader
		}
		if os.Getenv("MAAS_RELEASE_MANAGEMENT") == "1" {
			if operationsDB == nil {
				return fmt.Errorf("explicit management operation connection required")
			}
			if kube == nil {
				return fmt.Errorf("explicit management KUBECONFIG required")
			}
			registry := &management.Registry{Access: access}
			if path := os.Getenv("MAAS_RELEASE_REGISTRY_FILE"); path != "" {
				b, err := os.ReadFile(path)
				if err != nil || len(b) > 1048576 {
					return fmt.Errorf("approved release registry unavailable")
				}
				b, err = protocol.Canonical(b)
				if err != nil {
					return fmt.Errorf("invalid approved release registry")
				}
				decoder := json.NewDecoder(bytes.NewReader(b))
				decoder.DisallowUnknownFields()
				if decoder.Decode(registry) != nil || len(registry.Entries) == 0 || len(registry.Entries) > 256 {
					return fmt.Errorf("invalid approved release registry")
				}
				registry.Access = access
				for _, entry := range registry.Entries {
					if api.Validate(entry.Spec, nil) != nil || !allowed[entry.Namespace] || !owned[entry.Resolution.Versions["authorization_domain"]] {
						return fmt.Errorf("unapproved release registry scope")
					}
				}
			}
			if dsn := os.Getenv("MAAS_HISTORY_PAYLOAD_DSN"); dsn != "" {
				payload, err := sql.Open("mysql", dsn)
				if err != nil {
					return fmt.Errorf("history payload reader unavailable")
				}
				defer payload.Close()
				hr.PayloadDB = payload
				hr.Evaluator = history.ResolverEvaluator{Resolver: registry, Loader: hr}
			}
			op := &management.Operations{DB: operationsDB, Cluster: os.Getenv("MAAS_CLUSTER_ID"), Access: access}
			h.Releases = &management.Service{Client: kube, Reader: kube, Operations: op, History: hr, Resolver: registry, Access: access, CursorKey: key}
			publisher, err := mysqlstore.New(db, os.Getenv("MAAS_CLUSTER_ID"), core)
			if err != nil {
				return err
			}
			h.Models = core
			h.ModelGate = publisher
			h.ModelNamespaces = allowed
		}
		// No approved reference registry is implicitly manufactured: eligibility stays
		// unknown until an installation supplies ResolverEvaluator through the port.
		h.Revisions = hr
	}
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
