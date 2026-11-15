package workbench

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"testing"
)

func TestLocalSessionOriginCSRFAuthAndLogout(t *testing.T) {
	s := NewLocalSession("http://127.0.0.1:4179")
	install := func(host, origin string) *httptest.ResponseRecorder {
		r := httptest.NewRequest("POST", "http://"+host+"/__maas/local-session", nil)
		r.Header.Set("Origin", origin)
		w := httptest.NewRecorder()
		s.install(w, r)
		return w
	}
	for _, pair := range [][2]string{{"127.0.0.1:4179", "http://other.invalid"}, {"other.invalid", "http://127.0.0.1:4179"}} {
		if w := install(pair[0], pair[1]); w.Code != 403 || len(w.Result().Cookies()) != 0 {
			t.Fatal("cross-origin session issued")
		}
	}
	w := install("127.0.0.1:4179", "http://127.0.0.1:4179")
	if w.Code != 200 {
		t.Fatal(w.Code)
	}
	cookies := w.Result().Cookies()
	if len(cookies) != 1 || !cookies[0].HttpOnly || cookies[0].SameSite != http.SameSiteStrictMode {
		t.Fatal("session cookie policy")
	}
	var body struct {
		CSRF string `json:"csrf_token"`
	}
	if json.Unmarshal(w.Body.Bytes(), &body) != nil || body.CSRF == "" {
		t.Fatal("missing CSRF")
	}
	r := httptest.NewRequest("PUT", "http://127.0.0.1:4179/api/admin/v1/model-releases/maas-local/local-example", nil)
	r.AddCookie(cookies[0])
	r.Header.Set("Origin", "http://127.0.0.1:4179")
	if s.Authorize(r, true) == nil {
		t.Fatal("missing CSRF accepted")
	}
	r.Header.Set("X-CSRF-Token", body.CSRF)
	if s.Authorize(r, true) != nil {
		t.Fatal("valid local session rejected")
	}
	r.Header.Set("Authorization", "Bearer not-a-management-session")
	if s.Authorize(r, true) == nil {
		t.Fatal("consumer key used as management auth")
	}
	r.Header.Del("Authorization")
	logout := httptest.NewRequest("DELETE", "http://127.0.0.1:4179/__maas/local-session", nil)
	logout.Header.Set("Origin", "http://127.0.0.1:4179")
	s.install(httptest.NewRecorder(), logout)
	if s.Authorize(r, true) == nil {
		t.Fatal("logout left management session active")
	}
}

func TestUnifiedRoutesNeverReturnHTMLForInference(t *testing.T) {
	dir := t.TempDir()
	os.WriteFile(filepath.Join(dir, "index.html"), []byte("<html>workbench</html>"), 0600)
	h := Handler(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { w.WriteHeader(401) }), NewLocalSession("http://127.0.0.1:4179"), dir, nil)
	for _, tc := range []struct {
		path   string
		status int
	}{{"/", 200}, {"/api/admin/v1/keys", 401}, {"/v1/chat/completions", 503}, {"/assets/missing.js", 404}, {"/__maas/workbench", 403}} {
		w := httptest.NewRecorder()
		h.ServeHTTP(w, httptest.NewRequest("GET", tc.path, nil))
		if w.Code != tc.status {
			t.Fatal(tc.path, w.Code)
		}
	}
}
