// Package controlapi exposes session-protected management/query APIs only.
package controlapi

import (
	"context"
	"crypto/sha256"
	"crypto/subtle"
	"encoding/hex"
	"encoding/json"
	"errors"
	"github.com/google/uuid"
	"github.com/jianzi123/maas/internal/kernel"
	"github.com/jianzi123/maas/internal/protocol"
	"github.com/jianzi123/maas/internal/release/history"
	"io"
	"net/http"
	"net/url"
	"strings"
	"time"
)

type SessionVerifier interface {
	Authorize(*http.Request, bool) error
}

// BootstrapSession is a bounded local/controlled installation adapter, not a
// login service. Only digests of independently random 256-bit tokens are held.
type BootstrapSession struct {
	SessionSHA256, CSRFSHA256, Origin string
	Expires                           time.Time
}

func (a BootstrapSession) Authorize(r *http.Request, write bool) error {
	if !time.Now().Before(a.Expires) {
		return errors.New("unauthenticated")
	}
	if len(r.Header.Values("Authorization")) > 0 {
		return errors.New("forbidden")
	}
	cookies := []string{}
	for _, c := range r.Cookies() {
		if c.Name == "maas_session" {
			cookies = append(cookies, c.Value)
		}
	}
	if len(cookies) != 1 {
		return errors.New("unauthenticated")
	}
	match := func(raw, digest string) bool {
		if len(raw) < 43 || len(raw) > 256 {
			return false
		}
		want, e := hex.DecodeString(digest)
		sum := sha256.Sum256([]byte(raw))
		return e == nil && len(want) == 32 && subtle.ConstantTimeCompare(sum[:], want) == 1
	}
	if !match(cookies[0], a.SessionSHA256) {
		return errors.New("unauthenticated")
	}
	if write {
		if len(r.Header.Values("Origin")) != 1 || r.Header.Get("Origin") != a.Origin || len(r.Header.Values("X-CSRF-Token")) != 1 || !match(r.Header.Get("X-CSRF-Token"), a.CSRFSHA256) {
			return errors.New("csrf_failed")
		}
	}
	return nil
}

type RevisionReader interface {
	ReadRevisions(context.Context, string, string, url.Values) (map[string]any, error)
}
type Handler struct {
	Core      *kernel.Store
	Sessions  SessionVerifier
	Revisions RevisionReader
}

