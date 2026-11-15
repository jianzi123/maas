//go:build localworkbench

package main

import (
	"context"
	"database/sql"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/go-sql-driver/mysql"
	"github.com/jianzi123/maas/internal/kernel"
	"github.com/jianzi123/maas/internal/release/mysqlstore"
)

func TestLocalRuntimeIdentities(t *testing.T) {
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
	for name, pool := range map[string]*sql.DB{"core": connections.Core, "history": connections.History, "payload": connections.Payload, "operations": connections.Operations} {
		var current, role string
		if pool.QueryRow("SELECT CURRENT_USER(),CURRENT_ROLE()").Scan(&current, &role) != nil || strings.HasPrefix(current, "root@") || role == "NONE" {
			t.Fatal(name, "did not activate independent identity")
		}
		t.Log(name, "independent identity/default role active")
	}
	core, err := kernel.New(connections.Core, "local-workbench", []byte(strings.Repeat("x", 32)), nil, nil)
	if err != nil {
		t.Fatal(err)
	}
	pub, err := mysqlstore.OpenPublisher(ctx, connections.PublisherDSN, "local-workbench", core)
	if err != nil {
		t.Fatal(err)
	}
	defer pub.Close()
	t.Log("actual local installer and publisher factory passed")
}
