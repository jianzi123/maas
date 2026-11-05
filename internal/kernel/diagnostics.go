package kernel

import (
	"context"
	"crypto/sha256"
	"database/sql"
	_ "embed"
	"encoding/hex"
	"encoding/json"
	"errors"
	"github.com/google/uuid"
	"github.com/santhosh-tekuri/jsonschema/v5"
	"strings"
	"time"
)

//go:embed schema/0003_usage_diagnostics.sql
var diagnosticMigration string

//go:embed schema/usage-diagnostic.schema.json
var diagnosticSchema string
var diagnosticValidator, diagnosticSchemaError = jsonschema.CompileString("usage-diagnostic.json", diagnosticSchema)

const maxUsageDiagnostics = 64
const maxUsageDiagnosticBytes = 4096

var ErrDiagnosticLimit = errors.New("diagnostic_limit")

type DiagnosticUsage struct {
	Input     *int64 `json:"input_tokens"`
	Output    *int64 `json:"output_tokens"`
	Total     *int64 `json:"total_tokens"`
	Cached    *int64 `json:"input_cached_tokens"`
	Reasoning *int64 `json:"reasoning_tokens"`
}

// Internal diagnostic_only data; never an accounting or closure receipt.
type UsageDiagnostic struct {
	Version     string           `json:"schema_version"`
	Type        string           `json:"record_type"`
	ID          string           `json:"diagnostic_id"`
	RequestID   string           `json:"request_id"`
	Owner       string           `json:"owner_instance_id"`
	Fence       int64            `json:"owner_fence"`
	Sequence    int64            `json:"sequence"`
	Observed    time.Time        `json:"observed_at"`
	SnapshotSHA string           `json:"snapshot_sha256"`
	Binding     map[string]any   `json:"invocation_binding"`
	Authority   string           `json:"authority"`
	Usage       *DiagnosticUsage `json:"usage"`
	Cause       *string          `json:"cause"`
}

func bytesSHA(b []byte) string { v := sha256.Sum256(b); return hex.EncodeToString(v[:]) }
func invocationBinding(s Snapshot) map[string]any {
	p, plan := s.Input.Profile, s.Input.Plan
	purpose := purposeOf(s.Input)
	return map[string]any{"model_release_uid": p.CRUID, "model_release_namespace": p.Namespace, "model_release_name": p.Name, "model_release_generation": p.Binding.Generation, "release_revision": p.Binding.Revision, "publication_id": p.Binding.PublicationID, "activation_epoch": p.Binding.Epoch, "route_binding_sha256": p.RouteDigest, "admission_purpose": purpose, "price_snapshot_id": plan.PriceID, "price_version": plan.PriceVersion}
}
func migrateDiagnostics(ctx context.Context, db *sql.DB) error {
	c, err := db.Conn(ctx)
	if err != nil {
		return sanitize(err)
	}
	defer c.Close()
	var locked int
	if err = c.QueryRowContext(ctx, "SELECT GET_LOCK(CONCAT('maas-kernel:',DATABASE()),0)").Scan(&locked); err != nil || locked != 1 {
		return ErrBusy
	}
	defer c.ExecContext(context.Background(), "SELECT RELEASE_LOCK(CONCAT('maas-kernel:',DATABASE()))")
	want := bytesSHA([]byte(diagnosticMigration))
	var digest, state string
	err = c.QueryRowContext(ctx, "SELECT sha256,state FROM kernel_schema_migrations WHERE version=3").Scan(&digest, &state)
	if err == nil {
		if digest != want {
			return ErrConflict
		}
		if state == "Applied" {
			return nil
		}
	} else if errors.Is(err, sql.ErrNoRows) {
		var n int
		if err = c.QueryRowContext(ctx, "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=DATABASE() AND table_name IN ('request_snapshot_digests','request_usage_diagnostics')").Scan(&n); err != nil {
			return sanitize(err)
		}
		if n != 0 {
			return ErrConflict
		}
		if _, err = c.ExecContext(ctx, "INSERT INTO kernel_schema_migrations VALUES(3,?,'Applying')", want); err != nil {
			return sanitize(err)
		}
	} else {
		return sanitize(err)
	}
	for _, q := range strings.Split(diagnosticMigration, ";") {
		if q = strings.TrimSpace(q); q != "" {
			if _, err = c.ExecContext(ctx, q); err != nil {
				return sanitize(err)
			}
		}
	}
	_, err = c.ExecContext(ctx, "UPDATE kernel_schema_migrations SET state='Applied' WHERE version=3 AND sha256=?", want)
	return sanitize(err)
}

