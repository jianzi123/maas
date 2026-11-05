package kernel

import (
	"bytes"
	"context"
	"database/sql"
	"encoding/json"
	"errors"
	"github.com/go-sql-driver/mysql"
	"github.com/google/uuid"
	"github.com/jianzi123/maas/internal/protocol"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"
)

var diagnosticFrame = "data: {\"usage\":{\"prompt_tokens\":12,\"completion_tokens\":7,\"total_tokens\":19,\"prompt_tokens_details\":{\"cached_tokens\":4},\"completion_tokens_details\":{\"reasoning_tokens\":3}}}\n\n"

type usageFailWriter struct {
	header  http.Header
	core    *Store
	id      string
	durable bool
	buffer  bytes.Buffer
}

func (w *usageFailWriter) Header() http.Header { return w.header }
func (w *usageFailWriter) WriteHeader(int)     {}
func (w *usageFailWriter) Write(b []byte) (int, error) {
	if bytes.Contains(b, []byte(`"usage"`)) {
		rows, e := w.core.ReadDiagnostics(context.Background(), w.id)
		w.durable = e == nil && len(rows) > 0 && rows[0].Type == "receipt"
		return 0, io.ErrClosedPipe
	}
	return w.buffer.Write(b)
}
func TestMySQLDurableUsageRelay(t *testing.T) {
	for _, mode := range []string{"eof", "writer", "deadline_after_usage", "cancel_after_usage", "write_failure", "limit", "parse_invalid", "before_usage_eof", "parent_deadline_before_headers"} {
		t.Run(mode, func(t *testing.T) {
			f := setup(t, 1)
			in := f.input(t)
			ctx, cancel := context.WithCancel(context.Background())
			defer cancel()
			if mode == "deadline_after_usage" || mode == "parent_deadline_before_headers" {
				var done context.CancelFunc
				ctx, done = context.WithTimeout(ctx, 1200*time.Millisecond)
				defer done()
			}
			server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				_, _ = io.Copy(io.Discard, r.Body)
				if _, e := f.core.Admit(r.Context(), f.gate, in); e != nil {
					w.WriteHeader(503)
					return
				}
				if mode == "parent_deadline_before_headers" {
					select {
					case <-r.Context().Done():
					case <-time.After(3 * time.Second):
						t.Error("request cancellation did not reach controlled gateway")
					}
					return
				}
				if mode == "before_usage_eof" {
					io.WriteString(w, "data: {\"choices\":[]}\n\n")
					return
				}
				if mode == "write_failure" {
					_, _ = f.db.Exec("RENAME TABLE request_usage_diagnostics TO offline_diagnostics")
				}
				if mode == "limit" {
					_, _ = f.db.Exec("UPDATE diagnostic_policy SET max_records=2 WHERE id=1")
				}
				io.WriteString(w, diagnosticFrame)
				w.(http.Flusher).Flush()
				switch mode {
				case "deadline_after_usage":
					<-r.Context().Done()
				case "limit":
					io.WriteString(w, diagnosticFrame+"data: [DONE]\n\n")
				case "parse_invalid":
					io.WriteString(w, "data: {\"usage\":{\"prompt_tokens\":-1}}\n\n")
				}
			}))
			defer server.Close()
			recorder := httptest.NewRecorder()
			var writer http.ResponseWriter = recorder
			failing := &usageFailWriter{header: http.Header{}, core: f.core, id: in.RequestID}
			if mode == "writer" {
				writer = failing
			}
			if mode == "cancel_after_usage" {
				writer = &cancelAfterReceipt{header: http.Header{}, cancel: cancel}
			}
			relay := &Relay{core: f.core, endpoint: server.URL, client: server.Client(), maxBytes: 65536, maxLine: 65536}
			e := relay.Forward(ctx, writer, RelayCall{Input: in, Body: []byte(`{"model":"synthetic"}`), Stream: true})
			if e == nil || strings.Contains(recorder.Body.String(), "[DONE]") {
				t.Fatal("aborted stream reported success")
			}
			if mode == "write_failure" {
				_, _ = f.db.Exec("RENAME TABLE offline_diagnostics TO request_usage_diagnostics")
			}
			rows, e := f.core.ReadDiagnostics(context.Background(), in.RequestID)
			if e != nil {
				t.Fatal(e)
			}
			if mode == "write_failure" {
				if len(rows) != 0 || strings.Contains(recorder.Body.String(), `"usage"`) {
					t.Fatal("frame escaped failed receipt commit")
				}
			} else {
				expected := map[string]string{"eof": "eof", "writer": "client_write_error", "deadline_after_usage": "deadline_exceeded", "cancel_after_usage": "explicit_cancel", "limit": "diagnostic_limit", "parse_invalid": "parse_invalid", "before_usage_eof": "eof", "parent_deadline_before_headers": "deadline_exceeded"}[mode]
				last := rows[len(rows)-1]
				if last.Cause == nil || *last.Cause != expected {
					t.Fatal("termination", mode, last)
				}
				for _, d := range rows {
					if protocol.Validate("Diagnostic", d) != nil {
						t.Fatal("diagnostic schema", d)
					}
				}
				if mode != "before_usage_eof" && mode != "parent_deadline_before_headers" {
					d := rows[0]
					if d.Usage == nil || *d.Usage.Input != 12 || *d.Usage.Output != 7 || *d.Usage.Total != 19 || *d.Usage.Cached != 4 || *d.Usage.Reasoning != 3 || d.Authority != "diagnostic_only" {
						t.Fatal("lost counts", d)
					}
					if mode == "writer" && !failing.durable {
						t.Fatal("usage frame written before durable receipt")
					}
				}
			}
			var body []byte
			if e = f.db.QueryRow("SELECT event_json FROM usage_events WHERE request_id=?", in.RequestID).Scan(&body); e != nil {
				t.Fatal(e)
			}
			var event map[string]any
			_ = json.Unmarshal(body, &event)
			if protocol.Validate("Terminal", event) != nil {
				t.Fatal("3.0 schema")
			}
			usage := event["usage"].(map[string]any)
			if usage["total_tokens"] != nil {
				t.Fatal("diagnostic became final accounting", usage)
			}
			if len(rows) > 1 && strings.Contains(usage["missing_reason"].(string), "before_usage") {
				t.Fatal("received usage mislabeled", usage)
			}
			if mode == "deadline_after_usage" || mode == "parent_deadline_before_headers" {
				if event["result"] != "timed_out" {
					t.Fatal(event["result"])
				}
			}
			if c := readCounter(t, f, "tokens"); c.Held != "140" || c.Known != "0" {
				t.Fatal("held changed", c)
			}
			if c := readCounter(t, f, "money"); c.Held != "520000" || c.Known != "0" {
				t.Fatal(c)
			}
			assertSQL(t, f.db, "SELECT COUNT(*) FROM generation_requests", 1)
			assertSQL(t, f.db, "SELECT COUNT(*) FROM usage_events", 1)
			assertSQL(t, f.db, "SELECT SUM(finalized_total) FROM usage_daily", 1)
			rebuilt, _ := New(f.db, "controlled-test", f.core.pepper, f.rate, f.proofs)
			after, e := rebuilt.ReadDiagnostics(context.Background(), in.RequestID)
			if e != nil || len(after) != len(rows) {
				t.Fatal("Store reconstruction lost diagnostics", e)
			}
			if e = f.core.Release(context.Background(), in.RequestID, uuid.NewString(), uuid.NewString()); e != nil {
				t.Fatal(e)
			}
			if c := readCounter(t, f, "tokens"); c.Held != "140" {
				t.Fatal("slot release refunded diagnostic", c)
			}
		})
	}
}

