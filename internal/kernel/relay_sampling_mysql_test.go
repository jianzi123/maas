package kernel

import (
	"context"
	"encoding/json"
	"github.com/google/uuid"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

type slowContentWriter struct {
	*httptest.ResponseRecorder
	fail bool
}

func (w *slowContentWriter) WriteString(s string) (int, error) { return w.Write([]byte(s)) }

func (w *slowContentWriter) Write(b []byte) (int, error) {
	if strings.Contains(string(b), `"content":"visible"`) {
		time.Sleep(60 * time.Millisecond)
		if w.fail {
			return 0, io.ErrClosedPipe
		}
	}
	return w.ResponseRecorder.Write(b)
}

func TestMySQLRelaySampling(t *testing.T) {
	samples := []RelaySample{}
	runSampler := NewRelaySampler("go-controlled-d1", uuid.NewString(), "working-tree-d1", 1)
	for _, mode := range []string{"content", "empty", "usage_only", "error_then_finish", "error_after_content", "raw_eof", "write_failure", "cancel", "timeout", "full_sampler"} {
		t.Run(mode, func(t *testing.T) {
			f := setup(t, 1)
			in := f.input(t)
			ctx, cancel := context.WithCancel(context.Background())
			defer cancel()
			if mode == "timeout" {
				var done context.CancelFunc
				ctx, done = context.WithTimeout(ctx, 1500*time.Millisecond)
				defer done()
			}
			sampler := runSampler
			defer func() {
				for {
					select {
					case <-sampler.Records():
					default:
						return
					}
				}
			}()
			if mode == "full_sampler" {
				sampler.offer(RelaySample{})
			}
			calls := 0
			server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				calls++
				if _, err := f.core.Admit(r.Context(), f.gate, in); err != nil {
					w.WriteHeader(503)
					return
				}
				io.WriteString(w, "data: {\"choices\":[{\"delta\":{\"role\":\"assistant\"}}]}\n\n")
				w.(http.Flusher).Flush()
				if mode == "cancel" || mode == "timeout" {
					time.Sleep(50 * time.Millisecond)
					if mode == "cancel" {
						cancel()
					}
					<-r.Context().Done()
					return
				}
				if mode == "raw_eof" {
					return
				}
				io.WriteString(w, "data: {\"choices\":[{\"delta\":{\"content\":\"\"}}]}\n\n")
				w.(http.Flusher).Flush()
				time.Sleep(35 * time.Millisecond)
				if mode != "empty" && mode != "usage_only" && mode != "error_then_finish" {
					io.WriteString(w, "data: {\"choices\":[{\"delta\":{\"content\":\"visible\"}}]}\n\n")
				}
				if mode == "error_then_finish" || mode == "error_after_content" {
					io.WriteString(w, "data: {\"error\":{\"message\":\"private-provider-body\"}}\n\n")
				}
				io.WriteString(w, diagnosticFrame)
				io.WriteString(w, "data: {\"choices\":[{\"delta\":{},\"finish_reason\":\"stop\"}]}\n\ndata: [DONE]\n\n")
			}))
			defer server.Close()
			relay := &Relay{core: f.core, endpoint: server.URL, client: server.Client(), maxBytes: 65536, maxLine: 65536, Sampler: sampler}
			writer := &slowContentWriter{ResponseRecorder: httptest.NewRecorder(), fail: mode == "write_failure"}
			err := relay.Forward(ctx, writer, RelayCall{Input: in, Body: []byte(`{"model":"synthetic"}`), Stream: true})
			failed := strings.HasPrefix(mode, "error_") || mode == "raw_eof" || mode == "write_failure" || mode == "cancel" || mode == "timeout"
			if (err != nil) != failed || calls != 1 {
				t.Fatalf("mode %s err=%v calls=%d", mode, err, calls)
			}
			if failed && strings.Contains(writer.Body.String(), "[DONE]") {
				t.Fatal("failure recovered success")
			}
			if strings.Contains(writer.Body.String(), "private-provider-body") {
				t.Fatal("provider error leaked")
			}
			if mode == "full_sampler" {
				if sampler.Dropped() != 1 {
					t.Fatal("sampling full not dropped")
				}
				return
			}
			s := <-sampler.Records()
			samples = append(samples, s)
			if s.ProtocolMS == nil {
				t.Fatal("role protocol event missing")
			}
			hasContent := mode == "content" || mode == "write_failure" || mode == "error_after_content"
			if (s.ContentMS != nil) != hasContent {
				t.Fatal("noncontent triggered first visible content", s)
			}
			if hasContent && (*s.ContentMS < *s.ProtocolMS+25) {
				t.Fatal("role/empty event became first content")
			}
			if mode == "content" {
				if s.WriteMS == nil || *s.WriteMS < *s.ContentMS+50 {
					t.Fatal("write completion not distinguished")
				}
			}
			if mode == "write_failure" && s.WriteMS != nil {
				t.Fatal("failed write marked successful")
			}
			var terminal map[string]any
			var raw []byte
			if e := f.db.QueryRow("SELECT event_json FROM usage_events WHERE request_id=?", in.RequestID).Scan(&raw); e != nil {
				t.Fatal(e)
			}
			json.Unmarshal(raw, &terminal)
			if hasContent {
				if terminal["first_chunk_ms"] == nil {
					t.Fatal("first_chunk lost")
				}
			} else if terminal["first_chunk_ms"] != nil {
				t.Fatal("no content fabricated first_chunk")
			}
			if failed {
				if c := readCounter(t, f, "tokens"); c.Held != "140" {
					t.Fatal("failed sample refunded budget", c)
				}
			}
			assertSQL(t, f.db, "SELECT COUNT(*) FROM usage_events", 1)
		})
	}
	if path := os.Getenv("MAAS_D1_SAMPLE_OUTPUT"); path != "" {
		if !filepath.IsAbs(path) {
			path = filepath.Join("..", "..", path)
		}
		b, e := json.MarshalIndent(map[string]any{"schema_version": "maas-go-relay-export-1.0", "evidence_kind": "controlled_go_http_mysql", "samples": samples, "missing_components": []string{"real_higress", "worker", "gpu", "client_receive", "cross_clock_calibration"}, "missing_identity": []string{"trace_id", "experiment_ref", "cell_id"}, "run_id": "go-controlled-d1", "instance_fixture": false, "export_id": uuid.NewString()}, "", "  ")
		if e != nil {
			t.Fatal(e)
		}
		if os.WriteFile(path, b, 0600) != nil {
			t.Fatal("export failed")
		}
	}
}
