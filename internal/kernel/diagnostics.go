package kernel

import (
	"bytes"
	"context"
	"database/sql"
	_ "embed"
	"encoding/json"
	"errors"
	"github.com/jianzi123/maas/internal/protocol"
	"time"
)

//go:embed schema/0003_diagnostics.sql
var diagnosticMigration string
var ErrDiagnosticLimit = errors.New("diagnostic_limit")

type DiagnosticPolicy struct {
	MaxRecords, MaxBytes int
	RetentionRef         string
}

// DiagnosticReader needs only the diagnostic SELECT role, never a platform Key
// pepper, publisher authority or accounting write privileges.
type DiagnosticReader struct{ store *Store }

func NewDiagnosticReader(db *sql.DB) (*DiagnosticReader, error) {
	if db == nil {
		return nil, ErrUnavailable
	}
	return &DiagnosticReader{store: &Store{db: db}}, nil
}
func (r *DiagnosticReader) Read(ctx context.Context, id string) ([]Diagnostic, error) {
	if !validUUID(id) {
		return nil, ErrPolicy
	}
	return r.store.ReadDiagnostics(ctx, id)
}

func (s *Store) ConfigureDiagnostics(ctx context.Context, p DiagnosticPolicy) error {
	if p.MaxRecords < 2 || p.MaxRecords > 4096 || p.MaxBytes < 16384 || p.MaxBytes > 16<<20 || len(p.RetentionRef) == 0 || len(p.RetentionRef) > 128 {
		return ErrPolicy
	}
	return s.tx(ctx, func(tx *sql.Tx) error {
		if _, e := s.guard(ctx, tx, "FOR UPDATE NOWAIT"); e != nil {
			return e
		}
		_, e := tx.ExecContext(ctx, "INSERT INTO diagnostic_policy VALUES(1,?,?,?)", p.MaxRecords, p.MaxBytes, p.RetentionRef)
		return e
	})
}

type DiagnosticCounts struct {
	Input     *int64 `json:"input_tokens"`
	Output    *int64 `json:"output_tokens"`
	Total     *int64 `json:"total_tokens"`
	Cached    *int64 `json:"input_cached_tokens"`
	Reasoning *int64 `json:"reasoning_tokens"`
}
type Diagnostic struct {
	Version      string            `json:"schema_version"`
	Type         string            `json:"record_type"`
	ID           string            `json:"diagnostic_id"`
	RequestID    string            `json:"request_id"`
	Owner        string            `json:"owner_instance_id"`
	Fence        int64             `json:"owner_fence"`
	Sequence     int64             `json:"sequence"`
	Observed     time.Time         `json:"observed_at"`
	SnapshotHash string            `json:"snapshot_sha256"`
	Binding      any               `json:"invocation_binding"`
	Authority    string            `json:"authority"`
	Usage        *DiagnosticCounts `json:"usage"`
	Cause        *string           `json:"cause"`
}

func (s *Store) DiagnosticBinding(ctx context.Context, request, owner string) (Snapshot, string, error) {
	var snap Snapshot
	var digest string
	e := s.readView(ctx, func(tx *sql.Tx, _ time.Time) error {
		var b []byte
		var current string
		var fence int64
		e := tx.QueryRowContext(ctx, "SELECT r.snapshot_json,r.owner_id,r.owner_fence,d.snapshot_sha256 FROM generation_requests r JOIN request_snapshot_digests d ON d.request_id=r.request_id WHERE r.request_id=?", request).Scan(&b, &current, &fence, &digest)
		if e != nil {
			return e
		}
		if current != owner || json.Unmarshal(b, &snap) != nil {
			return ErrConflict
		}
		snap.OwnerFence = fence
		return nil
	})
	return snap, digest, e
}
func canonicalDiagnostic(d Diagnostic) ([]byte, error) {
	if protocol.Validate("Diagnostic", d) != nil {
		return nil, ErrConflict
	}
	b, _ := json.Marshal(d)
	return protocol.Canonical(b)
}

