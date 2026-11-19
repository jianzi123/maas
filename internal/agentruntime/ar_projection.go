package agentruntime

import (
	"crypto/rand"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"math/big"
	"sort"
	"strconv"
	"time"

	"github.com/google/uuid"
)

func rawHash(b []byte) string { h := sha256.Sum256(b); return hex.EncodeToString(h[:]) }
func opaque() string {
	var b [32]byte
	if _, e := rand.Read(b[:]); e != nil {
		panic("secure randomness unavailable")
	}
	return hex.EncodeToString(b[:])
}
func decimal(n int64) string { return strconv.FormatInt(n, 10) }
func nullable(s string) any {
	if s == "" {
		return nil
	}
	return s
}
func arConversation(v Session) map[string]any {
	var active any
	for _, r := range v.Runs {
		if !terminal(r.Status) {
			active = r.ID
			break
		}
	}
	return map[string]any{"id": v.ID, "owner_id": v.Owner, "title": v.Title, "model_alias": v.AR.Alias, "revision": decimal(v.Revision), "active_run_id": active, "created_at": v.AR.Created, "updated_at": v.AR.Updated, "deleted_at": v.AR.Deleted}
}
func arGroups(r Run) ([]ARUsageGroup, bool) {
	out := []ARUsageGroup{}
	by := map[string]*ARUsageGroup{}
	complete := len(r.Steps) > 0
	add := func(a, b string) string {
		x, ok := new(big.Int).SetString(a, 10)
		if !ok {
			return ""
		}
		y, ok := new(big.Int).SetString(b, 10)
		if !ok {
			return ""
		}
		return x.Add(x, y).String()
	}
	for _, st := range r.Steps {
		if !st.Usage.Complete {
			complete = false
		}
		for _, g := range st.Usage.Groups {
			key := g.Currency + "/" + g.Price
			if old := by[key]; old != nil {
				old.KnownTokens = add(old.KnownTokens, g.KnownTokens)
				old.HeldTokens = add(old.HeldTokens, g.HeldTokens)
				old.InflightTokens = add(old.InflightTokens, g.InflightTokens)
				old.KnownMoney = add(old.KnownMoney, g.KnownMoney)
				old.HeldMoney = add(old.HeldMoney, g.HeldMoney)
				old.InflightMoney = add(old.InflightMoney, g.InflightMoney)
			} else {
				copy := g
				by[key] = &copy
			}
		}
	}
	keys := []string{}
	for k := range by {
		keys = append(keys, k)
	}
	sort.Strings(keys)
	for _, k := range keys {
		out = append(out, *by[k])
	}
	return out, complete
}
func arRun(v Session, r Run) map[string]any {
	children := []string{}
	for _, s := range r.Steps {
		children = append(children, s.RequestID)
	}
	groups, complete := arGroups(r)
	return map[string]any{"id": r.ID, "session_id": v.ID, "client_operation_id": r.ClientID, "mode": r.Mode, "state": r.Status, "revision": decimal(v.Revision), "fence": decimal(r.AR.Fence), "input_head_message_id": r.MessageID, "model_alias": r.Model.Alias, "protocol_revision": r.Model.Protocol, "limits": r.AR.Limits, "cancel_requested": r.CancelRequested, "step_count": len(r.Steps), "child_request_ids": children, "usage_groups": groups, "aggregation_complete": complete, "last_event_seq": decimal(r.AR.Seq), "resume_cursor": r.AR.Cursor, "reason": nullable(r.Reason), "created_at": r.AR.Created, "deadline_at": r.Deadline, "finished_at": r.AR.Finished}
}
func findCall(r *Run, id string) (*Call, *Step) {
	for i := range r.Steps {
		st := &r.Steps[i]
		for j := range st.Calls {
			if st.Calls[j].ID == id || st.Calls[j].ApprovalID == id {
				return &st.Calls[j], st
			}
		}
	}
	return nil, nil
}
func arMessage(v Session, m Message) map[string]any {
	parts := []any{}
	r := run(&v, m.RunID)
	for _, p := range m.Parts {
		switch p.Type {
		case "text":
			parts = append(parts, map[string]any{"type": "text", "text": p.Text})
		case "tool_call":
			c, _ := findCall(r, p.CallID)
			parts = append(parts, map[string]any{"type": "tool_call", "call_id": c.ID, "name": c.Name, "tool_revision": c.ToolVersion, "arguments": c.Arguments, "args_sha256": c.ArgsHash})
		case "tool_result":
			parts = append(parts, map[string]any{"type": "tool_result", "call_id": p.CallID, "outcome": "succeeded", "result": p.Text})
		}
	}
	position := int64(0)
	for i := range v.Messages {
		if v.Messages[i].ID == m.ID {
			position = int64(i + 1)
			break
		}
	}
	status := m.Status
	if status == "" {
		status = "committed"
	}
	return map[string]any{"id": m.ID, "session_id": v.ID, "position": decimal(position), "role": m.Role, "parts": parts, "status": status, "run_id": nullable(m.RunID), "supersedes_message_id": nullable(m.ParentID), "created_at": m.Created}
}
func arStep(r Run, st Step) map[string]any {
	state := st.State
	switch state {
	case "running":
		if len(st.Calls) > 0 {
			state = "waiting_tools"
		} else {
			state = "model_running"
		}
	case "cancelled", "limit_reached":
		state = "failed"
	}
	return map[string]any{"id": st.ID, "run_id": r.ID, "index": st.Number, "model_call_id": uuid.NewSHA1(uuid.NameSpaceOID, []byte(st.ID+"/model-call")).String(), "child_request_id": st.RequestID, "state": state, "protocol_revision": r.Model.Protocol, "input_sha256": st.InputHash, "output_sha256": nullable(st.OutputHash)}
}
func arEffect(effect string) string {
	switch effect {
	case "pure":
		return "pure"
	case "read":
		return "read_only"
	default:
		return "non_idempotent"
	}
}
func arToolResult(c Call) map[string]any {
	outcome := "succeeded"
	if c.State == "unknown" {
		outcome = "unknown"
	} else if c.State != "completed" {
		outcome = "failed"
	}
	return map[string]any{"type": "tool_result", "call_id": c.ID, "outcome": outcome, "result": c.Result}
}
func arCall(r Run, st Step, c Call) map[string]any {
	state := c.State
	switch state {
	case "pending":
		state = "proposed"
	case "approved":
		state = "proposed"
	case "executing":
		state = "running"
	case "completed":
		state = "succeeded"
	case "not_executed", "denied":
		state = "cancelled"
	}
	var result any
	if c.State == "completed" || c.State == "failed" || c.State == "unknown" {
		result = arToolResult(c)
	}
	attempt := 0
	if c.State == "executing" || c.State == "completed" || c.State == "failed" || c.State == "unknown" {
		attempt = 1
	}
	return map[string]any{"id": c.ID, "run_id": r.ID, "step_id": st.ID, "name": c.Name, "tool_revision": c.ToolVersion, "args_sha256": c.ArgsHash, "state": state, "effect": arEffect(c.Effect), "attempt": attempt, "idempotency_key": uuid.NewSHA1(uuid.NameSpaceOID, []byte(c.ID+"/idempotency")).String(), "result": result, "source_call_id": c.SourceID, "arguments": c.Arguments}
}
func arApproval(r Run, c Call) map[string]any {
	state := "pending"
	if c.DecisionID != "" {
		if c.Decision == "deny" {
			state = "denied"
		} else {
			state = "allowed"
		}
	}
	switch c.State {
	case "approved", "executing", "completed":
		state = "allowed"
	case "denied":
		state = "denied"
	case "not_executed":
		state = "revoked"
	}
	if (state == "pending" || c.State == "approved") && !time.Now().Before(c.ApprovalExpires) {
		state = "expired"
	}
	return map[string]any{"id": c.ApprovalID, "run_id": r.ID, "call_id": c.ID, "tool_revision": c.ToolVersion, "args_sha256": c.ArgsHash, "policy_revision": r.AR.PolicyRevision, "scope_sha256": digest([]any{r.Granted, r.AuthRevision}), "expires_at": c.ApprovalExpires, "state": state, "tool_name": c.Name, "arguments": c.Arguments}
}
func arCheckpoint(v Session, r Run) map[string]any {
	children, calls := []string{}, []string{}
	if r.Checkpoint.Phase == "model_inflight" {
		children = append(children, r.Checkpoint.RequestID)
	}
	if r.Checkpoint.PendingCall != "" {
		calls = append(calls, r.Checkpoint.PendingCall)
	}
	return map[string]any{"run_id": r.ID, "revision": decimal(v.Revision), "last_event_seq": decimal(r.AR.Seq), "last_completed_step": r.Checkpoint.CompletedSteps, "message_head_id": r.MessageID, "context_sha256": r.AR.ContextHash, "context_strategy_revision": "reject-over-cap-v1", "registry_sha256": r.AR.RegistryHash, "policy_revision": r.AR.PolicyRevision, "pending_child_request_ids": children, "pending_tool_call_ids": calls, "fence": decimal(r.AR.Fence)}
}