func (h Handler) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	id := uuid.NewString()
	w.Header().Set("X-Request-ID", id)
	w.Header().Set("Cache-Control", "no-store")
	w.Header().Set("Content-Type", "application/json")
	failure := func(status int, code string) {
		w.WriteHeader(status)
		_ = json.NewEncoder(w).Encode(map[string]any{"error": map[string]any{"code": code, "message": code, "request_id": id, "retryable": r.Method == "GET" && status == 503, "reset_at": nil, "retry_after_seconds": nil, "param": nil, "budget_dimension": nil, "policy_revision": nil}})
	}
	if h.Core == nil || h.Sessions == nil {
		failure(503, "dependency_unavailable")
		return
	}
	write := r.Method != "GET"
	if e := h.Sessions.Authorize(r, write); e != nil {
		code := e.Error()
		status := 403
		if code == "unauthenticated" {
			status = 401
		}
		if code != "unauthenticated" && code != "csrf_failed" {
			code = "forbidden"
		}
		failure(status, code)
		return
	}
	q, e := url.ParseQuery(r.URL.RawQuery)
	if e != nil {
		failure(400, "invalid_request")
		return
	}
	for _, v := range q {
		if len(v) != 1 {
			failure(400, "invalid_request")
			return
		}
	}
	body := func(name string, target any) error {
		if r.Header.Get("Content-Type") != "application/json" {
			return kernel.ErrPolicy
		}
		b, e := io.ReadAll(io.LimitReader(r.Body, 65537))
		if e != nil || len(b) > 65536 {
			return kernel.ErrPolicy
		}
		canonical, e := protocol.Canonical(b)
		if e != nil {
			return kernel.ErrPolicy
		}
		var value any
		if json.Unmarshal(canonical, &value) != nil || protocol.Validate(name, value) != nil {
			return kernel.ErrPolicy
		}
		return json.Unmarshal(canonical, target)
	}
	var out map[string]any
	status := 200
	schema := ""
	path := strings.TrimPrefix(r.URL.Path, "/api/admin/v1/")
	switch {
	case r.URL.Path == "/api/admin/v1/keys" && r.Method == "POST":
		var v struct {
			Name   string        `json:"name"`
			Policy kernel.Policy `json:"budget_policy"`
		}
		e = body("KeyCreate", &v)
		if e == nil {
			var key, raw string
			key, raw, e = h.Core.CreateManagedKey(r.Context(), v.Name, v.Policy)
			if e == nil {
				var meta map[string]any
				meta, e = h.Core.KeyView(r.Context(), key)
				out = map[string]any{"key": meta, "secret": raw}
				status = 201
				schema = "KeyCreated"
			}
		}
	case r.URL.Path == "/api/admin/v1/keys" && r.Method == "GET":
		for k := range q {
			if k != "cursor" && k != "page_size" {
				e = kernel.ErrPolicy
			}
		}
		if e == nil {
			out, e = h.Core.ListKeys(r.Context(), q)
		}
		schema = "KeyPage"
	case strings.HasPrefix(path, "keys/"):
		parts := strings.Split(path, "/")
		if len(parts) < 2 {
			e = kernel.ErrPolicy
			break
		}
		key := parts[1]
		u, err := uuid.Parse(key)
		if err != nil || u.String() != key {
			e = kernel.ErrPolicy
			break
		}
		if len(parts) == 2 && r.Method == "PATCH" {
			var v struct {
				Expected string        `json:"expected_revision"`
				Limits   kernel.Limits `json:"limits"`
			}
			e = body("KeyPatch", &v)
			if e == nil {
				e = h.Core.PatchKey(r.Context(), key, v.Expected, v.Limits)
			}
		} else if len(parts) == 3 && parts[2] == "revoke" && r.Method == "POST" {
			e = h.Core.Revoke(r.Context(), key)
		} else {
			failure(404, "not_found")
			return
		}
		if e == nil {
			out, e = h.Core.KeyView(r.Context(), key)
		}
		schema = "Key"
	case r.URL.Path == "/api/admin/v1/usage/requests" && r.Method == "GET":
		for k := range q {
			switch k {
			case "request_id", "date_from", "date_to", "key_id", "model_alias", "source_id", "status", "cursor", "page_size":
			default:
				e = kernel.ErrPolicy
			}
		}
		if e == nil {
			out, e = h.Core.ListRequests(r.Context(), q)
		}
		schema = "RequestPage"
		if _, ok := q["request_id"]; ok {
			schema = "RequestLookupPage"
		}
	case r.URL.Path == "/api/admin/v1/usage/summary" && r.Method == "GET":
		out, e = h.Core.Summary(r.Context(), q)
		schema = "SummaryPage"
	case strings.HasPrefix(path, "model-releases/") && strings.HasSuffix(path, "/revisions") && r.Method == "GET":
		p := strings.Split(path, "/")
		if len(p) != 4 {
			e = kernel.ErrPolicy
		} else if h.Revisions == nil {
			e = kernel.ErrUnavailable
		} else {
			out, e = h.Revisions.ReadRevisions(r.Context(), p[1], p[2], q)
			schema = "ReleaseRevisionPage"
		}
	default:
		failure(404, "not_found")
		return
	}
	if e != nil {
		code, s := "dependency_unavailable", 503
		switch {
		case errors.Is(e, history.ErrForbidden):
			code, s = "forbidden", 403
		case errors.Is(e, history.ErrInvalid):
			code, s = "invalid_request", 400
		case errors.Is(e, kernel.ErrNotFound), errors.Is(e, history.ErrNotFound):
			code, s = "not_found", 404
		case errors.Is(e, kernel.ErrConflict):
			code, s = "state_conflict", 409
		case errors.Is(e, kernel.ErrPolicy), errors.Is(e, kernel.ErrPrice):
			code, s = "invalid_request", 400
		case errors.Is(e, kernel.ErrKey):
			code, s = "key_revoked", 409
		}
		failure(s, code)
		return
	}
	if schema != "" && protocol.Validate(schema, out) != nil {
		failure(503, "dependency_unavailable")
		return
	}
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(out)
}