// AppendDiagnostic never writes business accounting or authorizes generation.
// Receipt calls happen BEFORE forwarding the frame. Termination is independent.
func (s *Store) AppendDiagnostic(ctx context.Context, d Diagnostic) error {
	b, e := canonicalDiagnostic(d)
	if e != nil {
		return e
	}
	if len(b) > 8192 {
		return ErrDiagnosticLimit
	}
	e = s.tx(ctx, func(tx *sql.Tx) error {
		if _, e := s.guard(ctx, tx, "FOR UPDATE NOWAIT"); e != nil {
			return e
		}
		var original []byte
		var owner, digest string
		var fence int64
		e := tx.QueryRowContext(ctx, "SELECT r.snapshot_json,r.owner_id,r.owner_fence,h.snapshot_sha256 FROM generation_requests r JOIN request_snapshot_digests h ON h.request_id=r.request_id WHERE r.request_id=? FOR SHARE NOWAIT", d.RequestID).Scan(&original, &owner, &fence, &digest)
		if e != nil {
			return e
		}
		if owner != d.Owner || fence != d.Fence || digest != d.SnapshotHash {
			return ErrConflict
		}
		var snap Snapshot
		if json.Unmarshal(original, &snap) != nil {
			return ErrUnavailable
		}
		binding := requestProjection(snap, "in_progress", nil)["invocation_binding"]
		if hash(binding) != hash(d.Binding) {
			return ErrConflict
		}
		t, e := now(ctx, tx)
		if e != nil {
			return e
		}
		if d.Observed.Before(snap.Input.Received) || d.Observed.After(t) {
			return ErrConflict
		}
		if d.Usage != nil {
			u := Usage{Input: d.Usage.Input, Output: d.Usage.Output, Total: d.Usage.Total, Cached: d.Usage.Cached, Reasoning: d.Usage.Reasoning}
			if _, _, _, e = actualUsage(u, nil); e != nil {
				return e
			}
		}
		var previous []byte
		e = tx.QueryRowContext(ctx, "SELECT record_bytes FROM request_usage_diagnostics WHERE request_id=? AND owner_fence=? AND sequence=?", d.RequestID, d.Fence, d.Sequence).Scan(&previous)
		if e == nil {
			if bytes.Equal(b, previous) {
				return nil
			}
			return ErrConflict
		}
		if !errors.Is(e, sql.ErrNoRows) {
			return e
		}
		var last int64
		if e = tx.QueryRowContext(ctx, "SELECT COALESCE(MAX(sequence),0) FROM request_usage_diagnostics WHERE request_id=? AND owner_fence=?", d.RequestID, d.Fence).Scan(&last); e != nil {
			return e
		}
		if d.Sequence != last+1 {
			return ErrConflict
		}
		var limit, byteLimit int
		var ref string
		if e = tx.QueryRowContext(ctx, "SELECT max_records,max_bytes,retention_policy_ref FROM diagnostic_policy WHERE id=1").Scan(&limit, &byteLimit, &ref); e != nil || ref == "" {
			return ErrUnavailable
		}
		var count, size int64
		if e = tx.QueryRowContext(ctx, "SELECT COUNT(*),COALESCE(SUM(OCTET_LENGTH(record_bytes)),0) FROM request_usage_diagnostics WHERE request_id=?", d.RequestID).Scan(&count, &size); e != nil {
			return e
		}
		if count >= int64(limit) || size+int64(len(b)) > int64(byteLimit) {
			return ErrDiagnosticLimit
		}
		if d.Type == "receipt" && (count >= int64(limit-1) || size+int64(len(b))+8192 > int64(byteLimit)) {
			return ErrDiagnosticLimit
		}
		_, e = tx.ExecContext(ctx, "INSERT INTO request_usage_diagnostics(request_id,owner_fence,sequence,diagnostic_id,payload_sha256,record_bytes) VALUES(?,?,?,?,?,?)", d.RequestID, d.Fence, d.Sequence, d.ID, protocol.Digest(b), b)
		return e
	})
	if errors.Is(e, ErrCommitUnknown) {
		confirmed, readErr := s.ReadDiagnostic(ctx, d.RequestID, d.Fence, d.Sequence)
		if readErr == nil {
			stored, _ := canonicalDiagnostic(confirmed)
			if bytes.Equal(stored, b) {
				return nil
			}
		}
	}
	return e
}
func (s *Store) ReadDiagnostic(ctx context.Context, id string, fence, sequence int64) (Diagnostic, error) {
	var d Diagnostic
	var b []byte
	e := s.db.QueryRowContext(ctx, "SELECT record_bytes FROM request_usage_diagnostics WHERE request_id=? AND owner_fence=? AND sequence=?", id, fence, sequence).Scan(&b)
	if e != nil {
		return d, sanitizeView(e)
	}
	if json.Unmarshal(b, &d) != nil {
		return d, ErrUnavailable
	}
	return d, nil
}
func (s *Store) ReadDiagnostics(ctx context.Context, id string) ([]Diagnostic, error) {
	out := []Diagnostic{}
	e := s.readView(ctx, func(tx *sql.Tx, _ time.Time) error {
		rows, e := tx.QueryContext(ctx, "SELECT record_bytes FROM request_usage_diagnostics WHERE request_id=? ORDER BY owner_fence,sequence", id)
		if e != nil {
			return e
		}
		defer rows.Close()
		for rows.Next() {
			var b []byte
			var d Diagnostic
			if rows.Scan(&b) != nil || json.Unmarshal(b, &d) != nil {
				return ErrUnavailable
			}
			out = append(out, d)
		}
		return rows.Err()
	})
	return out, e
}
