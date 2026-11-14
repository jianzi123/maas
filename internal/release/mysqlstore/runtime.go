package mysqlstore

import (
	"context"
	"database/sql"
	"errors"
	"strings"
	"time"

	"github.com/go-sql-driver/mysql"
)

// PublisherRuntime owns only its explicitly supplied connection. Provisioning,
// migrations, core credentials and real proof producers remain caller-owned.
type PublisherRuntime struct {
	Store *Store
	DB    *sql.DB
}

func (r *PublisherRuntime) Close() error { return r.DB.Close() }

// OpenPublisher never falls back to a core/operations connection and always
// enables same-transaction management completion. The default role must be the
// original narrow publisher role; this is not a full effective-grants audit.
func OpenPublisher(ctx context.Context, dsn, cluster string, k Kernel) (*PublisherRuntime, error) {
	unavailable := errors.New("explicit narrow publisher connection unavailable")
	if dsn == "" || k == nil {
		return nil, unavailable
	}
	cfg, err := mysql.ParseDSN(dsn)
	if err != nil || cfg.User == "" || strings.EqualFold(cfg.User, "root") || cfg.DBName == "" || !cfg.ParseTime || cfg.MultiStatements {
		return nil, unavailable
	}
	db, err := sql.Open("mysql", dsn)
	if err != nil {
		return nil, unavailable
	}
	ok := false
	defer func() {
		if !ok {
			_ = db.Close()
		}
	}()
	check, cancel := context.WithTimeout(ctx, 5*time.Second)
	defer cancel()
	var role string
	if db.QueryRowContext(check, "SELECT CURRENT_ROLE()").Scan(&role) != nil || role != "`maas_release_publisher`@`%`" {
		return nil, unavailable
	}
	store, err := New(db, cluster, k)
	if err != nil {
		return nil, unavailable
	}
	ok = true
	return &PublisherRuntime{Store: store.WithManagementOperations(), DB: db}, nil
}