// The complete envelope is saved alongside the state mutation. Replay never
// regenerates historical payloads from current state. Opaque 256-bit cursors are
// retained, immutable mappings to owner/session/run/version/sequence; every use
// resolves in that authorized run. There is no client-supplied numeric offset.
func projectEvent(v *Session, r *Run, kind string, data any, at time.Time) json.RawMessage {
	if r.AR == nil {
		return nil
	}
	var value any
	lookup := func(key string) string {
		m, ok := data.(map[string]any)
		if !ok {
			return ""
		}
		s, _ := m[key].(string)
		return s
	}
	switch kind {
	case "run.accepted", "run.started", "run.completed", "run.failed", "run.cancelled", "run.limit_reached", "run.needs_confirmation":
		value = "run"
	case "run.cancel_requested":
		value = map[string]any{"run_id": r.ID}
	case "message.created", "message.completed":
		if kind == "message.completed" {
			kind = "message.committed"
		}
		id := lookup("message_id")
		for _, m := range v.Messages {
			if m.ID == id {
				value = arMessage(*v, m)
				break
			}
		}
	case "message.delta":
		value = map[string]any{"message_id": lookup("message_id"), "offset": lookup("offset"), "text": lookup("text")}
	case "step.started", "step.finished":
		if len(r.Steps) > 0 {
			value = arStep(*r, r.Steps[len(r.Steps)-1])
		}
	case "tool.call":
		kind = "tool.proposed"
		if c, ok := data.(Call); ok {
			_, st := findCall(r, c.ID)
			if st != nil {
				value = arCall(*r, *st, c)
			}
		}
	case "tool.started", "tool.result":
		c, st := findCall(r, lookup("call_id"))
		if c != nil {
			if kind == "tool.result" {
				value = arToolResult(*c)
			} else {
				value = arCall(*r, *st, *c)
			}
		}
	case "approval.needed", "approval.resolved":
		if kind == "approval.needed" {
			kind = "approval.required"
		}
		c, _ := findCall(r, lookup("call_id"))
		if c != nil {
			value = arApproval(*r, *c)
		}
	case "usage":
		kind = "run.usage"
		groups, _ := arGroups(*r)
		value = map[string]any{"run_id": r.ID, "groups": groups}
	case "checkpoint.saved", "run.recovered":
		kind = "checkpoint.saved"
		value = "checkpoint"
	default:
		return nil
	}
	if value == nil {
		return nil
	}
	r.AR.Seq++
	r.AR.Cursor = opaque()
	// Event payload revision is the revision of the pending atomic commit.
	committed := *v
	committed.Revision++
	if marker, ok := value.(string); ok {
		if marker == "run" {
			value = arRun(committed, *r)
		} else {
			value = arCheckpoint(committed, *r)
		}
	}
	b, _ := json.Marshal(value)
	env := AREnvelope{Version: ARVersion, ID: uuid.NewString(), SessionID: v.ID, RunID: r.ID, Seq: decimal(r.AR.Seq), Cursor: r.AR.Cursor, Created: at, Type: kind, Data: b}
	encoded, _ := json.Marshal(env)
	return encoded
}
