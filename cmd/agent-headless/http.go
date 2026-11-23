//go:build agentcontrolled

package main

import (
	"context"
	"crypto/rand"
	"encoding/json"
	"errors"
	"fmt"
	"net"
	"net/http"
	"os"
	"os/signal"
	"path/filepath"
	"syscall"
	"time"

	"github.com/google/uuid"
	a "github.com/jianzi123/maas/internal/agentruntime"
	"github.com/jianzi123/maas/internal/workbench"
)

type localAuth struct {
	session   *workbench.LocalSession
	principal a.Principal
}

func (l localAuth) Authenticate(r *http.Request, write bool) (a.Principal, error) {
	if e := l.session.Authorize(r, write); e != nil {
		return a.Principal{}, e
	}
	return l.principal, nil
}

type localModels struct{}

func (localModels) Resolve(_ context.Context, _ a.Principal, alias, mode string) (a.Model, error) {
	if alias != "demo" {
		return a.Model{}, a.ErrCapability
	}
	protocol := "text-v1"
	if mode == "agent" {
		protocol = "tools-v1"
	}
	return a.Model{Alias: "demo", Source: "controlled-local", Revision: "1", Protocol: protocol}, nil
}
func (localModels) Modes(context.Context, a.Principal) ([]map[string]any, error) {
	return []map[string]any{{"model_alias": "demo", "text_protocol": "text-v1", "tools_protocol": "tools-v1", "capability_revision": "controlled-v1", "approval_state": "controlled"}}, nil
}

// This local entry uses the existing loopback-only workbench bootstrap session,
// Origin/CSRF checks and cookie. It never accepts a platform key or provider URL.
func serveAR(address, owner, contractPath, stateDir string, store a.SessionStore) error {
	host, _, e := net.SplitHostPort(address)
	if e != nil || host != "127.0.0.1" {
		return a.ErrInvalid
	}
	if _, e = uuid.Parse(owner); e != nil {
		return a.ErrInvalid
	}
	contract, e := os.ReadFile(contractPath)
	if e != nil {
		return e
	}
	keyPath := filepath.Join(stateDir, ".pagination-key")
	key, e := os.ReadFile(keyPath)
	if errors.Is(e, os.ErrNotExist) {
		key = make([]byte, 32)
		if _, e = rand.Read(key); e != nil {
			return e
		}
		f, e := os.OpenFile(keyPath, os.O_CREATE|os.O_EXCL|os.O_WRONLY, 0600)
		if e != nil {
			return e
		}
		_, e = f.Write(key)
		if e == nil {
			e = f.Sync()
		}
		ce := f.Close()
		if e != nil {
			return e
		}
		if ce != nil {
			return ce
		}
	} else if e != nil {
		return e
	}
	if len(key) != 32 {
		return a.ErrUnavailable
	}
	p := a.Principal{ID: owner, Revision: "controlled-auth-v1", Permissions: map[string]bool{"tools.calculate": true, "models.read": true}}
	tools, e := a.NewRegistry(a.Calculator{}, a.ModelDirectory{Read: func(_ context.Context, scope a.Principal) ([]string, error) {
		if scope.ID != owner {
			return nil, a.ErrForbidden
		}
		return []string{"demo"}, nil
	}})
	if e != nil {
		return e
	}
	limits := a.Limits{Currency: "TST", Steps: 4, Calls: 4, Tokens: 100, Money: 100, Duration: 10 * time.Second, ToolTimeout: time.Second, ApprovalTTL: time.Minute, InputBytes: 32768, OutputBytes: 8192, Events: 1000}
	s, e := a.NewService(store, controlledModel{}, tools, limits)
	if e != nil {
		return e
	}
	// Bound for this deterministic synthetic model only; not a real tokenizer.
	s.CountContext = func(_ context.Context, r a.Request) (int64, error) {
		b, _ := json.Marshal(struct {
			Messages []a.Message
			Tools    []a.ToolSpec
		}{r.Messages, r.Tools})
		return int64(len(b)), nil
	}
	s.Reauthorize = func(_ context.Context, original a.Principal) (a.Principal, error) {
		if original.ID != owner || original.Revision != p.Revision {
			return a.Principal{}, a.ErrForbidden
		}
		return p, nil
	}
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	executor, e := a.NewHost(ctx, s, 2, s.Reauthorize)
	if e != nil {
		return e
	}
	defer executor.Close()
	origin := "http://" + address
	session := workbench.NewLocalSession(origin)
	policy := a.ARLimits{Steps: 4, Calls: 4, Tools: 8, Duration: 10000, ToolTimeout: 1000, OutputBytes: 8192, ContextTokens: 32768, NoProgress: 3, Tokens: "100", Money: "100", Currency: "TST"}
	api, e := a.NewARHandler(s, localAuth{session, p}, localModels{}, policy, key, contract, 20*time.Second)
	if e != nil {
		return e
	}
	api.Dispatch = executor.Schedule
	// The exclusive LocalStore lock proves there is no other local owner. Its
	// stale lock is never stolen automatically. Recover only after that check.
	documents, e := s.List(ctx, p)
	if e != nil {
		return e
	}
	for _, document := range documents {
		if document.AR == nil {
			continue
		}
		for _, r := range document.Runs {
			if r.Status == "running" {
				if e = s.Recover(ctx, p, document.ID, r.ID); e != nil {
					return e
				}
				fresh, e := s.Get(ctx, p, document.ID)
				if e != nil {
					return e
				}
				for _, saved := range fresh.Runs {
					if saved.ID == r.ID {
						r = saved
						break
					}
				}
			}
			if r.Status == "accepted" || r.Status == "waiting_approval" {
				if e = executor.Schedule(p, document.ID, r.ID); e != nil {
					return e
				}
			}
		}
	}
	server := &http.Server{Addr: address, Handler: workbench.Handler(api, session, ".cache/no-static-ui", nil), ReadHeaderTimeout: 5 * time.Second, ReadTimeout: 10 * time.Second, WriteTimeout: 25 * time.Second, IdleTimeout: 30 * time.Second, MaxHeaderBytes: 16384}
	done := make(chan error, 1)
	go func() { done <- server.ListenAndServe() }()
	fmt.Printf("Controlled model / real safe tools. AR-1: %s/api/agent/v1; bootstrap: POST %s/__maas/local-session with exact Origin. State: %s\n", origin, origin, stateDir)
	select {
	case e = <-done:
		if errors.Is(e, http.ErrServerClosed) {
			return nil
		}
		return e
	case <-ctx.Done():
	}
	shutdown, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	e = server.Shutdown(shutdown)
	if e != nil {
		_ = server.Close()
	}
	listenErr := <-done
	if e != nil {
		return e
	}
	if !errors.Is(listenErr, http.ErrServerClosed) {
		return listenErr
	}
	return nil
}
