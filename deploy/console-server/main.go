// Static console entrypoint. Management and inference traffic stays on Go API ingress.
package main

import (
	"fmt"
	"net/http"
	"os"
	"path"
	"path/filepath"
	"strings"
	"time"
)

func handler(root string) http.Handler {
	files := http.FileServer(http.Dir(root))
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("X-Content-Type-Options", "nosniff")
		if r.Method != http.MethodGet && r.Method != http.MethodHead {
			w.Header().Set("Allow", "GET, HEAD")
			w.WriteHeader(http.StatusMethodNotAllowed)
			return
		}
		p := path.Clean("/" + r.URL.Path)
		// Never turn API errors, the dev session bridge or directory listings into SPA success.
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
				info, err := f.Stat()
				f.Close()
				if err == nil && info.Mode().IsRegular() && info.Size() > 0 {
					w.WriteHeader(http.StatusNoContent)
					return
				}
			}
			w.WriteHeader(http.StatusServiceUnavailable)
			return
		}
		clean := path.Clean("/" + p)
		f, err := os.Stat(filepath.Join(root, filepath.FromSlash(clean)))
		if err == nil && f.Mode().IsRegular() && clean != "/index.html" {
			files.ServeHTTP(w, r)
			return
		}
		if path.Ext(clean) != "" || strings.HasPrefix(clean, "/assets/") {
			http.NotFound(w, r)
			return
		}
		w.Header().Set("Cache-Control", "no-store")
		http.ServeFile(w, r, index)
	})
}

func main() {
	s := &http.Server{Addr: ":8080", Handler: handler("/app/dist"), ReadHeaderTimeout: 5 * time.Second, IdleTimeout: 30 * time.Second}
	if err := s.ListenAndServe(); err != nil {
		fmt.Fprintln(os.Stderr, "console server stopped")
		os.Exit(1)
	}
}
