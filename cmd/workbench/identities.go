//go:build localworkbench

package main

import (
	"context"
	"database/sql"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strings"

	"github.com/go-sql-driver/mysql"
	"github.com/google/uuid"
)

type localConnections struct {
	Core, History, Payload, Operations *sql.DB
	PublisherDSN                       string
	opened                             []*sql.DB
}

func (c *localConnections) Close() {
	for _, db := range c.opened {
		_ = db.Close()
	}
}

// Only the owned disposable workbench installs identities. Credentials stay in
// memory; repository templates are applied without adopting any target account.
func installLocalConnections(ctx context.Context, installer *sql.DB, cfg *mysql.Config, root string) (_ *localConnections, err error) {
	c := &localConnections{}
	defer func() {
		if err != nil {
			c.Close()
		}
	}()
	fail := func(step string, cause error) error {
		var driver *mysql.MySQLError
		if errors.As(cause, &driver) {
			return fmt.Errorf("temporary identity %s failed (mysql %d)", step, driver.Number)
		}
		return fmt.Errorf("temporary identity %s failed", step)
	}
	failed := fail("socket guard", nil)
	if cfg.DBName != "maas_workbench" || cfg.Net != "unix" || !strings.HasPrefix(cfg.Addr, "/tmp/maas-workbench.") {
		return nil, failed
	}
	for _, name := range []string{"release-permissions.sql", "kernel-permissions.sql", "controlapi-projections.sql"} {
		failed = fail("template "+name, nil)
		b, e := os.ReadFile(filepath.Join(root, "config", "mysql", name))
		if e != nil {
			return nil, failed
		}
		var lines []string
		for _, line := range strings.Split(string(b), "\n") {
			if !strings.HasPrefix(strings.TrimSpace(line), "--") {
				lines = append(lines, line)
			}
		}
		for _, q := range strings.Split(strings.Join(lines, "\n"), ";") {
			q = strings.ReplaceAll(strings.TrimSpace(q), "__MAAS_DATABASE__", "`maas_workbench`")
			if q != "" {
				if _, e = installer.ExecContext(ctx, q); e != nil {
					return nil, fail("template "+name, e)
				}
			}
		}
	}
	roles := [][]string{{"maas_kernel_runtime", "maas_release_reader"}, {"maas_release_history_reader"}, {"maas_history_payload_reader"}, {"maas_release_operations_runtime"}, {"maas_release_publisher"}}
	for i, names := range roles {
		failed = fail("user/default-role/ping index "+fmt.Sprint(i), nil)
		user := "local_" + strings.ReplaceAll(uuid.NewString(), "-", "")[:16]
		password := uuid.NewString()
		if _, e := installer.ExecContext(ctx, "CREATE USER '"+user+"'@'localhost' IDENTIFIED BY '"+password+"'"); e != nil {
			return nil, failed
		}
		for _, q := range []string{"GRANT " + strings.Join(names, ",") + " TO '" + user + "'@'localhost'", "SET DEFAULT ROLE " + strings.Join(names, ",") + " TO '" + user + "'@'localhost'"} {
			if _, e := installer.ExecContext(ctx, q); e != nil {
				return nil, failed
			}
		}
		local := cfg.Clone()
		local.User = user
		local.Passwd = password
		if i == 4 {
			c.PublisherDSN = local.FormatDSN()
			continue
		}
		db, e := sql.Open("mysql", local.FormatDSN())
		if e != nil {
			return nil, failed
		}
		c.opened = append(c.opened, db)
		if db.PingContext(ctx) != nil {
			return nil, failed
		}
		switch i {
		case 0:
			c.Core = db
		case 1:
			c.History = db
		case 2:
			c.Payload = db
		case 3:
			c.Operations = db
		}
	}
	return c, nil
}
