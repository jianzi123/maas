package app

import (
	"bytes"
	"context"
	"crypto/tls"
	"crypto/x509"
	"database/sql"
	"encoding/json"
	"io"
	"net/http"
	"net/http/cookiejar"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"github.com/google/uuid"
	a "github.com/jianzi123/maas/internal/agentruntime"
	"github.com/jianzi123/maas/internal/agentruntime/kernelmodel"
	"github.com/jianzi123/maas/internal/kernel"
	"github.com/jianzi123/maas/internal/protocol"
	"github.com/jianzi123/maas/internal/release"
	"github.com/jianzi123/maas/internal/release/mysqlstore"
)

type countingProductTool struct {
	a.Tool
	count *atomic.Int32
}

type observedProductModel struct {
	a.ModelClient
	t *testing.T
}

func (m observedProductModel) Generate(ctx context.Context, r a.Request, emit func(string) error) (a.Response, error) {
	out, e := m.ModelClient.Generate(ctx, r, emit)
	if e != nil {
		m.t.Logf("model error=%v terminal=%v unknown=%v request=%s", e, out.TerminalConfirmed, out.OutcomeUnknown, r.RequestID)
	}
	return out, e
}

func (t countingProductTool) Execute(ctx context.Context, p a.Principal, key string, b json.RawMessage) (string, error) {
	t.count.Add(1)
	return t.Tool.Execute(ctx, p, key, b)
}

