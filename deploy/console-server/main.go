// Static console entrypoint. Management and inference traffic stays on Go API ingress.
package main

import (
	"fmt"
	"github.com/jianzi123/maas/internal/webconsole"
	"net/http"
	"os"
	"time"
)

func handler(root string) http.Handler {
	return webconsole.Handler(root)
}

func main() {
	s := &http.Server{Addr: ":8080", Handler: handler("/app/dist"), ReadHeaderTimeout: 5 * time.Second, IdleTimeout: 30 * time.Second}
	if err := s.ListenAndServe(); err != nil {
		fmt.Fprintln(os.Stderr, "console server stopped")
		os.Exit(1)
	}
}
