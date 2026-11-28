package agentruntime

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/google/uuid"
)

type dependencyAuthFunc func(*http.Request, bool) (Principal, error)

func (f dependencyAuthFunc) Authenticate(r *http.Request, write bool) (Principal, error) {
	return f(r, write)
}

type untouchedAuthStore struct {
	SessionStore
	actions int
}

func (s *untouchedAuthStore) Get(ctx context.Context, id string) (Session, error) {
	s.actions++
	return s.SessionStore.Get(ctx, id)
}
func (s *untouchedAuthStore) List(ctx context.Context, owner string) ([]Session, error) {
	s.actions++
	return s.SessionStore.List(ctx, owner)
}
func (s *untouchedAuthStore) CompareAndSwap(ctx context.Context, v Session, revision int64) error {
	s.actions++
	return s.SessionStore.CompareAndSwap(ctx, v, revision)
}

type untouchedAuthCatalog struct {
	ARCatalog
	actions int
}

func (c *untouchedAuthCatalog) Resolve(ctx context.Context, p Principal, alias, mode string) (Model, error) {
	c.actions++
	return c.ARCatalog.Resolve(ctx, p, alias, mode)
}
func (c *untouchedAuthCatalog) Modes(ctx context.Context, p Principal) ([]map[string]any, error) {
	c.actions++
	return c.ARCatalog.Modes(ctx, p)
}

func TestARAuthDependencyClassificationAndNoActions(t *testing.T) {
	cases := []struct {
		name   string
		p      Principal
		err    error
		status int
		code   string
	}{
		{"dependency", Principal{}, ErrUnavailable, 503, "dependency_unavailable"},
		{"wrapped_dependency", Principal{}, fmt.Errorf("private internal detail: %w", ErrUnavailable), 503, "dependency_unavailable"},
		{"dependency_with_principal", arActor, ErrUnavailable, 503, "dependency_unavailable"},
		{"unauthenticated", Principal{}, errors.New("unauthenticated"), 401, "unauthenticated"},
		{"forbidden", Principal{}, ErrForbidden, 403, "forbidden"},
		{"wrapped_forbidden", Principal{}, fmt.Errorf("private internal detail: %w", ErrForbidden), 403, "forbidden"},
		{"unknown_error", Principal{}, errors.New("private internal detail"), 403, "forbidden"},
		{"status_error_is_not_dependency", Principal{}, arFailure(503, "private_internal_code"), 403, "forbidden"},
		{"missing_principal", Principal{}, nil, 403, "forbidden"},
		{"missing_revision", Principal{ID: arActor.ID}, nil, 403, "forbidden"},
		{"invalid_subject", Principal{ID: "invalid", Revision: "policy-1"}, nil, 403, "forbidden"},
	}
	for _, tc := range cases {
		for _, method := range []string{"GET", "POST"} {
			t.Run(tc.name+"/"+method, func(t *testing.T) {
				h, model, _ := setupAR(t, arPlain, nil)
				store := &untouchedAuthStore{SessionStore: h.Service.Store}
				catalog := &untouchedAuthCatalog{ARCatalog: h.Catalog}
				h.Service.Store, h.Catalog = store, catalog
				authCalls := 0
				h.Auth = dependencyAuthFunc(func(_ *http.Request, write bool) (Principal, error) {
					authCalls++
					if write != (method != "GET") {
						t.Fatal("wrong write classification")
					}
					return tc.p, tc.err
				})
				path := "capabilities"
				var body any
				if method == "POST" {
					path = "sessions"
					body = ARCreate{OperationID: uuid.NewString(), Title: "should not execute", Alias: "controlled"}
				}
				w := arHTTP(t, h, method, path, body, "", "Error", tc.status)
				errorValue := arDecode(t, w)["error"].(map[string]any)
				if errorValue["code"] != tc.code || errorValue["message"] != tc.code || errorValue["retryable"] != (method == "GET" && tc.status == 503) || errorValue["http_request_id"] != w.Header().Get("X-Request-ID") {
					t.Fatal("wrong error classification", errorValue)
				}
				if _, e := uuid.Parse(w.Header().Get("X-Request-ID")); e != nil {
					t.Fatal("missing trusted Q correlation", e)
				}
				if strings.Contains(w.Body.String(), "private") {
					t.Fatal("internal auth message leaked")
				}
				if authCalls != 1 || store.actions != 0 || catalog.actions != 0 || model.calls.Load() != 0 {
					t.Fatal("auth error reached business actions", authCalls, store.actions, catalog.actions, model.calls.Load())
				}
			})
		}
	}
}

func TestARAuthInitialStreamDependencyAndSecurityControls(t *testing.T) {
	for _, err := range []error{ErrUnavailable, fmt.Errorf("private detail: %w", ErrUnavailable)} {
		h, model, _ := setupAR(t, arPlain, nil)
		h.Auth = dependencyAuthFunc(func(*http.Request, bool) (Principal, error) { return Principal{}, err })
		w := arHTTP(t, h, "GET", "sessions/"+uuid.NewString()+"/runs/"+uuid.NewString()+"/events/stream", nil, "", "Error", 503)
		if w.Header().Get("Content-Type") != "application/json" || strings.Contains(w.Body.String(), "event:") || model.calls.Load() != 0 {
			t.Fatal("initial auth error became a stream")
		}
	}
	h, model, _ := setupAR(t, arPlain, nil)
	q := httptest.NewRequest("POST", "/api/agent/v1/sessions", strings.NewReader(`{}`))
	w := httptest.NewRecorder()
	h.ServeHTTP(w, q)
	if w.Code != 403 {
		t.Fatal("missing CSRF accepted", w.Code)
	}
	var value any
	if e := json.Unmarshal(w.Body.Bytes(), &value); e != nil || h.Validate("Error", value) != nil {
		t.Fatal("invalid CSRF error schema", e)
	}
	arHTTP(t, h, "GET", "capabilities", nil, "", "Capabilities", 200)
	arCreateSession(t, h)
	if model.calls.Load() != 0 {
		t.Fatal("create/negative auth generated a model call")
	}
}
