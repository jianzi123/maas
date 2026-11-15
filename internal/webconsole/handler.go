// Package webconsole serves the shared Vue build for local and image entrypoints.
package webconsole

import (
	"net/http"
	"os"
	"path"
	"path/filepath"
	"strings"
)

func Handler(root string) http.Handler {
	files := http.FileServer(http.Dir(root))
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("X-Content-Type-Options", "nosniff")
		if r.Method != http.MethodGet && r.Method != http.MethodHead {
			w.Header().Set("Allow", "GET, HEAD")
			w.WriteHeader(http.StatusMethodNotAllowed)
			return
		}
		p := path.Clean("/" + r.URL.Path)
		for _, prefix := range []string{"/api", "/v1", "/__maas"} {
			if p == prefix || strings.HasPrefix(p, prefix+"/") {
				http.NotFound(w, r)
				return
			}
		}
		if p == "/healthz" {
			w.WriteHeader(http.StatusNoContent)
			return
		}
		index := filepath.Join(root, "index.html")
		if p == "/readyz" {
			if f, err := os.Open(index); err == nil {
				info, e := f.Stat()
				f.Close()
				if e == nil && info.Mode().IsRegular() && info.Size() > 0 {
					w.WriteHeader(http.StatusNoContent)
					return
				}
			}
			w.WriteHeader(http.StatusServiceUnavailable)
			return
		}
		if f, err := os.Stat(filepath.Join(root, filepath.FromSlash(p))); err == nil && f.Mode().IsRegular() && p != "/index.html" {
			files.ServeHTTP(w, r)
			return
		}
		if path.Ext(p) != "" || strings.HasPrefix(p, "/assets/") {
			http.NotFound(w, r)
			return
		}
		w.Header().Set("Cache-Control", "no-store")
		http.ServeFile(w, r, index)
	})
}
