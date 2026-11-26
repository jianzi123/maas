package app

import (
	"context"
	"database/sql"
	"errors"

	"github.com/jianzi123/maas/internal/kernel"
)

type LedgerConfig struct {
	Diagnostics *DiagnosticConfig `json:"diagnostics,omitempty"`
	Revision    string            `json:"rate_revision"`
	Epoch       int64             `json:"initial_rate_epoch"`
	WindowMS    int64             `json:"window_ms"`
	GlobalLimit int64             `json:"global_limit"`
	KeyLimit    int64             `json:"key_limit"`
	Slots       int64             `json:"slots"`
}

func initializeLedger(ctx context.Context, db *sql.DB, c Config) error {
	var n int
	if e := db.QueryRowContext(ctx, "SELECT COUNT(*) FROM kernel_guard").Scan(&n); e != nil {
		return e
	}
	if n > 0 {
		var cluster string
		if e := db.QueryRowContext(ctx, "SELECT cluster_id FROM kernel_guard WHERE id=1").Scan(&cluster); e != nil || cluster != c.Cluster {
			return errors.New("ledger_cluster_conflict")
		}
		return nil
	}
	pepper, e := secret(c.Secrets.PepperFile, 32, 4096)
	if e != nil {
		return e
	}
	core, e := kernel.New(db, c.Cluster, pepper, nil, nil)
	if e != nil {
		return e
	}
	l := c.Ledger
	// Existing slots/budgets are never reset; Configure leaves Redis readiness
	// false until the original authenticated reconstruction completes.
	return core.Configure(ctx, kernel.RatePolicy{Revision: l.Revision, Epoch: l.Epoch, WindowMS: l.WindowMS, GlobalLimit: l.GlobalLimit, KeyLimit: l.KeyLimit}, l.Slots)
}
