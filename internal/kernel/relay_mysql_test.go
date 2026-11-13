package kernel

import (
	"context"
	"errors"
	"github.com/google/uuid"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"strings"
	"testing"
	"time"
)

func TestMySQLControlledRelay(t *testing.T) {
	for _, mode := range []string{"nonstream", "stream", "cumulative", "decreasing", "cancel", "missing_usage", "interrupted", "accounting_failure"} {
		t.Run(mode, func(t *testing.T) {
			f := setup(t, 1)
			in := f.input(t)
			called := 0
			// This HTTP server substitutes ONLY the Higress transport. Final admission,
			// request/slot/budget rows and terminal transaction all use production code.
			gateway := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				if r.Method != "POST" || r.URL.Path != "/v1/chat/completions" || r.Header.Get("Authorization") != "" {
					t.Error("unexpected request/credential forwarding")
					w.WriteHeader(403)
					return
				}
				if _, e := f.core.Admit(r.Context(), f.gate, in); e != nil {
					w.WriteHeader(503)
					return
				}
				called++
				if mode == "nonstream" {
					io.WriteString(w, `{"choices":[{"index":0,"message":{"role":"assistant","content":"ok"},"finish_reason":"stop"}],"usage":{"prompt_tokens":12,"completion_tokens":7,"total_tokens":19,"prompt_tokens_details":{"cached_tokens":4},"completion_tokens_details":{"reasoning_tokens":3}}}`)
					return
				}
				io.WriteString(w, "data: {\"choices\":[{\"delta\":{\"content\":\"ok\"}}]}\n\n")
				w.(http.Flusher).Flush()
				if mode == "cancel" {
					select {
					case <-r.Context().Done():
					case <-time.After(time.Second):
					}
					return
				}
				if mode == "interrupted" {
					return
				}
				if mode != "missing_usage" {
					if mode == "cumulative" {
						io.WriteString(w, "data: {\"usage\":{\"prompt_tokens\":10,\"completion_tokens\":5,\"total_tokens\":15,\"prompt_tokens_details\":{\"cached_tokens\":0}}}\n\n")
					}
					if mode == "decreasing" {
						io.WriteString(w, "data: {\"usage\":{\"prompt_tokens\":15,\"completion_tokens\":8,\"total_tokens\":23,\"prompt_tokens_details\":{\"cached_tokens\":0}}}\n\n")
					}
					io.WriteString(w, "data: {\"usage\":{\"prompt_tokens\":12,\"completion_tokens\":7,\"total_tokens\":19,\"prompt_tokens_details\":{\"cached_tokens\":4},\"completion_tokens_details\":{\"reasoning_tokens\":3}}}\n\n")
				}
				if mode == "accounting_failure" {
					_, _ = f.db.Exec("RENAME TABLE usage_events TO offline_usage_events")
				}
				io.WriteString(w, "data: {\"choices\":[{\"index\":0,\"delta\":{},\"finish_reason\":\"stop\"}]}\n\ndata: [DONE]\n\n")
			}))
			defer gateway.Close()
			relay := &Relay{core: f.core, endpoint: gateway.URL, client: gateway.Client(), maxBytes: 1 << 20, maxLine: 65536}
			recorder := httptest.NewRecorder()
			var writer http.ResponseWriter = recorder
			if mode == "cancel" {
				writer = &cancelWriter{header: http.Header{}}
			}
			e := relay.Forward(context.Background(), writer, RelayCall{Input: in, Body: []byte(`{"model":"synthetic","messages":[{"role":"user","content":"test"}]}`), Ticket: "test-transport-only", PlanHeader: "test-transport-only", Stream: mode != "nonstream"})
			if called != 1 {
				t.Fatal("must have one gateway dispatch", called)
			}
			success := mode == "stream" || mode == "nonstream" || mode == "cumulative"
			if success && e != nil {
				t.Fatal(e)
			}
			if !success && e == nil {
				t.Fatal("failure reported as success")
			}
			if !success && strings.Contains(recorder.Body.String(), "[DONE]") {
				t.Fatal("success terminator escaped before terminal commit")
			}
			if mode == "accounting_failure" {
				_, _ = f.db.Exec("RENAME TABLE offline_usage_events TO usage_events")
				return
			}
			_, state, e := f.core.ReadRequest(context.Background(), in.RequestID)
			if e != nil {
				t.Fatal(e)
			}
			if success && state != "succeeded" {
				t.Fatal("state", state)
			}
			if mode == "cumulative" {
				if c := readCounter(t, f, "tokens"); c.Known != "19" {
					t.Fatal("cumulative usage summed", c)
				}
			}
			if mode == "cancel" && state != "cancelled" {
				t.Fatal(state)
			}
			if c := readCounter(t, f, "tokens"); !success && c.Held != "140" {
				t.Fatal("unknown budget", c)
			}
			assertSQL(t, f.db, "SELECT COUNT(*) FROM concurrency_slots WHERE state='QUARANTINED'", 1)
		})
	}
}

