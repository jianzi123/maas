package app

import (
	"context"
	"crypto/hmac"
	"crypto/pbkdf2"
	"crypto/rand"
	"crypto/sha256"
	"database/sql"
	"encoding/hex"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"strings"
	"time"

	"github.com/google/uuid"
	a "github.com/jianzi123/maas/internal/agentruntime"
)

const passwordIterations = 600000

type Sessions struct {
	DB     *sql.DB
	Config AuthConfig
	Origin string
}

func sum(raw string) string { b := sha256.Sum256([]byte(raw)); return hex.EncodeToString(b[:]) }
func randomToken() string {
	var b [32]byte
	if _, e := rand.Read(b[:]); e != nil {
		panic("secure randomness unavailable")
	}
	return hex.EncodeToString(b[:])
}
func (s *Sessions) principal(ctx context.Context, id string) (a.Principal, error) {
	var p a.Principal
	var enabled bool
	e := s.DB.QueryRowContext(ctx, "SELECT admin_id,policy_revision,enabled FROM product_admins WHERE admin_id=?", id).Scan(&p.ID, &p.Revision, &enabled)
	if e != nil || !enabled {
		return p, a.ErrForbidden
	}
	p.Permissions = map[string]bool{"tools.calculate": true, "models.read": true, "tools.approve": true}
	return p, nil
}
func (s *Sessions) Reauthorize(ctx context.Context, old a.Principal) (a.Principal, error) {
	return s.principal(ctx, old.ID)
}
func (s *Sessions) Authenticate(r *http.Request, write bool) (a.Principal, error) {
	if len(r.Header.Values("Authorization")) != 0 {
		return a.Principal{}, a.ErrForbidden
	}
	cookies := []string{}
	for _, c := range r.Cookies() {
		if c.Name == "maas_session" {
			cookies = append(cookies, c.Value)
		}
	}
	if len(cookies) != 1 || len(cookies[0]) != 64 {
		return a.Principal{}, errors.New("unauthenticated")
	}
	var id, csrf string
	var expires time.Time
	var revoked bool
	e := s.DB.QueryRowContext(r.Context(), "SELECT admin_id,csrf_token,expires_at,revoked FROM product_sessions WHERE token_sha256=?", sum(cookies[0])).Scan(&id, &csrf, &expires, &revoked)
	if e != nil || revoked || !time.Now().UTC().Before(expires) {
		return a.Principal{}, errors.New("unauthenticated")
	}
	if write && (len(r.Header.Values("Origin")) != 1 || r.Header.Get("Origin") != s.Origin || len(r.Header.Values("X-CSRF-Token")) != 1 || !hmac.Equal([]byte(r.Header.Get("X-CSRF-Token")), []byte(csrf))) {
		return a.Principal{}, a.ErrForbidden
	}
	return s.principal(r.Context(), id)
}
func (s *Sessions) Authorize(r *http.Request, write bool) error {
	_, e := s.Authenticate(r, write)
	return e
}
func (s *Sessions) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	w.Header().Set("Cache-Control", "no-store")
	id := uuid.NewString()
	w.Header().Set("X-Request-ID", id)
	fail := func(status int, code string) {
		w.WriteHeader(status)
		_ = json.NewEncoder(w).Encode(map[string]any{"error": map[string]any{"code": code, "message": code, "request_id": id, "retryable": false, "reset_at": nil, "retry_after_seconds": nil, "param": nil, "budget_dimension": nil, "policy_revision": nil}})
	}
	if r.Method == "POST" {
		if r.Header.Get("Origin") != s.Origin || len(r.Header.Values("Origin")) != 1 || !strings.HasPrefix(r.Header.Get("Content-Type"), "application/json") {
			fail(403, "forbidden")
			return
		}
		var in struct {
			Username string `json:"username"`
			Password string `json:"password"`
		}
		d := json.NewDecoder(http.MaxBytesReader(w, r.Body, 4096))
		d.DisallowUnknownFields()
		if d.Decode(&in) != nil || d.Decode(new(any)) != io.EOF || len(in.Username) > 128 || len(in.Password) > 1024 {
			fail(400, "invalid_request")
			return
		}
		// Durable per-account throttling survives process restart and replicas.
		window := time.Now().Unix() / 60
		identity := sum(s.Config.AdminID)
		_, e := s.DB.ExecContext(r.Context(), `INSERT INTO product_login_attempts(identity_sha256,window_start,attempts) VALUES(?,?,1) ON DUPLICATE KEY UPDATE attempts=IF(window_start=VALUES(window_start),attempts+1,1),window_start=VALUES(window_start)`, identity, window)
		if e != nil {
			fail(503, "dependency_unavailable")
			return
		}
		var attempts int
		if s.DB.QueryRowContext(r.Context(), "SELECT attempts FROM product_login_attempts WHERE identity_sha256=?", identity).Scan(&attempts) != nil {
			fail(503, "dependency_unavailable")
			return
		}
		if attempts > 10 {
			fail(429, "login_rate_limited")
			return
		}
		var admin string
		var salt, verifier []byte
		var enabled bool
		e = s.DB.QueryRowContext(r.Context(), "SELECT admin_id,salt,verifier,enabled FROM product_admins WHERE username=?", in.Username).Scan(&admin, &salt, &verifier, &enabled)
		if e != nil || !enabled {
			salt = make([]byte, 32)
			verifier = make([]byte, 32)
		}
		derived, kdfErr := pbkdf2.Key(sha256.New, in.Password, salt, passwordIterations, 32)
		if e != nil || !enabled || kdfErr != nil || !hmac.Equal(derived, verifier) {
			fail(401, "unauthenticated")
			return
		}
		token, csrf := randomToken(), randomToken()
		expires := time.Now().UTC().Add(time.Duration(s.Config.SessionTTLSeconds) * time.Second)
		if _, e = s.DB.ExecContext(r.Context(), "INSERT INTO product_sessions(token_sha256,admin_id,csrf_token,expires_at) VALUES(?,?,?,?)", sum(token), admin, csrf, expires); e != nil {
			fail(503, "dependency_unavailable")
			return
		}
		http.SetCookie(w, &http.Cookie{Name: "maas_session", Value: token, Path: "/", HttpOnly: true, Secure: s.Config.SecureCookie, SameSite: http.SameSiteStrictMode, Expires: expires, MaxAge: s.Config.SessionTTLSeconds})
		_ = json.NewEncoder(w).Encode(map[string]any{"admin_id": admin, "csrf_token": csrf, "expires_at": expires})
		return
	}
	p, e := s.Authenticate(r, r.Method != "GET")
	if e != nil {
		fail(401, "unauthenticated")
		return
	}
	var cookie *http.Cookie
	cookie, _ = r.Cookie("maas_session")
	if r.Method == "GET" {
		var csrf string
		var expires time.Time
		if s.DB.QueryRowContext(r.Context(), "SELECT csrf_token,expires_at FROM product_sessions WHERE token_sha256=?", sum(cookie.Value)).Scan(&csrf, &expires) != nil {
			fail(503, "dependency_unavailable")
			return
		}
		_ = json.NewEncoder(w).Encode(map[string]any{"admin_id": p.ID, "csrf_token": csrf, "expires_at": expires})
		return
	}
	if r.Method == "DELETE" {
		if _, e = s.DB.ExecContext(r.Context(), "UPDATE product_sessions SET revoked=TRUE WHERE token_sha256=?", sum(cookie.Value)); e != nil {
			fail(503, "dependency_unavailable")
			return
		}
		http.SetCookie(w, &http.Cookie{Name: "maas_session", Value: "", Path: "/", HttpOnly: true, Secure: s.Config.SecureCookie, SameSite: http.SameSiteStrictMode, MaxAge: -1})
		w.WriteHeader(204)
		return
	}
	fail(405, "method_not_allowed")
}
