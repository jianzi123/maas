package kernel

import (
	"context"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"
)

func TestMySQLToolsRelayOriginalLedger(t *testing.T) {
	for _, mode := range []string{"complete", "invalid_arguments", "missing_usage", "partial_cache", "eof", "source_error", "cancel"} {
		t.Run(mode, func(t *testing.T) {
			f := setupUsagePolicy(t, 1, &UsagePolicy{"deepseek-chat-tools/1", "final_only"}, &ToolCapability{"tools-v1", "deepseek-chat-tools/1", "non-thinking"})
			in := f.input(t)
			calls := 0
			ctx, cancel := context.WithCancel(context.Background())
			defer cancel()
			gateway := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				if _, e := f.core.Admit(r.Context(), f.gate, in); e != nil {
					w.WriteHeader(503)
					return
				}
				calls++
				frame := func(delta any, finish any, usage any) {
					b, _ := json.Marshal(map[string]any{"model": in.Profile.UpstreamModel, "choices": []any{map[string]any{"index": 0, "delta": delta, "finish_reason": finish}}, "usage": usage})
					wire := "data: " + string(b) + "\n\n"
					for i := 0; i < len(wire); i += 7 {
						end := i + 7
						if end > len(wire) {
							end = len(wire)
						}
						io.WriteString(w, wire[i:end])
						w.(http.Flusher).Flush()
					}
				}
				frame(map[string]any{"role": "assistant"}, nil, nil)
				fn := func(i int, id, name, args string) map[string]any {
					row := map[string]any{"index": i, "function": map[string]any{"arguments": args}}
					if id != "" {
						row["id"] = id
						row["type"] = "function"
						row["function"].(map[string]any)["name"] = name
					}
					return row
				}
				frame(map[string]any{"tool_calls": []any{fn(0, "supplier-1", "bounded_arithmetic", `{"a":6,`), fn(1, "supplier-2", "list_visible_models", `{}`)}}, nil, nil)
				if mode == "cancel" {
					select {
					case <-r.Context().Done():
					case <-time.After(2 * time.Second):
					}
					return
				}
				if mode == "eof" {
					return
				}
				if mode == "source_error" {
					io.WriteString(w, "data: {\"error\":{\"message\":\"private provider text\"}}\n\n")
					return
				}
				tail := `"b":7,"op":"multiply"}`
				if mode == "invalid_arguments" {
					tail = `"b":`
				}
				frame(map[string]any{"tool_calls": []any{fn(0, "", "", tail)}}, nil, nil)
				var usage any
				if mode != "missing_usage" {
					usage = map[string]any{"prompt_tokens": 12, "completion_tokens": 7, "total_tokens": 19, "prompt_cache_hit_tokens": 4, "prompt_cache_miss_tokens": 8, "completion_tokens_details": map[string]any{"reasoning_tokens": 0}}
				}
				if mode == "partial_cache" {
					usage.(map[string]any)["prompt_cache_hit_tokens"] = nil
					delete(usage.(map[string]any), "prompt_cache_hit_tokens")
				}
				frame(map[string]any{}, "tool_calls", usage)
				io.WriteString(w, "data: [DONE]\n\n")
			}))
			defer gateway.Close()
			relay := &Relay{core: f.core, endpoint: gateway.URL, client: gateway.Client(), maxBytes: 1 << 20, maxLine: 65536}
			rec := httptest.NewRecorder()
			var writer http.ResponseWriter = rec
			if mode == "cancel" {
				writer = &toolCancelWriter{ResponseWriter: rec, cancel: cancel}
			}
			e := relay.Forward(ctx, writer, RelayCall{Protocol: "tools-v1", Input: in, Body: []byte(`{"model":"controlled-upstream"}`), Ticket: "controlled-transport-only", PlanHeader: "controlled-transport-only", Stream: true})
			success := mode == "complete" || mode == "invalid_arguments" || mode == "partial_cache"
			if (e == nil) != success || calls != 1 {
				t.Fatal("wrong transport outcome", calls, e)
			}
			if strings.Contains(rec.Body.String(), "[DONE]") != success {
				t.Fatal("terminal emitted before accounting outcome")
			}
			if strings.Contains(rec.Body.String(), "private provider text") {
				t.Fatal("raw provider error leaked")
			}
			var requests, events int
			if e = f.db.QueryRow("SELECT COUNT(*) FROM generation_requests").Scan(&requests); e != nil {
				t.Fatal(e)
			}
			if e = f.db.QueryRow("SELECT COUNT(*) FROM usage_events").Scan(&events); e != nil || requests != 1 || events != 1 {
				t.Fatal("unique ledger", requests, events, e)
			}
			counter := readCounter(t, f, "tokens")
			if mode == "complete" || mode == "invalid_arguments" || mode == "partial_cache" {
				if counter.Known != "19" || counter.Held != "0" {
					t.Fatal("model usage lost before semantic batch validation", counter)
				}
				if mode == "partial_cache" {
					money := readCounter(t, f, "money")
					if money.Known != "0" || money.Held != "520000" {
						t.Fatal("unknown price classification was fabricated", money)
					}
				}
			} else if counter.Held != "140" || counter.Known != "0" {
				t.Fatal("unknown usage was released or fabricated", counter)
			}
		})
	}
}

type toolCancelWriter struct {
	http.ResponseWriter
	cancel context.CancelFunc
}

func (w *toolCancelWriter) Write(b []byte) (int, error) {
	n, e := w.ResponseWriter.Write(b)
	if strings.Contains(string(b), "tool_calls") {
		w.cancel()
	}
	return n, e
}
func (w *toolCancelWriter) Flush() {}
