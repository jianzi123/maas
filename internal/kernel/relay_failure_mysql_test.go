package kernel

import (
	"context"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync/atomic"
	"testing"
	"time"
)

// Only the gateway transport and admission proofs are fixtures. These checks
// read the real durable request, terminal event, budget and slot after failure.
func TestMySQLRelayFailureClassification(t *testing.T) {
	for _, tc := range []struct {
		name, trigger, result  string
		stream, headers, usage bool
	}{
		{"hard_deadline_before_headers", "hard", "timed_out", true, false, false},
		{"hard_deadline_after_chunk", "hard", "timed_out", true, true, false},
		{"parent_deadline_before_headers", "parent", "timed_out", true, false, false},
		{"parent_deadline_after_chunk", "parent", "timed_out", true, true, false},
		{"explicit_cancel_before_headers", "cancel", "cancelled", true, false, false},
		{"explicit_cancel_after_chunk", "cancel", "cancelled", true, true, false},
		{"eof_after_chunk", "eof", "interrupted", true, true, false},
		{"hard_deadline_after_usage", "hard", "timed_out", true, true, true},
		{"hard_deadline_during_write", "write", "timed_out", true, true, false},
		{"nonstream_hard_deadline_during_body", "hard", "timed_out", false, true, false},
		{"nonstream_parent_deadline_during_body", "parent", "timed_out", false, true, false},
		{"nonstream_cancel_during_body", "cancel", "cancelled", false, true, false},
	} {
		t.Run(tc.name, func(t *testing.T) {
			f := setup(t, 1)
			in := f.input(t)
			in.Expires = time.Now().UTC().Add(250 * time.Millisecond)
			in.Deadline = time.Now().UTC().Add(5 * time.Second)
			ctx, cancel := context.WithCancel(context.Background())
			defer cancel()
			if tc.trigger == "hard" || tc.trigger == "write" {
				in.Deadline = time.Now().UTC().Add(500 * time.Millisecond)
			}
			if tc.trigger == "parent" {
				var done context.CancelFunc
				ctx, done = context.WithTimeout(ctx, 500*time.Millisecond)
				defer done()
			}
			var calls atomic.Int32
			transportClosed := make(chan struct{})
			gateway := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				calls.Add(1)
				io.Copy(io.Discard, r.Body)
				if _, err := f.core.Admit(r.Context(), f.gate, in); err != nil {
					t.Error("admit", err)
					w.WriteHeader(http.StatusServiceUnavailable)
					return
				}
				if tc.headers {
					if tc.stream {
						io.WriteString(w, "data: {\"choices\":[{\"delta\":{\"content\":\"ok\"}}]}\n\n")
						if tc.usage {
							io.WriteString(w, "data: {\"usage\":{\"prompt_tokens\":12,\"completion_tokens\":7,\"total_tokens\":19}}\n\n")
						}
					} else {
						io.WriteString(w, `{"choices":[`)
					}
					w.(http.Flusher).Flush()
				}
				if tc.trigger == "cancel" && !(tc.stream && tc.headers) {
					cancel()
				}
				if tc.trigger != "eof" {
					select {
					case <-r.Context().Done():
					case <-time.After(3 * time.Second):
						t.Error("gateway did not observe cancellation")
					}
				}
				if tc.trigger == "write" {
					close(transportClosed)
				}
			}))
			defer gateway.Close()
			relay := &Relay{core: f.core, endpoint: gateway.URL, client: gateway.Client(), maxBytes: 1 << 20, maxLine: 65536}
			w := httptest.NewRecorder()
			var writer http.ResponseWriter = w
			if tc.trigger == "cancel" && tc.stream && tc.headers {
				writer = &cancelAfterChunkWriter{ResponseRecorder: w, cancel: cancel}
			}
			if tc.trigger == "write" {
				writer = &deadlineFailureWriter{ResponseRecorder: w, closed: transportClosed}
			}
			if err := relay.Forward(ctx, writer, RelayCall{Input: in, Body: []byte(`{"model":"synthetic","messages":[]}`), Stream: tc.stream}); err == nil {
				t.Fatal("transport failure returned success")
			}
			if strings.Contains(w.Body.String(), "[DONE]") {
				t.Fatal("failure emitted a normal DONE")
			}
			if calls.Load() != 1 {
				t.Fatalf("gateway dispatches=%d want=1", calls.Load())
			}
			if tc.usage && !strings.Contains(w.Body.String(), `"usage"`) {
				t.Fatal("usage chunk was not relayed before deadline")
			}
			_, state, err := f.core.ReadRequest(context.Background(), in.RequestID)
			if err != nil || state != tc.result {
				t.Fatalf("request state=%q want=%q err=%v", state, tc.result, err)
			}
			var data []byte
			if err := f.db.QueryRow("SELECT event_json FROM usage_events WHERE request_id=?", in.RequestID).Scan(&data); err != nil {
				t.Fatal(err)
			}
			var event struct {
				Result string `json:"result"`
				Code   string `json:"error_code"`
				First  *int64 `json:"first_chunk_ms"`
			}
			if err := json.Unmarshal(data, &event); err != nil {
				t.Fatal(err)
			}
			wantCode := map[string]string{"timed_out": "upstream_timeout", "cancelled": "client_cancelled", "interrupted": "owner_lost"}[tc.result]
			if event.Result != tc.result || event.Code != wantCode {
				t.Fatalf("terminal result=%q code=%q want=%q/%q", event.Result, event.Code, tc.result, wantCode)
			}
			if (event.First != nil) != (tc.stream && tc.headers) {
				t.Fatalf("first chunk=%v stream=%t headers=%t", event.First, tc.stream, tc.headers)
			}
			assertSQL(t, f.db, "SELECT COUNT(*) FROM usage_events WHERE request_id=?", 1, in.RequestID)
			assertSQL(t, f.db, "SELECT SUM(finalized_total) FROM usage_daily", 1)
			assertSQL(t, f.db, "SELECT COUNT(*) FROM concurrency_slots WHERE request_id=? AND state='QUARANTINED'", 1, in.RequestID)
			for dim, want := range map[string]Counter{
				"requests": {Known: "1", Reserved: "0", Held: "0"},
				"tokens":   {Known: "0", Reserved: "0", Held: "140"},
				"money":    {Known: "0", Reserved: "0", Held: "520000"},
			} {
				if got := readCounter(t, f, dim); got != want {
					t.Fatalf("%s counter=%+v want=%+v", dim, got, want)
				}
			}
		})
	}
}

type cancelAfterChunkWriter struct {
	*httptest.ResponseRecorder
	cancel context.CancelFunc
}

func (w *cancelAfterChunkWriter) Write(b []byte) (int, error) {
	n, err := w.ResponseRecorder.Write(b)
	w.cancel()
	return n, err
}

func (w *cancelAfterChunkWriter) WriteString(s string) (int, error) { return w.Write([]byte(s)) }

type deadlineFailureWriter struct {
	*httptest.ResponseRecorder
	closed <-chan struct{}
}

func (w *deadlineFailureWriter) Write([]byte) (int, error) {
	select {
	case <-w.closed:
		return 0, io.ErrClosedPipe
	case <-time.After(5 * time.Second):
		return 0, context.DeadlineExceeded
	}
}

func (w *deadlineFailureWriter) WriteString(s string) (int, error) { return w.Write([]byte(s)) }
