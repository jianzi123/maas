// Package workbench is the explicit loopback-only local integration entrypoint.
package workbench

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"github.com/google/uuid"
	"github.com/jianzi123/maas/internal/controlapi"
	"github.com/jianzi123/maas/internal/webconsole"
	"net/http"
	"strings"
	"sync"
	"time"
)

type LocalSession struct {
	mu                  sync.RWMutex
	bootstrap           controlapi.BootstrapSession
	token, csrf, origin string
}

func NewLocalSession(origin string) *LocalSession {
	token, csrf := uuid.NewString()+uuid.NewString(), uuid.NewString()+uuid.NewString()
	digest := func(raw string) string { v := sha256.Sum256([]byte(raw)); return hex.EncodeToString(v[:]) }
	return &LocalSession{token: token, csrf: csrf, origin: origin, bootstrap: controlapi.BootstrapSession{SessionSHA256: digest(token), CSRFSHA256: digest(csrf), Origin: origin}}
}
func (s *LocalSession) Authorize(r *http.Request, write bool) error {
	s.mu.RLock()
	b := s.bootstrap
	s.mu.RUnlock()
	return b.Authorize(r, write)
}
func (s *LocalSession) install(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	w.Header().Set("Cache-Control", "no-store")
	if r.Host != strings.TrimPrefix(s.origin, "http://") || len(r.Header.Values("Origin")) != 1 || r.Header.Get("Origin") != s.origin || (r.Method != "POST" && r.Method != "DELETE") {
		http.Error(w, `{"message":"local origin required"}`, 403)
		return
	}
	if r.Method == "DELETE" {
		s.mu.Lock()
		s.bootstrap.Expires = time.Time{}
		s.mu.Unlock()
		http.SetCookie(w, &http.Cookie{Name: "maas_session", Value: "", Path: "/", HttpOnly: true, SameSite: http.SameSiteStrictMode, MaxAge: -1})
		w.WriteHeader(http.StatusNoContent)
		return
	}
	s.mu.Lock()
	expires := time.Now().UTC().Add(25 * time.Minute)
	s.bootstrap.Expires = expires
	s.mu.Unlock()
	http.SetCookie(w, &http.Cookie{Name: "maas_session", Value: s.token, Path: "/", HttpOnly: true, SameSite: http.SameSiteStrictMode, MaxAge: 1500})
	_ = json.NewEncoder(w).Encode(map[string]any{"csrf_token": s.csrf, "expires_at": expires.Format(time.RFC3339)})
}

func Handler(admin http.Handler, session *LocalSession, staticRoot string, example map[string]any) http.Handler {
	static := webconsole.Handler(staticRoot)
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch {
		case r.URL.Path == "/__maas/local-session":
			session.install(w, r)
		case r.URL.Path == "/__maas/workbench":
			if r.Method != "GET" || session.Authorize(r, false) != nil {
				http.Error(w, "local session required", 403)
				return
			}
			w.Header().Set("Cache-Control", "no-store")
			w.Header().Set("Content-Type", "application/json")
			_ = json.NewEncoder(w).Encode(map[string]any{"mode": "local", "inference_available": false, "example_release": example})
		case strings.HasPrefix(r.URL.Path, "/api/"):
			admin.ServeHTTP(w, r)
		case r.URL.Path == "/api" || r.URL.Path == "/v1" || strings.HasPrefix(r.URL.Path, "/v1/"):
			id := uuid.NewString()
			w.Header().Set("X-Request-ID", id)
			w.Header().Set("Cache-Control", "no-store")
			w.Header().Set("Content-Type", "application/json")
			w.WriteHeader(503)
			_ = json.NewEncoder(w).Encode(map[string]any{"error": map[string]any{"code": "release_not_callable", "message": "Real gateway and validation dependencies are unavailable.", "request_id": id, "retryable": false, "reset_at": nil, "retry_after_seconds": nil, "param": nil, "budget_dimension": nil, "policy_revision": nil}})
		default:
			static.ServeHTTP(w, r)
		}
	})
}
