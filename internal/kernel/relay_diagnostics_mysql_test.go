package kernel

import (
	"context"
	"encoding/json"
	"errors"
	"github.com/google/uuid"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync/atomic"
	"testing"
	"time"
)

const diagnosticUsageFrame = "data: {\"usage\":{\"prompt_tokens\":12,\"completion_tokens\":7,\"total_tokens\":19,\"prompt_tokens_details\":{\"cached_tokens\":4},\"completion_tokens_details\":{\"reasoning_tokens\":3}}}\n\n"

func TestMySQLRelayUsageDiagnostics(t *testing.T) {
	for _, mode := range []string{"eof", "write_error", "cancel", "deadline", "partial", "duplicate", "conflict", "invalid", "receipt_write_failure", "termination_write_failure"} {
		t.Run(mode, func(t *testing.T) {
			f := setup(t, 1)
			in := f.input(t)
			ctx, cancel := context.WithCancel(context.Background())
			defer cancel()
			if mode == "deadline" {
				in.Expires = time.Now().UTC().Add(250 * time.Millisecond)
				in.Deadline = time.Now().UTC().Add(500 * time.Millisecond)
			}
			var calls atomic.Int32
			var offline atomic.Bool
			gateway := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				io.Copy(io.Discard, r.Body)
				calls.Add(1)
				if _, err := f.core.Admit(r.Context(), f.gate, in); err != nil {
					t.Error(err)
					w.WriteHeader(503)
					return
				}
				if mode == "receipt_write_failure" {
					if _, err := f.db.Exec("RENAME TABLE request_usage_diagnostics TO offline_request_usage_diagnostics"); err != nil {
						t.Error(err)
					}
					offline.Store(true)
				}
				frame := diagnosticUsageFrame
				if mode == "partial" {
					frame = "data: {\"usage\":{\"prompt_tokens\":12,\"completion_tokens\":7,\"prompt_tokens_details\":{\"cached_tokens\":4},\"completion_tokens_details\":{\"reasoning_tokens\":3}}}\n\n"
				}
				io.WriteString(w, frame)
				w.(http.Flusher).Flush()
				if mode == "duplicate" {
					io.WriteString(w, frame)
					return
				}
				if mode == "conflict" {
					io.WriteString(w, "data: {\"usage\":{\"prompt_tokens\":11,\"completion_tokens\":7,\"total_tokens\":18}}\n\n")
					return
				}
				if mode == "invalid" {
					io.WriteString(w, "data: {\"usage\":{\"prompt_tokens\":-1}}\n\n")
					return
				}
				if mode == "deadline" || mode == "cancel" || mode == "write_error" {
					select {
					case <-r.Context().Done():
					case <-time.After(3 * time.Second):
						t.Error("gateway cancellation missing")
					}
				}
			}))
			defer gateway.Close()
			recorder := httptest.NewRecorder()
			writer := &diagnosticInspectWriter{ResponseRecorder: recorder, inspect: func() {
				if mode == "receipt_write_failure" {
					return
				}
				rows, err := f.core.ReadUsageDiagnostics(context.Background(), in.RequestID)
				if err != nil || len(rows) != 1 || rows[0].Type != "receipt" {
					t.Error("receipt must be durable BEFORE forwarding", err, rows)
				}
				if mode == "termination_write_failure" {
					if _, err := f.db.Exec("RENAME TABLE request_usage_diagnostics TO offline_request_usage_diagnostics"); err != nil {
						t.Error(err)
					}
					offline.Store(true)
				}
			}, writeError: mode == "write_error"}
			if mode == "cancel" {
				writer.cancel = cancel
			}
			relay := &Relay{core: f.core, endpoint: gateway.URL, client: gateway.Client(), maxBytes: 1 << 20, maxLine: 65536}
			err := relay.Forward(ctx, writer, RelayCall{Input: in, Body: []byte("{}"), Stream: true})
			if err == nil || strings.Contains(recorder.Body.String(), "[DONE]") {
				t.Fatal("abnormal path reported success", err)
			}
			if calls.Load() != 1 {
				t.Fatal("generation replayed", calls.Load())
			}
			if offline.Load() {
				if _, err := f.core.ReadUsageDiagnostics(context.Background(), in.RequestID); err == nil {
					t.Fatal("unavailable read reported empty success")
				}
				if _, err := f.db.Exec("RENAME TABLE offline_request_usage_diagnostics TO request_usage_diagnostics"); err != nil {
					t.Fatal(err)
				}
			}
			rows, err := f.core.ReadUsageDiagnostics(context.Background(), in.RequestID)
			if err != nil {
				t.Fatal(err)
			}
			if mode == "receipt_write_failure" {
				if len(rows) != 0 || writer.inspected || strings.Contains(recorder.Body.String(), "\"usage\"") {
					t.Fatal("uncommitted receipt escaped")
				}
			} else {
				wantCount := 2
				if mode == "termination_write_failure" {
					wantCount = 1
				}
				if len(rows) != wantCount {
					t.Fatalf("diagnostics=%d want=%d", len(rows), wantCount)
				}
				u := rows[0].Usage
				if u == nil || u.Input == nil || *u.Input != 12 || u.Output == nil || *u.Output != 7 || u.Cached == nil || *u.Cached != 4 || u.Reasoning == nil || *u.Reasoning != 3 {
					t.Fatal("lost five counters", u)
				}
				if mode == "partial" {
					if u.Total != nil {
						t.Fatal("filled missing total")
					}
				} else if u.Total == nil || *u.Total != 19 {
					t.Fatal("lost total", u)
				}
				if rows[0].RequestID != in.RequestID || rows[0].Owner != in.Owner || rows[0].Fence != 1 || rows[0].Authority != "diagnostic_only" {
					t.Fatal("wrong binding")
				}
				if wantCount == 2 {
					cause := map[string]string{"eof": "eof", "write_error": "client_write_error", "cancel": "explicit_cancel", "deadline": "deadline_exceeded", "partial": "eof", "duplicate": "eof", "conflict": "usage_conflict", "invalid": "parse_invalid"}[mode]
					if rows[1].Cause == nil || *rows[1].Cause != cause {
						t.Fatal("wrong termination", rows[1].Cause, cause)
					}
				}
				rebuilt, _ := New(f.db, "controlled-test", f.core.pepper, f.rate, f.proofs)
				reread, err := rebuilt.ReadUsageDiagnostics(context.Background(), in.RequestID)
				if err != nil || hash(reread) != hash(rows) {
					t.Fatal("not durable after Store rebuild", err)
				}
			}
			var data []byte
			if err := f.db.QueryRow("SELECT event_json FROM usage_events WHERE request_id=?", in.RequestID).Scan(&data); err != nil {
				t.Fatal(err)
			}
			var event struct {
				Usage      Usage `json:"usage"`
				Accounting struct {
					Actual *string `json:"token_actual"`
					Cost   *string `json:"cost_actual_atomic"`
				} `json:"budget_accounting"`
				Result string `json:"result"`
			}
			if json.Unmarshal(data, &event) != nil {
				t.Fatal("invalid terminal")
			}
			if event.Usage.Input != nil || event.Usage.Output != nil || event.Usage.Total != nil || event.Usage.Cached != nil || event.Usage.Reasoning != nil || event.Usage.Missing == nil || *event.Usage.Missing != "not_provided" || event.Accounting.Actual != nil || event.Accounting.Cost != nil {
				t.Fatal("diagnostic became financial usage", string(data))
			}
			if mode == "deadline" && event.Result != "timed_out" {
				t.Fatal(event.Result)
			}
			for dim, want := range map[string]Counter{"requests": {Known: "1", Reserved: "0", Held: "0"}, "tokens": {Known: "0", Reserved: "0", Held: "140"}, "money": {Known: "0", Reserved: "0", Held: "520000"}} {
				if c := readCounter(t, f, dim); c != want {
					t.Fatal(dim, c)
				}
			}
			assertSQL(t, f.db, "SELECT COUNT(*) FROM generation_requests", 1)
			assertSQL(t, f.db, "SELECT COUNT(*) FROM usage_events", 1)
			assertSQL(t, f.db, "SELECT SUM(finalized_total) FROM usage_daily", 1)
			assertSQL(t, f.db, "SELECT COUNT(*) FROM concurrency_slots WHERE state='QUARANTINED'", 1)
			if err := f.core.Release(context.Background(), in.RequestID, uuid.NewString(), uuid.NewString()); err != nil {
				t.Fatal(err)
			}
			if c := readCounter(t, f, "tokens"); c.Held != "140" {
				t.Fatal("slot release refunded", c)
			}
			assertSQL(t, f.db, "SELECT COUNT(*) FROM usage_events", 1)
			assertSQL(t, f.db, "SELECT COUNT(*) FROM concurrency_slots WHERE state='FREE'", 1)
		})
	}
}

type diagnosticInspectWriter struct {
	*httptest.ResponseRecorder
	inspect    func()
	inspected  bool
	writeError bool
	cancel     context.CancelFunc
}

func (w *diagnosticInspectWriter) Write(b []byte) (int, error) {
	if strings.Contains(string(b), "\"usage\"") && !w.inspected {
		w.inspect()
		w.inspected = true
		if w.writeError {
			return 0, io.ErrClosedPipe
		}
		if w.cancel != nil {
			defer w.cancel()
		}
	}
	return w.ResponseRecorder.Write(b)
}
func (w *diagnosticInspectWriter) WriteString(s string) (int, error) { return w.Write([]byte(s)) }

// The child's first cause must survive a later change to the parent.
func TestRelayFirstContextTermination(t *testing.T) {
	parent, cancelParent := context.WithCancel(context.Background())
	defer cancelParent()
	child, done := context.WithDeadline(parent, time.Now().Add(-time.Second))
	defer done()
	cancelParent()
	result, _ := relayFailure(parent, child, child.Err(), "interrupted")
	if result != "timed_out" {
		t.Fatal("overwrote earlier deadline", result)
	}
	if !errors.Is(child.Err(), context.DeadlineExceeded) {
		t.Fatal(child.Err())
	}
}