type cancelAfterReceipt struct {
	header http.Header
	cancel context.CancelFunc
}

func (w *cancelAfterReceipt) Header() http.Header { return w.header }
func (w *cancelAfterReceipt) WriteHeader(int)     {}
func (w *cancelAfterReceipt) Write(b []byte) (int, error) {
	if bytes.Contains(b, []byte(`"usage"`)) {
		w.cancel()
	}
	return len(b), nil
}
func diagnosticExample(t *testing.T, core *Store, in Input, seq int64) Diagnostic {
	t.Helper()
	snap, digest, e := core.DiagnosticBinding(context.Background(), in.RequestID, in.Owner)
	if e != nil {
		t.Fatal(e)
	}
	a, b, c, d, r := int64(12), int64(7), int64(19), int64(4), int64(3)
	return Diagnostic{Version: "0.1-draft.1", Type: "receipt", ID: uuid.NewString(), RequestID: in.RequestID, Owner: in.Owner, Fence: snap.OwnerFence, Sequence: seq, Observed: time.Now().UTC(), SnapshotHash: digest, Binding: requestProjection(snap, "in_progress", nil)["invocation_binding"], Authority: "diagnostic_only", Usage: &DiagnosticCounts{&a, &b, &c, &d, &r}}
}
func TestMySQLDiagnosticReplayFenceAndACK(t *testing.T) {
	f := setup(t, 1)
	ctx := context.Background()
	in := f.input(t)
	snap := mustAdmit(t, f, in)
	d := diagnosticExample(t, f.core, in, 1)
	original, _ := json.Marshal(snap)
	if d.SnapshotHash != protocol.Digest(original) {
		t.Fatal("digest not captured at admission")
	}
	connector, _ := mysql.NewConnector(f.config)
	fault := &ackConnector{Connector: connector}
	db := sql.OpenDB(fault)
	defer db.Close()
	core, _ := New(db, "controlled-test", f.core.pepper, f.rate, f.proofs)
	fault.lose.Store(true)
	if e := core.AppendDiagnostic(ctx, d); e != nil {
		t.Fatal("confirmed diagnostic commit ACK", e)
	}
	if e := core.AppendDiagnostic(ctx, d); e != nil {
		t.Fatal("same payload retry", e)
	}
	conflict := d
	conflict.ID = uuid.NewString()
	if e := core.AppendDiagnostic(ctx, conflict); !errors.Is(e, ErrConflict) {
		t.Fatal("conflicting sequence", e)
	}
	fin := finalFor(snap)
	fin.Usage = unavailableUsage("not_provided")
	fault.lose.Store(true)
	if e := core.Finalize(ctx, fin); !errors.Is(e, ErrCommitUnknown) {
		t.Fatal(e)
	}
	if e := core.Finalize(ctx, fin); e != nil {
		t.Fatal(e)
	}
	late := diagnosticExample(t, core, in, 2)
	if e := core.AppendDiagnostic(ctx, late); e != nil {
		t.Fatal("late diagnostic", e)
	}
	if c := readCounter(t, f, "tokens"); c.Held != "140" {
		t.Fatal(c)
	}
	if _, e := f.db.Exec("UPDATE generation_requests SET owner_id=?,owner_fence=2 WHERE request_id=?", uuid.NewString(), in.RequestID); e != nil {
		t.Fatal(e)
	}
	if e := core.AppendDiagnostic(ctx, d); !errors.Is(e, ErrConflict) {
		t.Fatal("old fence accepted", e)
	}
	rows, e := core.ReadDiagnostics(ctx, in.RequestID)
	if e != nil || len(rows) != 2 {
		t.Fatal(rows, e)
	}
	assertSQL(t, f.db, "SELECT COUNT(*) FROM usage_events", 1)
}
