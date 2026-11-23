//go:build localworkbench

package main

import (
	"context"
	"crypto/x509"
	"database/sql"
	"encoding/json"
	"encoding/pem"
	"github.com/go-sql-driver/mysql"
	"github.com/jianzi123/maas/internal/gateway"
	"github.com/jianzi123/maas/internal/installation"
	"github.com/jianzi123/maas/internal/kernel"
	"github.com/jianzi123/maas/internal/release/mysqlstore"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

type fixtureRegistry struct{ revoked bool }

func (f *fixtureRegistry) Check(context.Context, string, string, string, string, int64) error {
	if f.revoked {
		return gateway.ErrDependency
	}
	return nil
}

type fixtureSecretReader struct{}

func (fixtureSecretReader) Read(context.Context, gateway.SecretRef) (gateway.SecretValue, error) {
	return gateway.SecretValue{}, gateway.ErrDependency
}
func TestInstallationComposition(t *testing.T) {
	socket := os.Getenv("MAAS_MYSQL_TEST_SOCKET")
	if socket == "" {
		t.Skip("owned temporary MySQL required")
	}
	if os.Getenv("MAAS_DISPOSABLE_MYSQL") != "1" || !strings.HasPrefix(socket, "/tmp/maas11-mysql.") {
		t.Fatal("owned test server required")
	}
	directory, err := os.MkdirTemp("/tmp", "maas-workbench.")
	if err != nil {
		t.Fatal(err)
	}
	defer os.RemoveAll(directory)
	linked := filepath.Join(directory, "mysql.sock")
	if err = os.Symlink(socket, linked); err != nil {
		t.Fatal(err)
	}
	cfg := mysql.NewConfig()
	cfg.User = "root"
	cfg.Net = "unix"
	cfg.Addr = linked
	cfg.ParseTime = true
	installer, err := sql.Open("mysql", cfg.FormatDSN())
	if err != nil {
		t.Fatal(err)
	}
	defer installer.Close()
	if _, err = installer.Exec("CREATE DATABASE maas_workbench"); err != nil {
		t.Fatal(err)
	}
	defer installer.Exec("DROP DATABASE maas_workbench")
	cfg.DBName = "maas_workbench"
	db, err := sql.Open("mysql", cfg.FormatDSN())
	if err != nil {
		t.Fatal(err)
	}
	defer db.Close()
	ctx := context.Background()
	if err = kernel.Migrate(ctx, db); err != nil {
		t.Fatal(err)
	}
	if err = mysqlstore.Migrate(ctx, db); err != nil {
		t.Fatal(err)
	}
	connections, err := installLocalConnections(ctx, db, cfg, "../..")
	if err != nil {
		t.Fatal(err)
	}
	defer connections.Close()
	core, err := kernel.New(connections.Core, "local-workbench", []byte(strings.Repeat("x", 32)), nil, nil)
	if err != nil {
		t.Fatal(err)
	}
	write := func(name string, b []byte) string {
		p := filepath.Join(directory, name)
		if e := os.WriteFile(p, b, 0600); e != nil {
			t.Fatal(e)
		}
		return p
	}
	server := httptest.NewTLSServer(http.HandlerFunc(func(http.ResponseWriter, *http.Request) { t.Error("composition must not send generation") }))
	defer server.Close()
	pair := server.TLS.Certificates[0]
	keyBytes, err := x509.MarshalPKCS8PrivateKey(pair.PrivateKey)
	if err != nil {
		t.Fatal(err)
	}
	cert := pem.EncodeToMemory(&pem.Block{Type: "CERTIFICATE", Bytes: pair.Certificate[0]})
	c := installation.Config{Cluster: "local-workbench", PublisherDSNFile: write("publisher.dsn", []byte(connections.PublisherDSN)), SigningKeyFile: write("signer.key", []byte(strings.Repeat("k", 32))), Kid: "fixture", SignerOwner: "fixture-owner", Instance: "fixture-instance", Epoch: 1, Relay: kernel.RelayTLSFiles{Endpoint: server.URL, CAFile: write("ca.pem", cert), CertificateFile: write("client.pem", cert), KeyFile: write("client.key", pem.EncodeToMemory(&pem.Block{Type: "PRIVATE KEY", Bytes: keyBytes})), DialTimeout: time.Second, HeaderTimeout: time.Second, MaxBytes: 4096, MaxLine: 1024}}
	c.Credentials = []gateway.CredentialBinding{{Handle: "fixture-handle", PublicationID: "fixture-publication", InstanceID: c.Instance, Epoch: c.Epoch, Secret: gateway.SecretRef{Namespace: "maas-local", Name: "fixture", UID: "fixture-uid", ResourceVersion: "1", DataKey: "token"}}}
	encoded, err := json.Marshal(c)
	if err != nil {
		t.Fatal(err)
	}
	c, err = installation.LoadConfig(encoded)
	if err != nil {
		t.Fatal(err)
	}
	registry := &fixtureRegistry{}
	d := installation.Dependencies{Core: core, Registry: registry, SecretReader: fixtureSecretReader{}, Peer: func(*http.Request) bool { return false }}
	if _, e := installation.LoadConfig([]byte(`{"Instance":"a","Instance":"b"}`)); e == nil {
		t.Fatal("duplicate configuration accepted")
	}
	if _, e := installation.LoadConfig([]byte(`{"productionReady":true}`)); e == nil {
		t.Fatal("unknown readiness override accepted")
	}
	missing := d
	missing.Registry = nil
	if _, e := installation.Open(ctx, c, missing); e == nil {
		t.Fatal("missing registry accepted")
	}
	runtime, err := installation.Open(ctx, c, d)
	if err != nil {
		t.Fatal(err)
	}
	defer runtime.Close()
	handler, err := runtime.Authorizer("")
	if err != nil {
		t.Fatal(err)
	}
	rec := httptest.NewRecorder()
	handler.ServeHTTP(rec, httptest.NewRequest("POST", "/internal/v1/authorize", nil))
	if rec.Code != 503 {
		t.Fatal("unauthenticated peer accepted")
	}
	registry.revoked = true
	rec = httptest.NewRecorder()
	handler.ServeHTTP(rec, httptest.NewRequest("POST", "/internal/v1/authorize", nil))
	if rec.Code != 503 {
		t.Fatal("revoked registry accepted")
	}
	if _, e := runtime.Authorizer("not-an-intent"); e == nil {
		t.Fatal("unbound validation purpose accepted")
	}
	var requests int
	if db.QueryRow("SELECT COUNT(*) FROM generation_requests").Scan(&requests) != nil || requests != 0 {
		t.Fatal("failed assembly/auth created requests")
	}
	t.Log("real MySQL templates/default publisher role and relay TLS file construction; registry/SecretReader/peer are test substitutes, no production Ready or generation")
}
