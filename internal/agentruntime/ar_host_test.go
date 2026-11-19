package agentruntime

import (
	"context"
	"testing"
	"time"

	"github.com/google/uuid"
)

func TestAR1HostApprovalResumeAndWaitingDeadline(t *testing.T) {
	for _, mode := range []string{"resume", "expire"} {
		t.Run(mode, func(t *testing.T) {
			tool := controlledTool(true)
			h, model, _ := setupAR(t, toolResponse, nil, tool)
			host, e := NewHost(context.Background(), h.Service, 1, h.Service.Reauthorize)
			if e != nil {
				t.Fatal(e)
			}
			defer host.Close()
			h.Dispatch = host.Schedule
			sid, etag := arCreateSession(t, h)
			in := arInput("agent")
			in.Tools = []ARToolRef{{Name: tool.Spec().Name, Revision: "1"}}
			if mode == "expire" {
				in.Limits.Duration = 80
			}
			rid := arSubmit(t, h, sid, etag, in)
			deadline := time.Now().Add(3 * time.Second)
			var current Run
			for {
				v, _ := h.Service.Get(context.Background(), arActor, sid)
				current = *run(&v, rid)
				if current.Status == "waiting_approval" || terminal(current.Status) {
					break
				}
				if time.Now().After(deadline) {
					t.Fatal(current)
				}
				time.Sleep(time.Millisecond)
			}
			if mode == "resume" {
				if current.Status != "waiting_approval" {
					t.Fatal(current)
				}
				c := current.Steps[0].Calls[0]
				d := ARDecision{ID: uuid.NewString(), Decision: "allow", ArgsHash: c.ArgsHash, ToolRevision: c.ToolVersion, PolicyRevision: arActor.Revision}
				arHTTP(t, h, "POST", "sessions/"+sid+"/runs/"+rid+"/approvals/"+c.ApprovalID+"/decision", d, "", "Approval", 200)
			}
			for {
				v, _ := h.Service.Get(context.Background(), arActor, sid)
				current = *run(&v, rid)
				if terminal(current.Status) {
					break
				}
				if time.Now().After(deadline) {
					t.Fatal(current)
				}
				time.Sleep(time.Millisecond)
			}
			if mode == "resume" {
				if current.Status != "completed" || tool.calls.Load() != 1 || model.calls.Load() != 2 {
					t.Fatal(current)
				}
			} else {
				if current.Status != "limit_reached" || current.Reason != "duration_limit" || tool.calls.Load() != 0 {
					t.Fatal(current)
				}
			}
		})
	}
}