// Actual normal HTTP/AR/Service/ModelClient/Relay/mTLS/MySQL/ledger and real tools.
// Only Higress/source/rate/publication/closure producers are scoped test fixtures.
func TestProductToolsProtectedLoopAndWholeBatch(t *testing.T) {
	for _, invalid := range []bool{false, true} {
		name := "complete"
		if invalid {
			name = "invalid_second_tool"
		}
		t.Run(name, func(t *testing.T) {
			m := testConfiguredModel(t, true)
			c := m.Config
			ctx := context.Background()
			p, e := m.Core.Profile(ctx, c.Models[0].PublicationID)
			if e != nil {
				t.Fatal(e)
			}
			pepper, e := secret(c.Secrets.PepperFile, 32, 4096)
			if e != nil {
				t.Fatal(e)
			}
			raw, e := secret(c.Models[0].PlatformKeyFile, 40, 128)
			if e != nil {
				t.Fatal(e)
			}
			key, _, e := m.Core.Authenticate(ctx, string(raw))
			if e != nil {
				t.Fatal(e)
			}
			core, e := kernel.New(m.CoreDBForTest(t), c.Cluster, pepper, offlineRate{Key: key}, offlineProofs{UID: p.CRUID, PubID: p.Binding.PublicationID, Source: p.SourceID})
			if e != nil {
				t.Fatal(e)
			}
			db := m.CoreDBForTest(t)
			gate, e := mysqlstore.New(db, c.Cluster, core)
			if e != nil {
				t.Fatal(e)
			}
			state, e := gate.Read(ctx, p.CRUID)
			if e != nil {
				t.Fatal(e)
			}
			target := p.Binding.PublicationID
			if e = gate.Apply(ctx, release.Command{ID: uuid.NewString(), Action: "Activate", CRUID: p.CRUID, Generation: state.Generation, Fence: state.Fence, Target: &target, Revision: state.Revision, EvidenceRefs: state.EvidenceRefs}); e != nil {
				t.Fatal(e)
			}
			if e = core.ReadyRate(ctx, c.Ledger.Epoch); e != nil {
				t.Fatal(e)
			}
			m.Core, m.Gate = core, gate
			var prepared sync.Map
			var dispatches atomic.Int32
			var tools atomic.Int32
			signing, e := secret(c.Gateway.AdmissionKeyFile, 32, 8192)
			if e != nil {
				t.Fatal(e)
			}
			gateway := httptest.NewUnstartedServer(http.HandlerFunc(func(w http.ResponseWriter, q *http.Request) {
				id := q.Header.Get("X-Request-ID")
				stored, ok := prepared.Load(id)
				if !ok {
					t.Error("missing original signed intent")
					w.WriteHeader(503)
					return
				}
				call := stored.(kernel.RelayCall)
				body, _ := io.ReadAll(q.Body)
				verified, e := protocol.VerifyTicket(q.Header.Get("X-Maas-Admission-Ticket"), q.Header.Get("X-Maas-Reservation-Plan"), signing)
				if e != nil || verified.Claims["body_sha256"] != protocol.Digest(body) || q.Header.Get("X-Maas-Admission-Ticket") != call.Ticket || len(q.TLS.PeerCertificates) == 0 {
					t.Error("private binding lost")
					w.WriteHeader(403)
					return
				}
				if _, e = core.Admit(q.Context(), gate, call.Input); e != nil {
					t.Error("original Admit", e)
					w.WriteHeader(503)
					return
				}
				turn := dispatches.Add(1)
				if turn == 2 {
					var request map[string]any
					json.Unmarshal(body, &request)
					messages := request["messages"].([]any)
					seen := map[string]bool{}
					for _, v := range messages {
						row := v.(map[string]any)
						if row["role"] == "tool" {
							seen[row["tool_call_id"].(string)] = true
						}
					}
					if !seen["provider-a"] || !seen["provider-b"] || len(seen) != 2 {
						t.Error("feedback used internal UUID or lost result", seen)
					}
				}
				w.Header().Set("Content-Type", "text/event-stream")
				frame := func(delta any, finish any, usage any) {
					b, _ := json.Marshal(map[string]any{"model": p.UpstreamModel, "choices": []any{map[string]any{"index": 0, "delta": delta, "finish_reason": finish}}, "usage": usage})
					io.WriteString(w, "data: "+string(b)+"\n\n")
					w.(http.Flusher).Flush()
				}
				frame(map[string]any{"role": "assistant"}, nil, nil)
				finish := "stop"
				if turn == 1 {
					finish = "tool_calls"
					args := `{}`
					if invalid {
						args = `{"scope":"all"}`
					}
					frame(map[string]any{"tool_calls": []any{map[string]any{"index": 0, "id": "provider-a", "type": "function", "function": map[string]any{"name": "bounded_arithmetic", "arguments": `{"a":6,`}}, map[string]any{"index": 1, "id": "provider-b", "type": "function", "function": map[string]any{"name": "list_visible_models", "arguments": args}}}}, nil, nil)
					frame(map[string]any{"tool_calls": []any{map[string]any{"index": 0, "function": map[string]any{"arguments": `"b":7,"op":"multiply"}`}}}}, nil, nil)
				} else {
					frame(map[string]any{"content": "受控工具结果42🙂"}, nil, nil)
				}
				frame(map[string]any{}, finish, map[string]any{"prompt_tokens": 12, "completion_tokens": 7, "total_tokens": 19, "prompt_cache_hit_tokens": 4, "prompt_cache_miss_tokens": 8, "completion_tokens_details": map[string]any{"reasoning_tokens": 0}})
				io.WriteString(w, "data: [DONE]\n\n")
			}))
			gateway.TLS = &tls.Config{MinVersion: tls.VersionTLS13, ClientAuth: tls.RequireAnyClientCert}
			gateway.StartTLS()
			defer gateway.Close()
			roots := x509.NewCertPool()
			roots.AddCert(gateway.Certificate())
			transport := &http.Transport{TLSClientConfig: &tls.Config{MinVersion: tls.VersionTLS13, RootCAs: roots, Certificates: gateway.TLS.Certificates}}
			relay, e := kernel.NewRelay(core, gateway.URL, transport, 1<<20, 65536)
			if e != nil {
				t.Fatal(e)
			}
			defer relay.Close()
			m.relay = relay
			clientModel := kernelmodel.RelayModel{Relay: relay, Prepare: func(ctx context.Context, in a.Request) (kernel.RelayCall, error) {
				call, e := m.prepare(ctx, in)
				if e != nil {
					t.Logf("prepare error=%v protocol=%s bounds=%d/%d/%s context=%d messages=%d tools=%d", e, in.Model.Protocol, in.TokenUpper, in.MoneyUpper, in.Currency, in.ContextTokenLimit, len(in.Messages), len(in.Tools))
				}
				if e == nil {
					prepared.Store(in.RequestID, call)
				}
				return call, e
			}, Usage: m.usage, FailureResolved: m.resolved}
			site := httptest.NewUnstartedServer(nil)
			c.Origin = "http://" + site.Listener.Addr().String()
			m.Config = c
			runtime, e := Open(ctx, c)
			if e != nil {
				t.Fatal(e)
			}
			defer runtime.Close()
			runtime.Service.Model = observedProductModel{clientModel, t}
			runtime.Service.CountContext = m.CountContext
			runtime.Agent.Catalog = m
			registry, e := a.NewRegistry(countingProductTool{a.Calculator{}, &tools}, countingProductTool{a.ModelDirectory{Read: m.Visible}, &tools})
			if e != nil {
				t.Fatal(e)
			}
			runtime.Service.Tools = registry
			site.Config.Handler = runtime.Handler
			site.Start()
			defer site.Close()
			jar, _ := cookiejar.New(nil)
			httpClient := &http.Client{Jar: jar, Timeout: 10 * time.Second}
			csrf := ""
			httpTrace := []map[string]any{}
			do := func(method, path string, value any, etag string, status int) (map[string]any, http.Header) {
				t.Helper()
				b, _ := json.Marshal(value)
				q, _ := http.NewRequest(method, site.URL+path, bytes.NewReader(b))
				q.Header.Set("Origin", c.Origin)
				q.Header.Set("Content-Type", "application/json")
				q.Header.Set("X-CSRF-Token", csrf)
				if etag != "" {
					q.Header.Set("If-Match", etag)
				}
				res, e := httpClient.Do(q)
				if e != nil {
					t.Fatal(e)
				}
				defer res.Body.Close()
				raw, _ := io.ReadAll(res.Body)
				if res.StatusCode != status {
					t.Fatalf("%s %s %d: %s", method, path, res.StatusCode, raw)
				}
				if os.Getenv("MAAS_CAPTURE_PRODUCT_TOOLS") == "1" && strings.HasPrefix(path, "/api/agent/v1/") {
					httpTrace = append(httpTrace, map[string]any{"method": method, "path": path, "status": res.StatusCode, "etag": res.Header.Get("ETag"), "body": json.RawMessage(raw)})
				}
				var out map[string]any
				if len(raw) > 0 && json.Unmarshal(raw, &out) != nil {
					t.Fatal("invalid JSON")
				}
				return out, res.Header
			}
			login, _ := do("POST", "/api/admin/v1/session", map[string]string{"username": c.Auth.Username, "password": "test-only-password-12345"}, "", 200)
			csrf = login["csrf_token"].(string)
			session, h := do("POST", "/api/agent/v1/sessions", a.ARCreate{OperationID: uuid.NewString(), Title: "protected tools", Alias: p.Alias}, "", 201)
			sid := session["id"].(string)
			text := "compute and list models"
			accepted, _ := do("POST", "/api/agent/v1/sessions/"+sid+"/runs", a.ARRunCreate{OperationID: uuid.NewString(), Mode: "agent", Operation: "send", Text: &text, Alias: p.Alias, Limits: c.Agent.Limits, Tools: []a.ARToolRef{{Name: "bounded_arithmetic", Revision: "1"}, {Name: "list_visible_models", Revision: "1"}}}, h.Get("ETag"), 202)
			rid := accepted["run"].(map[string]any)["id"].(string)
			base := "/api/agent/v1/sessions/" + sid + "/runs/" + rid
			deadline := time.Now().Add(20 * time.Second)
			for {
				run, _ := do("GET", base, nil, "", 200)
				state := run["state"]
				if state == "completed" || state == "failed" || state == "needs_confirmation" {
					want := "completed"
					expectedCalls := int32(2)
					if invalid {
						want = "failed"
						expectedCalls = 1
					}
					if state != want || dispatches.Load() != expectedCalls {
						t.Fatal("wrong protected loop outcome", run, dispatches.Load())
					}
					var requests, events int
					db.QueryRow("SELECT COUNT(*) FROM generation_requests").Scan(&requests)
					db.QueryRow("SELECT COUNT(*) FROM usage_events").Scan(&events)
					if requests != int(expectedCalls) || events != requests || tools.Load() != map[bool]int32{false: 2, true: 0}[invalid] {
						t.Fatal("duplicate accounting or partial batch execution", requests, events, tools.Load())
					}
					groups := run["usage_groups"].([]any)
					wantTokens := "38"
					if invalid {
						wantTokens = "19"
					}
					if groups[0].(map[string]any)["known_tokens"] != wantTokens {
						t.Fatal("invalid batch erased settled model usage", run)
					}
					do("GET", base+"/events?page_size=100", nil, "", 200)
					if os.Getenv("MAAS_CAPTURE_PRODUCT_TOOLS") == "1" {
						document, e := runtime.Service.Store.Get(ctx, sid)
						if e != nil {
							t.Fatal(e)
						}
						children := []any{}
						for _, run := range document.Runs {
							for _, step := range run.Steps {
								record, e := core.LookupRequest(ctx, step.RequestID)
								if e != nil {
									t.Fatal(e)
								}
								children = append(children, record)
							}
						}
						root, e := filepath.Abs("../..")
						if e != nil {
							t.Fatal(e)
						}
						dir := filepath.Join(root, "artifacts", "fc1-wire")
						if e = os.MkdirAll(dir, 0700); e != nil {
							t.Fatal(e)
						}
						trace := map[string]any{"kind": "actual-controlled-http-and-mysql; no real supplier", "generated_at": time.Now().UTC(), "http": httpTrace, "persisted_session": document, "original_child_records": children}
						b, e := json.MarshalIndent(trace, "", "  ")
						if e != nil {
							t.Fatal(e)
						}
						if e = os.WriteFile(filepath.Join(dir, name+".json"), append(b, '\n'), 0600); e != nil {
							t.Fatal(e)
						}
						t.Log("saved controlled trace: artifacts/fc1-wire/" + name + ".json (no login/cookie/CSRF captured)")
					}
					break
				}
				if time.Now().After(deadline) {
					t.Fatal("protected loop timed out", run)
				}
				time.Sleep(10 * time.Millisecond)
			}
		})
	}
}

func (m *Models) CoreDBForTest(t *testing.T) *sql.DB {
	t.Helper()
	db, e := openDB(context.Background(), m.Config.MySQL.RuntimeDSNFile)
	if e != nil {
		t.Fatal(e)
	}
	t.Cleanup(func() { db.Close() })
	return db
}