type cancelWriter struct{ header http.Header }

func (w *cancelWriter) Header() http.Header       { return w.header }
func (w *cancelWriter) WriteHeader(int)           {}
func (w *cancelWriter) Write([]byte) (int, error) { return 0, io.ErrClosedPipe }

func TestMySQLRealRedisWitness(t *testing.T) {
	socket := os.Getenv("MAAS_REDIS_TEST_SOCKET")
	if socket == "" {
		t.Skip("real disposable Redis not provided")
	}
	if !strings.HasPrefix(socket, "/tmp/maas11-mysql.") {
		t.Fatal("requires owned disposable Redis")
	}
	f := setup(t, 2)
	ctx := context.Background()
	r := &RedisGate{Network: "unix", Address: socket, Prefix: f.config.DBName, Timeout: 2 * time.Second}
	p := RatePolicy{Revision: "test-rate-v1", Epoch: 1, WindowMS: 3600000, GlobalLimit: 1, KeyLimit: 1, Ready: true}
	if _, e := f.db.Exec("UPDATE kernel_guard SET global_limit=1,key_limit=1 WHERE id=1"); e != nil {
		t.Fatal(e)
	}
	f.core.rate = r
	if _, e := f.core.Admit(ctx, f.gate, f.input(t)); e == nil {
		t.Fatal("missing Redis epoch must fail closed")
	}
	if e := r.InitializeEpoch(ctx, p); e != nil {
		t.Fatal(e)
	}
	in := f.input(t)
	s := mustAdmit(t, f, in)
	if _, e := r.Acquire(ctx, in.RequestID, f.key, p); !errors.Is(e, ErrConflict) {
		t.Fatal("Redis replay", e)
	}
	fin := finalFor(s)
	fin.EvidenceRef = uuid.NewString()
	if e := f.core.Finalize(ctx, fin); e != nil {
		t.Fatal(e)
	}
	// Deliberately lose only these fixture buckets while preserving the marker.
	// Redis may now undercount; MySQL's durable same-window witness still wins.
	c, e := r.connect(ctx)
	if e != nil {
		t.Fatal(e)
	}
	defer c.Close()
	bucket := r.Prefix + "{maas-rate}:1:test-rate-v1:" + decimal(time.Now().UnixMilli()/p.WindowMS*p.WindowMS) + ":"
	if _, e = command(c, "DEL", bucket+"global", bucket+f.key); e != nil {
		t.Fatal(e)
	}
	if _, e = f.core.Admit(ctx, f.gate, f.input(t)); e == nil {
		t.Fatal("Redis loss bypassed durable rate cap")
	}
	assertSQL(t, f.db, "SELECT COUNT(*) FROM generation_requests", 1)
	epoch, e := f.core.BlockRate(ctx)
	if e != nil {
		t.Fatal(e)
	}
	if e = r.InitializeEpoch(ctx, RatePolicy{Revision: p.Revision, Epoch: epoch}); e != nil {
		t.Fatal(e)
	}
	if _, e = f.core.Admit(ctx, f.gate, f.input(t)); e == nil {
		t.Fatal("blocked epoch reopened without coordinator")
	}
}
