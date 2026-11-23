package agentruntime

import (
	"context"
	"encoding/json"
	"fmt"
	"github.com/google/uuid"
	"testing"
	"time"
)

func TestQAARToolOutcomeMatrix(t *testing.T) {
	for _, effect := range []string{"pure", "read", "write"} {
		for _, mode := range []string{"duration", "tool_timeout", "cancel"} {
			t.Run(effect+"/"+mode, func(t *testing.T) {
				entered := make(chan struct{})
				tool := controlledTool(effect == "write")
				tool.spec.Effect = effect

				tool.f = func(ctx context.Context) (string, error) { close(entered); <-ctx.Done(); return "", ctx.Err() }
				h, m, _ := setupAR(t, func(_ context.Context, r Request, _ func(string) error) (Response, error) {
					return Response{RequestID: r.RequestID, TerminalConfirmed: true, Finish: "tool_calls", Calls: []Call{{ID: "source-call-1", Name: "controlled_tool", Arguments: json.RawMessage("{}")}}, Usage: arUsage()}, nil
				}, nil, tool)
				sid, etag := arCreateSession(t, h)
				in := arInput("agent")
				in.Tools = []ARToolRef{{Name: "controlled_tool", Revision: "1"}}
				if mode == "duration" {
					in.Limits.Duration = 1000
				} else if mode == "tool_timeout" {
					in.Limits.ToolTimeout = 10
				}
				rid := arSubmit(t, h, sid, etag, in)
				if effect == "write" {
					if err := h.Service.Drive(context.Background(), arActor, sid, rid); err != nil {
						t.Fatal(err)
					}
					v, err := h.Service.Get(context.Background(), arActor, sid)
					if err != nil {
						t.Fatal(err)
					}
					c := run(&v, rid).Steps[0].Calls[0]
					d := ARDecision{ID: uuid.NewString(), Decision: "allow", ArgsHash: c.ArgsHash, ToolRevision: c.ToolVersion, PolicyRevision: arActor.Revision}
					arHTTP(t, h, "POST", "sessions/"+sid+"/runs/"+rid+"/approvals/"+c.ApprovalID+"/decision", d, "", "Approval", 200)
				}
				owned, cancel := context.WithCancel(context.Background())
				defer cancel()
				driven := make(chan error, 1)
				go func() { driven <- h.Service.Drive(owned, arActor, sid, rid); close(driven) }()
				defer func() {
					cancel()
					select {
					case <-driven:
					case <-time.After(2 * time.Second):
						t.Error("owned tool did not stop")
					}
				}()
				select {
				case <-entered:
				case <-time.After(2 * time.Second):
					t.Fatal("tool did not enter")
				}
				if mode == "cancel" {
					arHTTP(t, h, "POST", "sessions/"+sid+"/runs/"+rid+"/cancel", nil, "", "Run", 202)
				}
				select {
				case err := <-driven:
					if err != nil {
						t.Fatal(err)
					}
				case <-time.After(3 * time.Second):
					t.Fatal("tool did not terminate")
				}
				v, err := h.Service.Get(context.Background(), arActor, sid)
				if err != nil {
					t.Fatal(err)
				}
				r := run(&v, rid)
				c := r.Steps[0].Calls[0]
				wantRun, wantCall, wantReason := "limit_reached", "failed", "duration_limit"
				if mode == "cancel" {
					wantRun, wantCall, wantReason = "cancelled", "cancelled", "execution_stopped"
				}
				if mode == "tool_timeout" {
					wantRun, wantCall, wantReason = "failed", "failed", "tool_timeout"
				}
				if effect == "write" {
					wantRun, wantCall, wantReason = "needs_confirmation", "unknown", "tool_outcome_unknown"
				}
				if r.Status != wantRun || c.State != wantCall || r.Reason != wantReason || c.Attempt != 1 {
					t.Fatalf("run=%s reason=%s tool=%s attempt=%d", r.Status, r.Reason, c.State, c.Attempt)
				}
				base := "sessions/" + sid + "/runs/" + rid
				arHTTP(t, h, "GET", base, nil, "", "Run", 200)
				arHTTP(t, h, "GET", base+"/steps", nil, "", "StepPage", 200)
				page := arDecode(t, arHTTP(t, h, "GET", base+"/tool-calls", nil, "", "ToolCallPage", 200))
				if page["data"].([]any)[0].(map[string]any)["attempt"] != float64(1) {
					t.Fatal(page)
				}
				arHTTP(t, h, "GET", base+"/events", nil, "", "EventPage", 200)
				if effect == "write" {
					_ = h.Service.Drive(context.Background(), arActor, sid, rid)
				}
				if tool.calls.Load() != 1 || m.calls.Load() != 1 {
					t.Fatal("unknown/replay executed work again")
				}
				t.Logf("QA session=%s run_id=%s tool_id=%s effect=%s mode=%s run=%s reason=%s tool=%s attempt=%d model_calls=%d tool_calls=%d", sid,rid,c.ID,effect,mode,r.Status,r.Reason,c.State,c.Attempt,m.calls.Load(),tool.calls.Load())
			})
		}
	}
	t.Run("approval_cancel_never_attempted", func(t *testing.T) {
		tool := controlledTool(true)
		h, _, _ := setupAR(t, func(_ context.Context, r Request, _ func(string) error) (Response, error) {
			return Response{RequestID: r.RequestID, TerminalConfirmed: true, Finish: "tool_calls", Calls: []Call{{ID: "source-call-1", Name: "controlled_tool", Arguments: json.RawMessage("{}")}}, Usage: arUsage()}, nil
		}, nil, tool)
		sid, etag := arCreateSession(t, h)
		in := arInput("agent")
		in.Tools = []ARToolRef{{Name: "controlled_tool", Revision: "1"}}
		rid := arSubmit(t, h, sid, etag, in)
		if err := h.Service.Drive(context.Background(), arActor, sid, rid); err != nil {
			t.Fatal(err)
		}
		arHTTP(t, h, "POST", "sessions/"+sid+"/runs/"+rid+"/cancel", nil, "", "Run", 202)
		page := arDecode(t, arHTTP(t, h, "GET", fmt.Sprintf("sessions/%s/runs/%s/tool-calls", sid, rid), nil, "", "ToolCallPage", 200))
		c := page["data"].([]any)[0].(map[string]any)
		if c["state"] != "cancelled" || c["attempt"] != float64(0) || tool.calls.Load() != 0 {
			t.Fatal(c)
		}
	})
}

func TestQAARCursorMigration(t *testing.T) {
	h, _, _ := setupAR(t, arPlain, nil)
	sid, _ := arCreateSession(t, h)
	path := "/api/agent/v1/sessions/" + sid + "/messages"
	v, _ := h.Service.Get(context.Background(), arActor, sid)
	token := h.pageToken(arActor, path, []int64{v.Revision, 0})
	t.Run("same_revision", func(t *testing.T) {
		arHTTP(t, h, "GET", "sessions/"+sid+"/messages?cursor="+token, nil, "", "MessagePage", 200)
	})
	t.Run("legacy_requires_snapshot", func(t *testing.T) {
		arHTTP(t, h, "GET", "sessions/"+sid+"/messages?cursor="+h.pageToken(arActor, path, 0), nil, "", "Error", 410)
	})
	t.Run("tampered_rejected", func(t *testing.T) {
		arHTTP(t, h, "GET", "sessions/"+sid+"/messages?cursor="+token+"x", nil, "", "Error", 400)
	})
}
