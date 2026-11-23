package app

import (
	"context"
	"database/sql"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"os"
	"strconv"
	"strings"
	"sync"
	"time"

	a "github.com/jianzi123/maas/internal/agentruntime"
	"github.com/jianzi123/maas/internal/controlapi"
	"github.com/jianzi123/maas/internal/kernel"
	"github.com/jianzi123/maas/internal/webconsole"
)

type Runtime struct {
	closers        []io.Closer
	monitorStarted bool
	Agent          *a.ARHandler
	Handler        http.Handler
	Service        *a.Service
	Sessions       *Sessions
	DB             *sql.DB
	Core           *kernel.Store
	ctx            context.Context
	cancel         context.CancelFunc
	host           *a.Host
	lease          *sql.Conn
	closeOnce      sync.Once
	models         modelSource
	done           chan struct{}
}

type modelSource interface {
	a.ModelClient
	a.ARCatalog
	Namespaces() map[string]bool
	Visible(context.Context, a.Principal) ([]string, error)
	CountContext(context.Context, a.Request) (int64, error)
	Close()
}

// Open uses only MySQL. There is no fallback provider, DDL or local bootstrap
// bypass in serve. The controlled model is an explicit isolated profile, never
// a production failure fallback. A DB advisory lease defines the active scheduler;
// a second process fails closed instead of replaying another replica's work.
func Open(ctx context.Context, c Config) (*Runtime, error) {
	if e := c.Validate(); e != nil {
		return nil, e
	}
	db, e := openDB(ctx, c.MySQL.RuntimeDSNFile)
	if e != nil {
		return nil, e
	}
	root, cancel := context.WithCancel(ctx)
	r := &Runtime{DB: db, ctx: root, cancel: cancel, done: make(chan struct{})}
	ok := false
	defer func() {
		if !ok {
			r.Close()
		}
	}()
	if e = validateSchema(ctx, db); e != nil {
		return nil, e
	}
	var cluster string
	if e = db.QueryRowContext(ctx, "SELECT cluster_id FROM kernel_guard WHERE id=1").Scan(&cluster); e != nil || cluster != c.Cluster {
		return nil, errors.New("ledger_cluster_conflict")
	}
	lease, e := db.Conn(ctx)
	if e != nil {
		return nil, e
	}
	r.lease = lease
	var locked int
	if e = lease.QueryRowContext(ctx, "SELECT GET_LOCK(CONCAT('maas-product-runtime:',DATABASE()),0)").Scan(&locked); e != nil || locked != 1 {
		return nil, errors.New("runtime_already_owned")
	}
	pepper, e := secret(c.Secrets.PepperFile, 32, 4096)
	if e != nil {
		return nil, errors.New("key_pepper_unavailable")
	}
	cursor, e := secret(c.Secrets.CursorKeyFile, 32, 4096)
	if e != nil {
		return nil, errors.New("cursor_key_unavailable")
	}
	models, core, gate, e := openModelSource(ctx, db, c, pepper)
	if e != nil {
		return nil, e
	}
	r.Core = core
	r.models = models
	sessions := &Sessions{DB: db, Config: c.Auth, Origin: c.Origin}
	r.Sessions = sessions
	var calculator a.Tool = a.Calculator{}
	if c.Offline.Enabled && c.Offline.RequireApproval {
		calculator = approvalTool{Tool: calculator}
	}
	registry, e := a.NewRegistry(calculator, a.ModelDirectory{Read: models.Visible})
	if e != nil {
		return nil, e
	}
	tokens, e := strconv.ParseInt(c.Agent.Limits.Tokens, 10, 64)
	if e != nil {
		return nil, ErrConfig
	}
	money, e := strconv.ParseInt(c.Agent.Limits.Money, 10, 64)
	if e != nil {
		return nil, ErrConfig
	}
	l := c.Agent.Limits
	limits := a.Limits{Currency: l.Currency, Steps: l.Steps, Calls: l.Calls, Tokens: tokens, Money: money, Duration: time.Duration(l.Duration) * time.Millisecond, ToolTimeout: time.Duration(l.ToolTimeout) * time.Millisecond, ApprovalTTL: time.Duration(c.Agent.ApprovalTTLMS) * time.Millisecond, InputBytes: c.Agent.InputBytes, OutputBytes: l.OutputBytes, Events: c.Agent.Events}
	s, e := a.NewService(a.MySQLStore{DB: db}, models, registry, limits)
	if e != nil {
		return nil, e
	}
	s.Reauthorize = sessions.Reauthorize
	s.CountContext = models.CountContext
	r.Service = s
	host, e := a.NewHost(root, s, c.Agent.Concurrency, sessions.Reauthorize)
	if e != nil {
		return nil, e
	}
	r.host = host
	contract, e := os.ReadFile(c.ContractFile)
	if e != nil {
		return nil, errors.New("agent_contract_unavailable")
	}
	agent, e := a.NewARHandler(s, sessions, models, l, cursor, contract, 20*time.Second)
	if e != nil {
		return nil, e
	}
	agent.Dispatch = host.Schedule
	r.Agent = agent
	admin := controlapi.Handler{Core: core, Sessions: sessions, Models: core, ModelGate: gate, ModelNamespaces: models.Namespaces()}
	if e = r.wireManagement(ctx, c, &admin, cursor); e != nil {
		return nil, e
	}
	static := webconsole.Handler(c.StaticDir)
	r.Handler = http.HandlerFunc(func(w http.ResponseWriter, q *http.Request) {
		w.Header().Set("Cache-Control", "no-store")
		switch {
		case q.URL.Path == "/healthz":
			w.Header().Set("Content-Type", "application/json")
			_, _ = w.Write([]byte(`{"status":"alive"}`))
		case q.URL.Path == "/readyz":
			check, done := context.WithTimeout(q.Context(), 2*time.Second)
			defer done()
			if r.ctx.Err() != nil || db.PingContext(check) != nil {
				http.Error(w, "not ready", 503)
				return
			}
			w.Header().Set("Content-Type", "application/json")
			mode, count := "production", len(c.Models)
			if c.Offline.Enabled {
				mode = "offline-controlled"
				count = 1
			}
			_ = json.NewEncoder(w).Encode(map[string]any{"status": "ready", "persistence": "mysql", "models_configured": count, "profile": mode, "management_enabled": c.Management.Enabled})
		case q.URL.Path == "/api/admin/v1/session":
			sessions.ServeHTTP(w, q)
		case strings.HasPrefix(q.URL.Path, "/api/agent/v1/"):
			agent.ServeHTTP(w, q)
		case strings.HasPrefix(q.URL.Path, "/api/admin/v1/"):
			admin.ServeHTTP(w, q)
		case strings.HasPrefix(q.URL.Path, "/api/") || strings.HasPrefix(q.URL.Path, "/__maas/") || strings.HasPrefix(q.URL.Path, "/internal/"):
			http.NotFound(w, q)
		default:
			static.ServeHTTP(w, q)
		}
	})
	p, e := sessions.principal(ctx, c.Auth.AdminID)
	if e != nil {
		return nil, errors.New("bootstrap_admin_not_initialized")
	}
	documents, e := s.List(ctx, p)
	if e != nil {
		return nil, e
	}
	for _, doc := range documents {
		for _, run := range doc.Runs {
			if run.AR == nil {
				continue
			}
			if run.Status == "running" {
				if e = s.Recover(ctx, p, doc.ID, run.ID); e != nil {
					return nil, e
				}
			}
			if run.Status == "accepted" || run.Status == "waiting_approval" {
				_ = host.Schedule(p, doc.ID, run.ID)
			}
		}
	}
	r.monitorStarted = true
	go func() {
		defer close(r.done)
		tick := time.NewTicker(time.Second)
		defer tick.Stop()
		for {
			select {
			case <-root.Done():
				return
			case <-tick.C:
				var own int
				check, finish := context.WithTimeout(root, 2*time.Second)
				e := lease.QueryRowContext(check, "SELECT IS_USED_LOCK(CONCAT('maas-product-runtime:',DATABASE()))=CONNECTION_ID()").Scan(&own)
				finish()
				if e != nil || own != 1 {
					cancel()
					return
				}
			}
		}
	}()
	ok = true
	return r, nil
}
func (r *Runtime) Done() <-chan struct{} { return r.ctx.Done() }
func (r *Runtime) Close() {
	r.closeOnce.Do(func() {
		r.cancel()
		if r.host != nil {
			r.host.Close()
		}
		if r.models != nil {
			r.models.Close()
		}
		if r.lease != nil {
			_, _ = r.lease.ExecContext(context.Background(), "SELECT RELEASE_LOCK(CONCAT('maas-product-runtime:',DATABASE()))")
			r.lease.Close()
		}
		if r.DB != nil {
			for i := len(r.closers) - 1; i >= 0; i-- {
				_ = r.closers[i].Close()
			}
			r.DB.Close()
		}
		if r.monitorStarted {
			<-r.done
		}
	})
}
