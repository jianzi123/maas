// publisher serves only the existing authenticated release-command contract.
package main

import (
	"context"
	"crypto/tls"
	"flag"
	"fmt"
	"github.com/jianzi123/maas/internal/publisher"
	"io"
	"log"
	"net"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"
)

func run() error {
	path := flag.String("config", "", "explicit publisher configuration file")
	flag.Parse()
	config, err := publisher.Load(*path)
	if err != nil {
		return err
	}
	tlsConfig, err := config.TLS()
	if err != nil {
		return err
	}
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	runtime, err := config.Open(ctx)
	if err != nil {
		return err
	}
	defer runtime.Close()
	mux := http.NewServeMux()
	mux.HandleFunc("GET /healthz", func(w http.ResponseWriter, r *http.Request) { w.WriteHeader(http.StatusNoContent) })
	mux.HandleFunc("GET /readyz", func(w http.ResponseWriter, r *http.Request) {
		// SQL/process health does not prove real H1-H4/validation readiness.
		http.Error(w, "DependencyMissing", http.StatusServiceUnavailable)
	})
	mux.Handle("/", publisher.Handler{Control: runtime.Store, OperatorIdentity: config.OperatorIdentity})
	server := &http.Server{Handler: mux, TLSConfig: tlsConfig, ReadHeaderTimeout: 5 * time.Second, ReadTimeout: 15 * time.Second, WriteTimeout: 15 * time.Second, IdleTimeout: 30 * time.Second, MaxHeaderBytes: 16384, ErrorLog: log.New(io.Discard, "", 0)}
	listener, err := net.Listen("tcp", config.Listen)
	if err != nil {
		return publisher.ErrConfiguration
	}
	defer listener.Close()
	done := make(chan struct{})
	go func() {
		defer close(done)
		<-ctx.Done()
		shutdown, cancel := context.WithTimeout(context.Background(), 5*time.Second)
		defer cancel()
		_ = server.Shutdown(shutdown)
	}()
	err = server.Serve(tls.NewListener(listener, tlsConfig))
	stop()
	<-done
	if err == http.ErrServerClosed {
		return nil
	}
	return publisher.ErrConfiguration
}
func main() {
	if err := run(); err != nil {
		fmt.Fprintln(os.Stderr, "publisher unavailable")
		os.Exit(1)
	}
}
