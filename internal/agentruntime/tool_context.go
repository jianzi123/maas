package agentruntime

import (
	"context"
	"github.com/google/uuid"
	"time"
)

// ToolExecution is derived from trusted runtime state, not tool arguments.
type ToolExecution struct {
	Principal                                                                Principal
	SessionID, RunID, StepID, ToolCallID, RequestID, TraceID, IdempotencyKey string
	Deadline                                                                 time.Time
	Fence                                                                    int64
}
type toolExecutionKey struct{}

func ToolExecutionFrom(ctx context.Context) (ToolExecution, bool) {
	v, ok := ctx.Value(toolExecutionKey{}).(ToolExecution)
	return v, ok
}
func toolContext(ctx context.Context, p Principal, sid string, r Run, c Call) context.Context {
	step := r.Steps[len(r.Steps)-1]
	deadline, _ := ctx.Deadline()
	fence := int64(0)
	if r.AR != nil {
		fence = r.AR.Fence
	}
	v := ToolExecution{Principal: p, SessionID: sid, RunID: r.ID, StepID: step.ID, ToolCallID: c.ID, RequestID: step.RequestID, TraceID: r.ID, IdempotencyKey: uuid.NewSHA1(uuid.NameSpaceOID, []byte(c.ID+"/idempotency")).String(), Deadline: deadline, Fence: fence}
	return context.WithValue(ctx, toolExecutionKey{}, v)
}

type ToolDefinition struct {
	Name             string `json:"name"`
	Version          string `json:"version"`
	Description      string `json:"description"`
	InputSchema      any    `json:"input_schema"`
	OutputSchema     any    `json:"output_schema"`
	Scope            string `json:"required_scope"`
	Effect           string `json:"effect"`
	RequiresApproval bool   `json:"requires_approval"`
}

func Definition(t Tool) ToolDefinition {
	spec := t.Spec()
	description := "Registered extension tool"
	switch spec.Name {
	case "bounded_arithmetic":
		description = "Bounded integer add, subtract and multiply; no code evaluation."
	case "list_visible_models":
		description = "Read current trusted principal's approved model catalogue; never credentials."
	}
	output := spec.OutputSchema
	if len(output) == 0 {
		output = []byte(`{"type":"string"}`)
	}
	return ToolDefinition{Name: spec.Name, Version: spec.Version, Description: description, InputSchema: spec.Schema, OutputSchema: output, Scope: spec.Permission, Effect: spec.Effect, RequiresApproval: spec.Approval}
}
