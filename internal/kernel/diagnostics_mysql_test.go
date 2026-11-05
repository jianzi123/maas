package kernel

import (
	"context"
	"database/sql"
	"encoding/json"
	"errors"
	"github.com/go-sql-driver/mysql"
	"github.com/google/uuid"
	"strings"
	"testing"
	"time"
)

func diagnosticInt(v int64) *int64 { return &v }

func diagnosticFor(t *testing.T, f *fixture, in Input) UsageDiagnostic {
	t.Helper()
	d, err := f.core.NewUsageDiagnostic(context.Background(), in)
	if err != nil {
		t.Fatal(err)
	}
	d.Type, d.ID, d.Sequence, d.Observed = "receipt", uuid.NewString(), 1, time.Now().UTC()
	d.Usage = &DiagnosticUsage{diagnosticInt(int64(12)), diagnosticInt(int64(7)), diagnosticInt(int64(19)), diagnosticInt(int64(4)), diagnosticInt(int64(3))}
	return d
}
func cloneDiagnostic(d UsageDiagnostic) UsageDiagnostic {
	b, _ := json.Marshal(d)
	var out UsageDiagnostic
	json.Unmarshal(b, &out)
	return out
}
func TestMySQLUsageDiagnosticStorage(t *testing.T) {
	ctx := context.Background()
	t.Run("original_digest_rebuild_and_exact_replay", func(t *testing.T) {
		f := setup(t, 1)
		in := f.input(t)
		snap := mustAdmit(t, f, in)
		d := diagnosticFor(t, f, in)
		b, _ := json.Marshal(snap)
		if d.SnapshotSHA != bytesSHA(b) {
			t.Fatal("not the original admission bytes")
		}
		if err := f.core.AppendUsageDiagnostic(ctx, d); err != nil {
			t.Fatal(err)
		}
		if err := f.core.AppendUsageDiagnostic(ctx, d); err != nil {
			t.Fatal("exact replay", err)
		}
		rebuilt, _ := New(f.db, "controlled-test", f.core.pepper, f.rate, f.proofs)
		rows, err := rebuilt.ReadUsageDiagnostics(ctx, in.RequestID)
		if err != nil || len(rows) != 1 || hash(rows[0]) != hash(d) {
			t.Fatal("durability", err, rows)
		}
		if c := readCounter(t, f, "tokens"); c.Reserved != "140" || c.Known != "0" {
			t.Fatal(c)
		}
		assertSQL(t, f.db, "SELECT COUNT(*) FROM usage_events", 0)
	})
	t.Run("conflict_snapshot_binding_and_owner_rejected", func(t *testing.T) {
		f := setup(t, 1)
		in := f.input(t)
		mustAdmit(t, f, in)
		d := diagnosticFor(t, f, in)
		if err := f.core.AppendUsageDiagnostic(ctx, d); err != nil {
			t.Fatal(err)
		}
		for _, mutate := range []func(*UsageDiagnostic){
			func(v *UsageDiagnostic) { v.Usage.Total = diagnosticInt(int64(20)) },
			func(v *UsageDiagnostic) { v.Owner = uuid.NewString(); v.Sequence = 2 },
			func(v *UsageDiagnostic) { v.Fence++; v.Sequence = 2 },
			func(v *UsageDiagnostic) { v.SnapshotSHA = strings.Repeat("f", 64); v.Sequence = 2 },
			func(v *UsageDiagnostic) { v.Binding["publication_id"] = uuid.NewString(); v.Sequence = 2 },
			func(v *UsageDiagnostic) { v.Binding["route_binding_sha256"] = strings.Repeat("f", 64); v.Sequence = 2 },
		} {
			bad := cloneDiagnostic(d)
			bad.ID = uuid.NewString()
			mutate(&bad)
			if err := f.core.AppendUsageDiagnostic(ctx, bad); !errors.Is(err, ErrConflict) {
				t.Fatal("accepted tamper", err)
			}
		}
		assertSQL(t, f.db, "SELECT COUNT(*) FROM request_usage_diagnostics", 1)
	})
	t.Run("recovery_rejects_old_fence_and_keeps_original_diagnostic", func(t *testing.T) {
		f := setup(t, 1)
		in := f.input(t)
		in.Expires = time.Now().UTC().Add(250 * time.Millisecond)
		in.Deadline = time.Now().UTC().Add(500 * time.Millisecond)
		mustAdmit(t, f, in)
		d := diagnosticFor(t, f, in)
		if err := f.core.AppendUsageDiagnostic(ctx, d); err != nil {
			t.Fatal(err)
		}
		<-time.After(time.Until(in.Deadline) + 10*time.Millisecond)
		if err := f.core.Recover(ctx, in.RequestID, uuid.NewString()); err != nil {
			t.Fatal(err)
		}
		var recovered []byte
		if err := f.db.QueryRow("SELECT event_json FROM usage_events WHERE request_id=?", in.RequestID).Scan(&recovered); err != nil {
			t.Fatal(err)
		}
		var event struct {
			Usage Usage `json:"usage"`
		}
		if json.Unmarshal(recovered, &event) != nil || event.Usage.Missing == nil || *event.Usage.Missing != "not_provided" {
			t.Fatal("recovery lost received-usage fact", string(recovered))
		}
		d.Sequence = 2
		d.ID = uuid.NewString()
		if err := f.core.AppendUsageDiagnostic(ctx, d); !errors.Is(err, ErrConflict) {
			t.Fatal("old fence", err)
		}
		rows, err := f.core.ReadUsageDiagnostics(ctx, in.RequestID)
		if err != nil || len(rows) != 1 {
			t.Fatal(err)
		}
		if c := readCounter(t, f, "tokens"); c.Held != "140" {
			t.Fatal(c)
		}
	})
	t.Run("diagnostic_and_terminal_commit_ack_unknown", func(t *testing.T) {
		f := setup(t, 1)
		in := f.input(t)
		snap := mustAdmit(t, f, in)
		d := diagnosticFor(t, f, in)
		connector, err := mysql.NewConnector(f.config)
		if err != nil {
			t.Fatal(err)
		}
		fault := &ackConnector{Connector: connector}
		db := sql.OpenDB(fault)
		defer db.Close()
		core, _ := New(db, "controlled-test", f.core.pepper, f.rate, f.proofs)
		fault.lose.Store(true)
		if err = core.AppendUsageDiagnostic(ctx, d); !errors.Is(err, ErrCommitUnknown) {
			t.Fatal(err)
		}
		if err = core.AppendUsageDiagnostic(ctx, d); err != nil {
			t.Fatal("same identity", err)
		}
		fin := finalFor(snap)
		fin.Usage = unavailableUsage("not_provided")
		fin.Result = "interrupted"
		fault.lose.Store(true)
		if err = core.Finalize(ctx, fin); !errors.Is(err, ErrCommitUnknown) {
			t.Fatal(err)
		}
		if err = core.Finalize(ctx, fin); err != nil {
			t.Fatal(err)
		}
		assertSQL(t, f.db, "SELECT COUNT(*) FROM request_usage_diagnostics", 1)
		assertSQL(t, f.db, "SELECT COUNT(*) FROM usage_events", 1)
		assertSQL(t, f.db, "SELECT SUM(finalized_total) FROM usage_daily", 1)
	})
	t.Run("bounded_append_and_reserved_termination", func(t *testing.T) {
		f := setup(t, 1)
		in := f.input(t)
		mustAdmit(t, f, in)
		d := diagnosticFor(t, f, in)
		for i := int64(1); i < maxUsageDiagnostics; i++ {
			d.Sequence = i
			d.ID = uuid.NewString()
			if err := f.core.AppendUsageDiagnostic(ctx, d); err != nil {
				t.Fatal(i, err)
			}
		}
		d.Sequence = maxUsageDiagnostics
		d.ID = uuid.NewString()
		if err := f.core.AppendUsageDiagnostic(ctx, d); !errors.Is(err, ErrDiagnosticLimit) {
			t.Fatal(err)
		}
		d.Type = "termination"
		d.Usage = nil
		d.Cause = ptr("diagnostic_limit")
		if err := f.core.AppendUsageDiagnostic(ctx, d); err != nil {
			t.Fatal(err)
		}
		d.Sequence++
		d.ID = uuid.NewString()
		if err := f.core.AppendUsageDiagnostic(ctx, d); !errors.Is(err, ErrDiagnosticLimit) {
			t.Fatal(err)
		}
		assertSQL(t, f.db, "SELECT COUNT(*) FROM request_usage_diagnostics", 64)
	})
	t.Run("migration_resume_checksum_and_legacy_digest_missing", func(t *testing.T) {
		f := setup(t, 1)
		in := f.input(t)
		mustAdmit(t, f, in)
		if _, err := f.db.Exec("DELETE FROM request_snapshot_digests WHERE request_id=?", in.RequestID); err != nil {
			t.Fatal(err)
		}
		if _, err := f.core.NewUsageDiagnostic(ctx, in); err == nil {
			t.Fatal("invented legacy digest")
		}
		if _, err := f.db.Exec("UPDATE kernel_schema_migrations SET state='Applying' WHERE version=3"); err != nil {
			t.Fatal(err)
		}
		if _, err := f.db.Exec("DROP TABLE request_usage_diagnostics"); err != nil {
			t.Fatal(err)
		}
		if err := Migrate(ctx, f.db); err != nil {
			t.Fatal("resume", err)
		}
		if _, err := f.db.Exec("UPDATE kernel_schema_migrations SET sha256=REPEAT('f',64) WHERE version=3"); err != nil {
			t.Fatal(err)
		}
		if err := Migrate(ctx, f.db); !errors.Is(err, ErrConflict) {
			t.Fatal("checksum", err)
		}
	})
	t.Run("late_diagnostic_does_not_change_financial_hold", func(t *testing.T) {
		f := setup(t, 1)
		in := f.input(t)
		snap := mustAdmit(t, f, in)
		d := diagnosticFor(t, f, in)
		if err := f.core.Finalize(ctx, finalFor(snap)); err != nil {
			t.Fatal(err)
		}
		if err := f.core.AppendUsageDiagnostic(ctx, d); err != nil {
			t.Fatal(err)
		}
		if err := f.core.Release(ctx, in.RequestID, uuid.NewString(), uuid.NewString()); err != nil {
			t.Fatal(err)
		}
		if c := readCounter(t, f, "tokens"); c.Held != "140" || c.Known != "0" {
			t.Fatal(c)
		}
		assertSQL(t, f.db, "SELECT COUNT(*) FROM usage_events", 1)
		assertSQL(t, f.db, "SELECT COUNT(*) FROM concurrency_slots WHERE state='FREE'", 1)
	})
	t.Run("runtime_append_only_and_reader_select_only", func(t *testing.T) {
		f := setup(t, 1)
		in := f.input(t)
		mustAdmit(t, f, in)
		d := diagnosticFor(t, f, in)
		for _, role := range []string{"runtime", "reader"} {
			username := "diag_" + strings.ReplaceAll(uuid.NewString(), "-", "")[:16]
			password := uuid.NewString()
			if _, err := f.db.Exec("CREATE USER '" + username + "'@'localhost' IDENTIFIED BY '" + password + "'"); err != nil {
				t.Fatal(err)
			}
			defer func() {
				if _, err := f.db.Exec("DROP USER '" + username + "'@'localhost'"); err != nil {
					t.Error(err)
				}
			}()
			grants := []string{"SELECT ON request_usage_diagnostics"}
			if role == "runtime" {
				grants = []string{"SELECT,INSERT ON request_usage_diagnostics", "SELECT ON kernel_guard", "SELECT,UPDATE ON generation_requests", "SELECT ON request_snapshot_digests"}
			}
			for _, grant := range grants {
				parts := strings.SplitN(grant, " ON ", 2)
				if _, err := f.db.Exec("GRANT " + parts[0] + " ON " + f.config.DBName + "." + parts[1] + " TO '" + username + "'@'localhost'"); err != nil {
					t.Fatal(err)
				}
			}
			cfg := f.config.Clone()
			cfg.User = username
			cfg.Passwd = password
			low, err := sql.Open("mysql", cfg.FormatDSN())
			if err != nil {
				t.Fatal(err)
			}
			core, _ := New(low, "controlled-test", f.core.pepper, f.rate, f.proofs)
			if role == "runtime" {
				if err := core.AppendUsageDiagnostic(ctx, d); err != nil {
					t.Fatal("runtime append", err)
				}
			}
			rows, err := core.ReadUsageDiagnostics(ctx, in.RequestID)
			if err != nil || len(rows) != 1 {
				t.Fatal("reader", err)
			}
			for _, q := range []string{"UPDATE request_usage_diagnostics SET sequence=2", "DELETE FROM request_usage_diagnostics", "UPDATE request_snapshot_digests SET snapshot_sha256=REPEAT('f',64)"} {
				if _, err := low.Exec(q); err == nil {
					t.Fatal("permission violation", role, q)
				}
			}
			low.Close()
		}
	})
}
