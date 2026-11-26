package main

import (
	"context"
	"flag"
	"fmt"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/jianzi123/maas/internal/app"
)

func run(args []string) error {
	if len(args) == 0 {
		return fmt.Errorf("usage: maas-service migrate|reconcile-product-002|serve --config FILE")
	}
	flags := flag.NewFlagSet(args[0], flag.ContinueOnError)
	file := flags.String("config", "", "product configuration file")
	if flags.Parse(args[1:]) != nil || *file == "" {
		return app.ErrConfig
	}
	cfg, e := app.LoadConfig(*file)
	if e != nil {
		return e
	}
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	if args[0] == "migrate" || args[0] == "reconcile-product-002" {
		bounded, cancel := context.WithTimeout(ctx, 2*time.Minute)
		defer cancel()
		if args[0] == "reconcile-product-002" {
			e = app.ReconcileProduct002(bounded, cfg)
		} else {
			e = app.Migrate(bounded, cfg)
		}
		if e != nil {
			return e
		}
		fmt.Println("product migration operation completed")
		return nil
	}
	if args[0] != "serve" {
		return app.ErrConfig
	}
	runtime, e := app.Open(ctx, cfg)
	if e != nil {
		return e
	}
	defer runtime.Close()
	server := &http.Server{Addr: cfg.Listen, Handler: runtime.Handler, ReadHeaderTimeout: 5 * time.Second, ReadTimeout: 15 * time.Second, WriteTimeout: 30 * time.Second, IdleTimeout: 60 * time.Second, MaxHeaderBytes: 16384}
	done := make(chan error, 1)
	go func() { done <- server.ListenAndServe() }()
	fmt.Printf("maas-service starting listen=%s persistence=mysql\n", cfg.Listen)
	select {
	case e = <-done:
		if e != http.ErrServerClosed {
			return fmt.Errorf("product listener stopped")
		}
		return nil
	case <-ctx.Done():
	case <-runtime.Done():
	}
	shutdown, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	if e = server.Shutdown(shutdown); e != nil {
		_ = server.Close()
	}
	runtime.Close()
	listenErr := <-done
	if e != nil {
		return fmt.Errorf("product graceful shutdown timed out")
	}
	if listenErr != http.ErrServerClosed {
		return fmt.Errorf("product listener stopped")
	}
	return nil
}
func main() {
	if e := run(os.Args[1:]); e != nil {
		fmt.Fprintln(os.Stderr, e)
		os.Exit(1)
	}
}
