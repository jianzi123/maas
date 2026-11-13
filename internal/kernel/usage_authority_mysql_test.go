package kernel

import (
	"context"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

func TestMySQLUsageAuthority(t *testing.T) {
	for _, mode := range []string{"same_final", "conflicting_final", "conflicting_cached", "progress", "missing_policy", "progress_eof", "final_cancel"} {
		t.Run(mode, func(t *testing.T) {
			policy := &UsagePolicy{"controlled-adapter-v2", "final_only"}
			if strings.HasPrefix(mode, "progress") {
				policy.Mode = "cumulative_until_finish"
			}
			if mode == "missing_policy" {
				policy = nil
			}
			f := setupUsagePolicy(t, 1, policy)
			in := f.input(t)
			ctx, cancel := context.WithCancel(context.Background())
			defer cancel()
			calls := 0
			server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				calls++
				if _, err := f.core.Admit(r.Context(), f.gate, in); err != nil {
					w.WriteHeader(503)
					return
				}
				io.WriteString(w, "data: {\"choices\":[{\"delta\":{\"content\":\"answer\"}}]}\n\n")
				if mode == "progress" {
					io.WriteString(w, "data: {\"usage\":{\"prompt_tokens\":12,\"completion_tokens\":5,\"total_tokens\":17}}\n\n")
				}
				io.WriteString(w, diagnosticFrame)
				switch mode {
				case "same_final":
					io.WriteString(w, diagnosticFrame)
				case "conflicting_final":
					io.WriteString(w, strings.ReplaceAll(strings.ReplaceAll(diagnosticFrame, "\"completion_tokens\":7", "\"completion_tokens\":8"), "\"total_tokens\":19", "\"total_tokens\":20"))
				case "conflicting_cached":
					io.WriteString(w, strings.ReplaceAll(diagnosticFrame, "\"cached_tokens\":4", "\"cached_tokens\":5"))
				case "progress_eof":
					return
				}
				io.WriteString(w, "data: {\"choices\":[{\"index\":0,\"delta\":{},\"finish_reason\":\"stop\"}]}\n\ndata: [DONE]\n\n")
			}))
			defer server.Close()
			relay := &Relay{core: f.core, endpoint: server.URL, client: server.Client(), maxBytes: 65536, maxLine: 65536}
			out := httptest.NewRecorder()
			var writer http.ResponseWriter = out
			if mode == "final_cancel" {
				writer = &cancelAfterReceipt{header: http.Header{}, cancel: cancel, core: f.core, id: in.RequestID}
			}
			err := relay.Forward(ctx, writer, RelayCall{Input: in, Body: []byte(`{"model":"synthetic"}`), Stream: true})
			failed := mode == "conflicting_final" || mode == "conflicting_cached" || mode == "progress_eof" || mode == "final_cancel" || mode == "missing_policy"
			if (err != nil) != failed || calls != 1 {
				t.Fatalf("err=%v calls=%d", err, calls)
			}
			counter := readCounter(t, f, "tokens")
			if failed || mode == "missing_policy" {
				if counter.Known != "0" || counter.Held != "140" {
					t.Fatal("untrusted usage booked", counter)
				}
			} else if counter.Known != "19" {
				t.Fatal("final not booked exactly once", counter)
			}
			if failed && strings.Contains(out.Body.String(), "[DONE]") {
				t.Fatal("failure sent normal DONE")
			}
			records, err := f.core.ReadDiagnostics(context.Background(), in.RequestID)
			if err != nil || len(records) < 2 {
				t.Fatal("durable receipts missing", err)
			}
			if mode == "conflicting_final" || mode == "conflicting_cached" {
				if len(records) != 3 || records[2].Cause == nil || *records[2].Cause != "usage_conflict" {
					t.Fatal("conflicting receipt or cause lost", records)
				}
			}
			assertSQL(t, f.db, "SELECT COUNT(*) FROM usage_events", 1)
		})
	}
}
