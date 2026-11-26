package app

import (
	"context"
	"database/sql"
	"errors"
	a "github.com/jianzi123/maas/internal/agentruntime"
	"github.com/jianzi123/maas/internal/kernel"
)

type DiagnosticConfig struct {
	MaxRecords   int    `json:"max_records"`
	MaxBytes     int    `json:"max_bytes"`
	RetentionRef string `json:"retention_policy_ref"`
}

func (p DiagnosticConfig) valid() bool {
	return p.MaxRecords >= 2 && p.MaxRecords <= 4096 && p.MaxBytes >= 16384 && p.MaxBytes <= 16<<20 && len(p.RetentionRef) > 0 && len(p.RetentionRef) <= 128
}
func readDiagnosticPolicy(ctx context.Context, db *sql.DB) (DiagnosticConfig, error) {
	var p DiagnosticConfig
	e := db.QueryRowContext(ctx, "SELECT max_records,max_bytes,retention_policy_ref FROM diagnostic_policy WHERE id=1").Scan(&p.MaxRecords, &p.MaxBytes, &p.RetentionRef)
	return p, e
}

// Existing installation-owned diagnostic policy is inserted once, never reset
// or changed silently by a process restart or runtime identity.
func initializeRelayDiagnostics(ctx context.Context, db *sql.DB, c Config) error {
	if c.Ledger.Diagnostics == nil {
		return nil
	}
	actual, e := readDiagnosticPolicy(ctx, db)
	if e == nil {
		if actual != *c.Ledger.Diagnostics {
			return errors.New("relay_diagnostic_policy_conflict")
		}
		return nil
	}
	if !errors.Is(e, sql.ErrNoRows) {
		return errors.New("relay_diagnostic_policy_unavailable")
	}
	pepper, e := secret(c.Secrets.PepperFile, 32, 4096)
	if e != nil {
		return e
	}
	defer func() {
		for i := range pepper {
			pepper[i] = 0
		}
	}()
	core, e := kernel.New(db, c.Cluster, pepper, nil, nil)
	if e != nil {
		return e
	}
	p := c.Ledger.Diagnostics
	if e = core.ConfigureDiagnostics(ctx, kernel.DiagnosticPolicy{MaxRecords: p.MaxRecords, MaxBytes: p.MaxBytes, RetentionRef: p.RetentionRef}); e != nil {
		return errors.New("relay_diagnostic_policy_unavailable")
	}
	return nil
}
func (m *Models) diagnosticReady(ctx context.Context) error {
	if len(m.Config.Models) == 0 {
		return nil
	}
	configured := m.Config.Ledger.Diagnostics
	if configured == nil || !configured.valid() {
		return a.NewFailure(503, "relay_diagnostic_policy_unavailable")
	}
	if m.DB == nil {
		return a.NewFailure(503, "relay_diagnostic_policy_unavailable")
	}
	actual, e := readDiagnosticPolicy(ctx, m.DB)
	if e != nil || actual != *configured {
		return a.NewFailure(503, "relay_diagnostic_policy_unavailable")
	}
	return nil
}
