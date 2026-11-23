package agentruntime

import (
	"context"
	"encoding/json"
	"testing"
	"time"
)

func TestTrustedToolExecutionContext(t *testing.T) {
	tool := controlledTool(false)
	seen := make(chan ToolExecution, 1)
	tool.f = func(ctx context.Context) (string, error) {
		v, ok := ToolExecutionFrom(ctx)
		if !ok {
			t.Error("trusted execution metadata missing")
		}
		seen <- v
		return "safe", nil
	}
	h, _, _ := setupAR(t, toolResponse, nil, tool)
	sid, etag := arCreateSession(t, h)
	in := arInput("agent")
	in.Tools = []ARToolRef{{Name: tool.Spec().Name, Revision: "1"}}
	rid := arSubmit(t, h, sid, etag, in)
	if e := h.Service.Drive(context.Background(), arActor, sid, rid); e != nil {
		t.Fatal(e)
	}
	v := <-seen
	if v.SessionID != sid || v.RunID != rid || v.TraceID != rid || v.Principal.ID != arActor.ID || v.ToolCallID == "" || v.StepID == "" || v.RequestID == "" || v.IdempotencyKey == "" || v.Fence < 1 || !v.Deadline.After(time.Now().Add(-time.Second)) {
		t.Fatal("invalid trusted context")
	}
	b, e := json.Marshal(Definition(Calculator{}))
	if e != nil {
		t.Fatal(e)
	}
	var doc map[string]any
	if json.Unmarshal(b, &doc) != nil || doc["description"] == "" {
		t.Fatal("definition missing description")
	}
	if _, ok := doc["input_schema"].(map[string]any); !ok {
		t.Fatal("input schema is not a JSON object")
	}
	if _, ok := doc["output_schema"].(map[string]any); !ok {
		t.Fatal("output schema is not a JSON object")
	}
}
