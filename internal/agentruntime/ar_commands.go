package agentruntime

import (
	"context"
	"errors"
	"strconv"
	"time"

	"github.com/google/uuid"
	"github.com/jianzi123/maas/internal/protocol"
)

type arError struct {
	Status int
	Code   string
}

func (e *arError) Error() string              { return e.Code }
func arFailure(status int, code string) error { return &arError{status, code} }
func mustCanonical(b []byte) []byte {
	v, e := protocol.Canonical(b)
	if e != nil {
		return nil
	}
	return v
}
func selectedTool(r Run, name, revision string) bool {
	if r.AR == nil {
		return true
	}
	for _, t := range r.AR.Tools {
		if t.Name == name && t.Revision == revision {
			return true
		}
	}
	return false
}
func selectedSpecs(registry ToolRegistry, p Principal, r Run) []ToolSpec {
	out := []ToolSpec{}
	for _, spec := range registry.Specs(effective(p, r)) {
		if selectedTool(r, spec.Name, spec.Version) {
			out = append(out, spec)
		}
	}
	return out
}
func internalLimits(base Limits, l ARLimits) Limits {
	base.Steps = l.Steps
	base.Calls = l.Calls
	base.Duration = time.Duration(l.Duration) * time.Millisecond
	base.ToolTimeout = time.Duration(l.ToolTimeout) * time.Millisecond
	base.OutputBytes = l.OutputBytes
	base.Currency = l.Currency
	base.Tokens, _ = strconv.ParseInt(l.Tokens, 10, 64)
	base.Money, _ = strconv.ParseInt(l.Money, 10, 64)
	return base
}
func creationID(p Principal, operation string) string {
	return uuid.NewSHA1(uuid.NameSpaceOID, []byte("ar1/create/"+p.ID+"/"+operation)).String()
}
func (s *Service) createAR(ctx context.Context, p Principal, in ARCreate, hash string) (Session, bool, error) {
	id := creationID(p, in.OperationID)
	for i := 0; i < 3; i++ {
		v, e := s.Store.Get(ctx, id)
		if e == nil {
			if v.Owner != p.ID || v.AR == nil {
				return Session{}, false, ErrNotFound
			}
			if v.AR.Hash != hash {
				return Session{}, false, arFailure(409, "operation_conflict")
			}
			if v.Deleted {
				return Session{}, false, ErrConflict
			}
			return v, false, nil
		}
		if !errors.Is(e, ErrNotFound) {
			return Session{}, false, e
		}
		now := time.Now().UTC()
		v = Session{Version: Version, ID: id, Owner: p.ID, Title: in.Title, Revision: 1, Messages: []Message{}, Runs: []Run{}, Events: []Event{}, AR: &ARSession{OperationID: in.OperationID, Hash: hash, Alias: in.Alias, Created: now, Updated: now}}
		e = s.Store.CompareAndSwap(ctx, v, 0)
		if errors.Is(e, ErrConflict) {
			continue
		}
		return v, true, e
	}
	return Session{}, false, ErrConflict
}
func creationCommand(v Session) map[string]any {
	return map[string]any{"client_operation_id": v.AR.OperationID, "session_id": v.ID, "state": "accepted", "request_sha256": v.AR.Hash}
}
func command(v Session, r Run) map[string]any {
	return map[string]any{"client_operation_id": r.ClientID, "session_id": v.ID, "state": "accepted", "run_id": r.ID, "request_sha256": r.InputHash}
}
func accepted(v Session, r Run) map[string]any {
	var m Message
	for _, msg := range v.Messages {
		if msg.ID == r.MessageID {
			m = msg
			break
		}
	}
	return map[string]any{"conversation": arConversation(v), "run": arRun(v, r), "input_message": arMessage(v, m), "operation": command(v, r), "resume_cursor": r.AR.Cursor}
}
func checkARLimits(req, policy ARLimits) error {
	a, b := internalLimits(Limits{}, req), internalLimits(Limits{}, policy)
	if a.Tokens < 0 || a.Money < 0 {
		return arFailure(422, "run_limit_exceeded")
	}
	if _, e := strconv.ParseInt(req.Tokens, 10, 64); e != nil {
		return arFailure(422, "run_limit_exceeded")
	}
	if _, e := strconv.ParseInt(req.Money, 10, 64); e != nil {
		return arFailure(422, "run_limit_exceeded")
	}
	if req.Currency != policy.Currency || req.Steps > policy.Steps || req.Calls > policy.Calls || req.Tools > policy.Tools || req.Duration > policy.Duration || req.ToolTimeout > policy.ToolTimeout || req.OutputBytes > policy.OutputBytes || req.ContextTokens > policy.ContextTokens || req.NoProgress > policy.NoProgress || a.Tokens > b.Tokens || a.Money > b.Money {
		return arFailure(422, "run_limit_exceeded")
	}
	return nil
}
func (h *ARHandler) submit(ctx context.Context, p Principal, sid, match string, in ARRunCreate, hash string) (map[string]any, error) {
	v, e := h.Service.Get(ctx, p, sid)
	if e != nil {
		return nil, e
	}
	if v.AR == nil {
		return nil, ErrNotFound
	}
	// Idempotent recovery precedes stale revision, current policy and capability
	// changes. Authorization has already been rechecked by this request.
	for _, r := range v.Runs {
		if r.ClientID == in.OperationID {
			if r.InputHash != hash {
				return nil, arFailure(409, "operation_conflict")
			}
			if h.Dispatch != nil && r.Status == "accepted" {
				if e = h.Dispatch(p, sid, r.ID); e != nil {
					return nil, e
				}
			}
			return accepted(v, r), nil
		}
	}
	if e = checkARLimits(in.Limits, h.Policy); e != nil {
		return nil, e
	}
	expected, e := revision(match)
	if e != nil {
		return nil, e
	}
	if expected != v.Revision {
		return nil, arFailure(409, "revision_conflict")
	}
	for _, r := range v.Runs {
		if !terminal(r.Status) {
			return nil, arFailure(409, "conversation_busy")
		}
	}
	model, e := h.Catalog.Resolve(ctx, p, in.Alias, in.Mode)
	if e != nil {
		return nil, e
	}
	for _, ref := range in.Tools {
		t, ok := h.Service.Tools.Lookup(ref.Name)
		if !ok || t.Spec().Version != ref.Revision || !p.Permissions[t.Spec().Permission] {
			return nil, arFailure(422, "tool_unsupported")
		}
	}
	if len(in.Tools) > in.Limits.Tools {
		return nil, arFailure(422, "run_limit_exceeded")
	}
	text, parent := "", ""
	if in.Text != nil {
		text = *in.Text
	}
	if in.Operation != "send" {
		// Only the current visible branch may be edited. Regeneration references
		// the visible assistant and reuses its original input, retaining old usage.
		visible := visibleHistory(v)
		var ref *Message
		for i := range visible {
			if in.Reference != nil && visible[i].ID == *in.Reference {
				ref = &visible[i]
			}
		}
		if ref == nil {
			return nil, arFailure(409, "message_not_current")
		}
		if in.Operation == "edit" {
			if ref.Role != "user" {
				return nil, ErrInvalid
			}
			parent = ref.ID
		} else {
			if ref.Role != "assistant" {
				return nil, ErrInvalid
			}
			old := run(&v, ref.RunID)
			if old == nil {
				return nil, ErrNotFound
			}
			parent = old.MessageID
			for _, m := range v.Messages {
				if m.ID == parent && len(m.Parts) > 0 {
					text = m.Parts[0].Text
					break
				}
			}
		}
	}
	now := time.Now().UTC()
	execution := &ARExecution{Limits: in.Limits, Tools: in.Tools, Operation: in.Operation, Created: now, Fence: 1, Cursor: opaque(), ContextHash: digest([]any{}), RegistryHash: digest(in.Tools), PolicyRevision: p.Revision}
	if in.Reference != nil {
		execution.Reference = *in.Reference
	}
	r, e := h.Service.Submit(ctx, p, sid, Submit{ClientID: in.OperationID, Text: text, ParentID: parent, Mode: in.Mode, Model: model, AR: execution, CommandHash: hash, ExpectedRevision: &expected})
	if e != nil {
		return nil, e
	}
	v, e = h.Service.Get(ctx, p, sid)
	if e != nil {
		return nil, e
	}
	r = *run(&v, r.ID)
	if h.Dispatch != nil && r.Status == "accepted" {
		if e = h.Dispatch(p, sid, r.ID); e != nil {
			return nil, e
		}
	}
	return accepted(v, r), nil
}
func visibleHistory(v Session) []Message {
	// Project through the same branch assembler used by the model. A temporary
	// non-persisted input lets it fold all completed branch edits exactly once.
	temp := Run{ID: uuid.NewString(), MessageID: uuid.NewString()}
	v.Messages = append(append([]Message{}, v.Messages...), Message{ID: temp.MessageID, RunID: temp.ID})
	out := history(v, temp)
	if len(out) > 0 {
		out = out[:len(out)-1]
	}
	return out
}
func revision(s string) (int64, error) {
	if len(s) < 3 || s[0] != '"' || s[len(s)-1] != '"' {
		return 0, arFailure(400, "if_match_required")
	}
	n, e := strconv.ParseInt(s[1:len(s)-1], 10, 64)
	if e != nil || n < 1 {
		return 0, ErrInvalid
	}
	return n, nil
}
func (h *ARHandler) decide(ctx context.Context, p Principal, sid, rid, approval string, d ARDecision) error {
	_, e := h.Service.mutate(ctx, p, sid, func(v *Session) error {
		r := run(v, rid)
		if r == nil || r.AR == nil {
			return ErrNotFound
		}
		c, _ := findCall(r, approval)
		if c == nil || c.ApprovalID != approval {
			return ErrNotFound
		}
		hash := digest(d)
		if c.DecisionID != "" {
			if c.DecisionID == d.ID && c.DecisionHash == hash {
				return nil
			}
			return arFailure(409, "decision_conflict")
		}
		for _, old := range v.Runs {
			for _, st := range old.Steps {
				for _, oc := range st.Calls {
					if oc.DecisionID == d.ID {
						return arFailure(409, "decision_conflict")
					}
				}
			}
		}
		if !p.Permissions["tools.approve"] {
			return ErrForbidden
		}
		t, ok := h.Service.Tools.Lookup(c.Name)
		if !ok || r.Status != "waiting_approval" || r.CancelRequested || r.AuthRevision != p.Revision || r.AR.PolicyRevision != d.PolicyRevision || c.ArgsHash != d.ArgsHash || c.ToolVersion != d.ToolRevision || t.Spec().Version != c.ToolVersion || !p.Permissions[t.Spec().Permission] || !time.Now().Before(c.ApprovalExpires) || !time.Now().Before(r.Deadline) {
			return ErrConflict
		}
		if digest(selectedSpecs(h.Service.Tools, p, *r)) != r.AR.RegistryHash {
			return ErrConflict
		}
		c.DecisionID = d.ID
		c.DecisionHash = hash
		c.Decision = d.Decision
		if d.Decision == "deny" {
			c.State = "denied"
			event(v, r, "approval.resolved", map[string]any{"call_id": c.ID})
			finish(v, r, "failed", "approval_denied")
		} else {
			c.State = "approved"
			r.Status = "accepted"
			event(v, r, "approval.resolved", map[string]any{"call_id": c.ID})
		}
		return nil
	})
	if e != nil {
		return e
	}
	if d.Decision == "allow" && h.Dispatch != nil {
		return h.Dispatch(p, sid, rid)
	}
	return nil
}
