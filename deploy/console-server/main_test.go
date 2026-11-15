package main

import (
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestStaticConsoleAndSPARoutes(t *testing.T) {
	root := t.TempDir()
	os.Mkdir(filepath.Join(root, "assets"), 0700)
	os.WriteFile(filepath.Join(root, "index.html"), []byte("<html>console</html>"), 0600)
	os.WriteFile(filepath.Join(root, "assets", "main.js"), []byte("const consoleReady=true;"), 0600)
	h := handler(root)
	for _, tc := range []struct {
		path   string
		status int
		text   string
	}{
		{"/", 200, "<html>console</html>"},
		{"/model-releases/detail", 200, "<html>console</html>"},
		{"/assets/main.js", 200, "const consoleReady=true;"},
		{"/assets/missing.js", 404, ""},
		{"/missing.css", 404, ""},
		{"/api/admin/v1/models", 404, ""},
		{"/assets/../api/admin/v1/models", 404, ""},
		{"/v1/chat/completions", 404, ""},
		{"/__maas/local-session", 404, ""},
		{"/healthz", 204, ""},
		{"/readyz", 204, ""},
	} {
		t.Run(tc.path, func(t *testing.T) {
			w := httptest.NewRecorder()
			h.ServeHTTP(w, httptest.NewRequest("GET", tc.path, nil))
			if w.Code != tc.status || (tc.text != "" && w.Body.String() != tc.text) {
				t.Fatalf("unexpected response: %d", w.Code)
			}
			if tc.status == 404 && strings.Contains(w.Body.String(), "<html>console") {
				t.Fatal("API or missing asset served SPA")
			}
		})
	}
}

func TestMissingAssetsStayUnready(t *testing.T) {
	root := t.TempDir()
	for _, content := range []string{"", "<html>ready</html>"} {
		os.WriteFile(filepath.Join(root, "index.html"), []byte(content), 0600)
		w := httptest.NewRecorder()
		handler(root).ServeHTTP(w, httptest.NewRequest("GET", "/readyz", nil))
		if (w.Code == 204) != (content != "") {
			t.Fatalf("unexpected ready state: %d", w.Code)
		}
	}
	os.Remove(filepath.Join(root, "index.html"))
	w := httptest.NewRecorder()
	handler(root).ServeHTTP(w, httptest.NewRequest("GET", "/readyz", nil))
	if w.Code != 503 {
		t.Fatal("missing index reported ready")
	}
}

func TestReadOnlyAndUncachedShell(t *testing.T) {
	root := t.TempDir()
	os.WriteFile(filepath.Join(root, "index.html"), []byte("<html>console</html>"), 0600)
	h := handler(root)
	w := httptest.NewRecorder()
	h.ServeHTTP(w, httptest.NewRequest("POST", "/", nil))
	if w.Code != 405 {
		t.Fatal("write accepted")
	}
	w = httptest.NewRecorder()
	h.ServeHTTP(w, httptest.NewRequest("GET", "/releases", nil))
	if w.Header().Get("Cache-Control") != "no-store" {
		t.Fatal("SPA shell can be stale")
	}
	w = httptest.NewRecorder()
	h.ServeHTTP(w, httptest.NewRequest("GET", "/../outside.txt", nil))
	if w.Code == 200 {
		t.Fatal("traversal accepted")
	}
}