// Legacy requests without the original admission-time digest fail closed.
func (s *Store) NewUsageDiagnostic(ctx context.Context, in Input) (UsageDiagnostic, error) {
	var d UsageDiagnostic
	snap, _, err := s.ReadRequest(ctx, in.RequestID)
	if err != nil {
		return d, err
	}
	if snap.Input.Owner != in.Owner || hash(snap.Input) != hash(in) {
		return d, ErrConflict
	}
	var digest string
	if err = s.db.QueryRowContext(ctx, "SELECT snapshot_sha256 FROM request_snapshot_digests WHERE request_id=?", in.RequestID).Scan(&digest); err != nil {
		return d, sanitize(err)
	}
	return UsageDiagnostic{Version: "0.1-draft.1", RequestID: in.RequestID, Owner: in.Owner, Fence: snap.OwnerFence, SnapshotSHA: digest, Binding: invocationBinding(snap), Authority: "diagnostic_only"}, nil
}
func validateDiagnostic(d UsageDiagnostic) ([]byte, error) {
	b, err := json.Marshal(d)
	if err != nil || len(b) > maxUsageDiagnosticBytes || diagnosticSchemaError != nil {
		return nil, ErrConflict
	}
	var v any
	if json.Unmarshal(b, &v) != nil || diagnosticValidator.Validate(v) != nil {
		return nil, ErrConflict
	}
	if d.Usage != nil {
		u := Usage{Input: d.Usage.Input, Output: d.Usage.Output, Total: d.Usage.Total, Cached: d.Usage.Cached, Reasoning: d.Usage.Reasoning, Source: "upstream"}
		if _, _, _, err := actualUsage(u, nil); err != nil {
			return nil, ErrConflict
		}
	}
	return b, nil
}
func (s *Store) AppendUsageDiagnostic(ctx context.Context, d UsageDiagnostic) error {
	b, err := validateDiagnostic(d)
	if err != nil {
		return err
	}
	return s.tx(ctx, func(tx *sql.Tx) error {
		if _, err := s.guard(ctx, tx, "FOR SHARE NOWAIT"); err != nil {
			return err
		}
		snap, _, _, err := s.lockRequest(ctx, tx, d.RequestID)
		if err != nil {
			return err
		}
		var digest string
		if err = tx.QueryRowContext(ctx, "SELECT snapshot_sha256 FROM request_snapshot_digests WHERE request_id=?", d.RequestID).Scan(&digest); err != nil {
			return err
		}
		if snap.Input.Owner != d.Owner || snap.OwnerFence != d.Fence || digest != d.SnapshotSHA || hash(invocationBinding(snap)) != hash(d.Binding) {
			return ErrConflict
		}
		var old string
		err = tx.QueryRowContext(ctx, "SELECT record_sha256 FROM request_usage_diagnostics WHERE request_id=? AND owner_fence=? AND sequence=?", d.RequestID, d.Fence, d.Sequence).Scan(&old)
		if err == nil {
			if old == bytesSHA(b) {
				return nil
			}
			return ErrConflict
		}
		if !errors.Is(err, sql.ErrNoRows) {
			return err
		}
		var count, last int64
		if err = tx.QueryRowContext(ctx, "SELECT COUNT(*) FROM request_usage_diagnostics WHERE request_id=?", d.RequestID).Scan(&count); err != nil {
			return err
		}
		if count >= maxUsageDiagnostics || (d.Type == "receipt" && count >= maxUsageDiagnostics-1) {
			return ErrDiagnosticLimit
		}
		if err = tx.QueryRowContext(ctx, "SELECT COALESCE(MAX(sequence),0) FROM request_usage_diagnostics WHERE request_id=? AND owner_fence=?", d.RequestID, d.Fence).Scan(&last); err != nil {
			return err
		}
		if d.Sequence != last+1 {
			return ErrConflict
		}
		_, err = tx.ExecContext(ctx, "INSERT INTO request_usage_diagnostics(request_id,owner_fence,sequence,diagnostic_id,record_sha256,record_json) VALUES(?,?,?,?,?,?)", d.RequestID, d.Fence, d.Sequence, d.ID, bytesSHA(b), b)
		return err
	})
}

// Internal primary read. Public API consumers must keep their existing shapes.
func (s *Store) ReadUsageDiagnostics(ctx context.Context, id string) ([]UsageDiagnostic, error) {
	if !validUUID(id) {
		return nil, ErrConflict
	}
	rows, err := s.db.QueryContext(ctx, "SELECT record_sha256,record_json FROM request_usage_diagnostics WHERE request_id=? ORDER BY owner_fence,sequence LIMIT 65", id)
	if err != nil {
		return nil, sanitize(err)
	}
	defer rows.Close()
	out := []UsageDiagnostic{}
	for rows.Next() {
		var digest string
		var b []byte
		var d UsageDiagnostic
		if rows.Scan(&digest, &b) != nil || json.Unmarshal(b, &d) != nil {
			return nil, ErrUnavailable
		}
		canonical, err := validateDiagnostic(d)
		if err != nil || bytesSHA(canonical) != digest || d.RequestID != id || len(out) >= maxUsageDiagnostics {
			return nil, ErrUnavailable
		}
		out = append(out, d)
	}
	return out, sanitize(rows.Err())
}

type relayDiagnostics struct {
	store    *Store
	input    Input
	base     *UsageDiagnostic
	sequence int64
	seen     bool
}

func (r *relayDiagnostics) append(kind string, usage *Usage, cause string) error {
	observed := time.Now().UTC()
	ctx, done := context.WithTimeout(context.Background(), 5*time.Second)
	defer done()
	if r.base == nil {
		d, err := r.store.NewUsageDiagnostic(ctx, r.input)
		if err != nil {
			return err
		}
		r.base = &d
	}
	d := *r.base
	d.Sequence, d.Type, d.Observed = r.sequence+1, kind, observed
	d.ID = uuid.NewSHA1(uuid.NameSpaceOID, []byte(d.RequestID+"/diagnostic/"+decimal(d.Fence)+"/"+decimal(d.Sequence))).String()
	if usage != nil {
		d.Usage = &DiagnosticUsage{usage.Input, usage.Output, usage.Total, usage.Cached, usage.Reasoning}
	}
	if cause != "" {
		d.Cause = ptr(cause)
	}
	err := r.store.AppendUsageDiagnostic(ctx, d)
	if errors.Is(err, ErrCommitUnknown) {
		records, readErr := r.store.ReadUsageDiagnostics(ctx, d.RequestID)
		if readErr == nil {
			for _, old := range records {
				if old.ID == d.ID && hash(old) == hash(d) {
					err = nil
					break
				}
			}
		}
	}
	if err == nil {
		r.sequence++
		if usage != nil {
			r.seen = true
		}
	}
	return err
}
