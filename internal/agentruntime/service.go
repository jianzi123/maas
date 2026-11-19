package agentruntime

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"sort"
	"strings"
	"time"
	"unicode/utf8"

	"github.com/google/uuid"
)

type Service struct {
	Store  SessionStore
	Model  ModelClient
	Tools  ToolRegistry
	Limits Limits
	// Source-specific bound including system input, schemas and role wrappers.
	CountContext func(context.Context, Request) (int64, error)
	Reauthorize  func(context.Context, Principal) (Principal, error)
}

func NewService(store SessionStore, model ModelClient, tools ToolRegistry, limits Limits) (*Service, error) {
	if store == nil || model == nil || tools == nil || !limits.valid() || len(limits.Currency) != 3 {
		return nil, ErrInvalid
	}
	return &Service{Store: store, Model: model, Tools: tools, Limits: limits}, nil
}
func digest(v any) string {
	b, _ := json.Marshal(v)
	s := sha256.Sum256(b)
	return hex.EncodeToString(s[:])
}
func terminal(s string) bool {
	return s == "completed" || s == "failed" || s == "cancelled" || s == "limit_reached"
}
func authorize(v Session, p Principal) error {
	if p.ID == "" || v.Owner != p.ID || v.Deleted {
		return ErrNotFound
	}
	return nil
}
func run(v *Session, id string) *Run {
	for i := range v.Runs {
		if v.Runs[i].ID == id {
			return &v.Runs[i]
		}
	}
	return nil
}
func event(v *Session, r *Run, kind string, data any) {
	b, _ := json.Marshal(data)
	at := time.Now().UTC()
	wire := projectEvent(v, r, kind, data, at)
	v.Events = append(v.Events, Event{Cursor: int64(len(v.Events) + 1), RunID: r.ID, Type: kind, At: at, Data: b, Wire: wire})
}
func finish(v *Session, r *Run, status, reason string) {
	if r.AR != nil {
		now := time.Now().UTC()
		r.AR.Finished = &now
		for i := range v.Messages {
			if v.Messages[i].RunID == r.ID && v.Messages[i].Status == "partial" {
				v.Messages[i].Status = "interrupted"
			}
		}
	}
	if len(r.Steps) > 0 {
		st := &r.Steps[len(r.Steps)-1]
		if st.State != "completed" {
			st.State = status
		}
		for i := range st.Calls {
			c := &st.Calls[i]
			if c.State == "executing" {
				c.State = status
				if status == "limit_reached" {
					c.State = "failed"
				}
			} else if c.State == "pending" || c.State == "approved" || c.State == "waiting_approval" {
				c.State = "not_executed"
			}
		}
	}
	r.Status = status
	r.Reason = reason
	r.Executor = ""
	r.Checkpoint.Phase = "terminal"
	event(v, r, "run."+status, map[string]any{"reason": reason, "usage": r.Usage})
}
func (s *Service) mutate(ctx context.Context, p Principal, id string, f func(*Session) error) (Session, error) {
	for i := 0; i < 12; i++ {
		v, e := s.Store.Get(ctx, id)
		if e != nil {
			return v, e
		}
		if e = authorize(v, p); e != nil {
			return Session{}, e
		}
		if e = f(&v); e != nil {
			return Session{}, e
		}
		if v.AR != nil {
			v.AR.Updated = time.Now().UTC()
		}
		rev := v.Revision
		v.Revision++
		e = s.Store.CompareAndSwap(ctx, v, rev)
		if errors.Is(e, ErrConflict) {
			continue
		}
		return v, e
	}
	return Session{}, ErrConflict
}
func (s *Service) Create(ctx context.Context, p Principal, title string) (Session, error) {
	if p.ID == "" || p.Revision == "" || len(p.ID) > 128 || len(title) > 256 {
		return Session{}, ErrInvalid
	}
	v := Session{Version: Version, ID: uuid.NewString(), Owner: p.ID, Title: title, Revision: 1, Messages: []Message{}, Runs: []Run{}, Events: []Event{}}
	return v, s.Store.CompareAndSwap(ctx, v, 0)
}
func (s *Service) Get(ctx context.Context, p Principal, id string) (Session, error) {
	v, e := s.Store.Get(ctx, id)
	if e != nil {
		return v, e
	}
	if e = authorize(v, p); e != nil {
		return Session{}, e
	}
	return v, nil
}
func (s *Service) List(ctx context.Context, p Principal) ([]Session, error) {
	if p.ID == "" {
		return nil, ErrForbidden
	}
	return s.Store.List(ctx, p.ID)
}
func (s *Service) Update(ctx context.Context, p Principal, id, title string, deleted bool) error {
	if len(title) > 256 {
		return ErrInvalid
	}
	_, e := s.mutate(ctx, p, id, func(v *Session) error {
		if deleted {
			for _, r := range v.Runs {
				if !terminal(r.Status) {
					return ErrConflict
				}
			}
		}
		v.Title = title
		v.Deleted = deleted
		return nil
	})
	return e
}
func (s *Service) Submit(ctx context.Context, p Principal, id string, in Submit) (Run, error) {
	if p.Revision == "" || len(in.ClientID) == 0 || len(in.ClientID) > 128 || strings.TrimSpace(in.Text) == "" || !utf8.ValidString(in.Text) || len(in.Text) > s.Limits.InputBytes || (in.Mode != "chat" && in.Mode != "agent") || in.Model.Alias == "" || in.Model.Source == "" || in.Model.Revision == "" || (in.Model.Protocol != "text-v1" && in.Model.Protocol != "tools-v1") {
		return Run{}, ErrInvalid
	}
	if in.Mode == "agent" && in.Model.Protocol != "tools-v1" {
		return Run{}, ErrCapability
	}
	if e := s.Model.Supports(ctx, in.Model); e != nil {
		return Run{}, e
	}
	inputHash := digest(in)
	if in.CommandHash != "" {
		inputHash = in.CommandHash
	}
	rid, mid := uuid.NewString(), uuid.NewString()
	v, e := s.mutate(ctx, p, id, func(v *Session) error {
		for _, r := range v.Runs {
			if r.ClientID == in.ClientID {
				if r.InputHash != inputHash {
					if in.AR != nil {
						return arFailure(409, "operation_conflict")
					}
					return ErrConflict
				}
				return nil
			}
		}
		if len(v.Events) > s.Limits.Events-24 || len(v.Messages) >= 2048 {
			return ErrInvalid
		}
		if in.ExpectedRevision != nil && *in.ExpectedRevision != v.Revision {
			return arFailure(409, "revision_conflict")
		}
		for _, r := range v.Runs {
			if !terminal(r.Status) {
				if in.AR != nil {
					return arFailure(409, "conversation_busy")
				}
				return ErrConflict
			}
		}
		if in.ParentID != "" {
			found := false
			for _, m := range v.Messages {
				if m.ID == in.ParentID && m.Role == "user" {
					found = true
				}
			}
			if !found {
				return ErrInvalid
			}
		}
		granted := []string{}
		for k, ok := range p.Permissions {
			if ok {
				granted = append(granted, k)
			}
		}
		sort.Strings(granted)
		effectiveLimits := s.Limits
		if in.AR != nil {
			effectiveLimits = internalLimits(s.Limits, in.AR.Limits)
		}
		if in.Mode == "chat" {
			effectiveLimits.Calls = 1
			effectiveLimits.Steps = 1
		}
		r := Run{ID: rid, MessageID: mid, ClientID: in.ClientID, InputHash: inputHash, AuthRevision: p.Revision, Granted: granted, Mode: in.Mode, Model: in.Model, Status: "accepted", Deadline: time.Now().UTC().Add(effectiveLimits.Duration), Limits: effectiveLimits, Steps: []Step{}, Checkpoint: Checkpoint{Phase: "ready"}, AR: in.AR}
		v.Messages = append(v.Messages, Message{ID: mid, Role: "user", RunID: rid, ParentID: in.ParentID, Parts: []Part{{Type: "text", Text: in.Text}}, Status: "committed", Created: time.Now().UTC()})
		v.Runs = append(v.Runs, r)
		if r.AR != nil {
			current := &v.Runs[len(v.Runs)-1]
			current.AR.ContextHash = digest(history(*v, *current))
			specs := []ToolSpec{}
			for _, spec := range s.Tools.Specs(p) {
				if selectedTool(*current, spec.Name, spec.Version) {
					specs = append(specs, spec)
				}
			}
			current.AR.RegistryHash = digest(specs)
		}
		event(v, &v.Runs[len(v.Runs)-1], "run.accepted", map[string]any{"message_id": mid})
		if r.AR != nil {
			event(v, &v.Runs[len(v.Runs)-1], "message.created", map[string]any{"message_id": mid})
			event(v, &v.Runs[len(v.Runs)-1], "message.completed", map[string]any{"message_id": mid})
		}
		return nil
	})
	if e != nil {
		return Run{}, e
	}
	for _, r := range v.Runs {
		if r.ClientID == in.ClientID {
			return r, nil
		}
	}
	return Run{}, ErrNotFound
}
func (s *Service) Events(ctx context.Context, p Principal, id, rid string, after int64) ([]Event, error) {
	v, e := s.Get(ctx, p, id)
	if e != nil {
		return nil, e
	}
	if run(&v, rid) == nil {
		return nil, ErrNotFound
	}
	if after < 0 || after > int64(len(v.Events)) {
		return nil, ErrInvalid
	}
	out := []Event{}
	for _, x := range v.Events {
		if x.RunID == rid && x.Cursor > after {
			out = append(out, x)
			if len(out) == 200 {
				break
			}
		}
	}
	return out, nil
}
func (s *Service) Cancel(ctx context.Context, p Principal, id, rid string) error {
	_, e := s.mutate(ctx, p, id, func(v *Session) error {
		r := run(v, rid)
		if r == nil {
			return ErrNotFound
		}
		if terminal(r.Status) || r.CancelRequested {
			return nil
		}
		r.CancelRequested = true
		event(v, r, "run.cancel_requested", nil)
		if r.Status == "accepted" || r.Status == "waiting_approval" {
			finish(v, r, "cancelled", "cancelled_before_execution")
		}
		return nil
	})
	return e
}

// Expire is a scheduler action; GET/replay never changes execution state.
func (s *Service) Expire(ctx context.Context, p Principal, sid, rid string) error {
	_, e := s.mutate(ctx, p, sid, func(v *Session) error {
		r := run(v, rid)
		if r == nil {
			return ErrNotFound
		}
		if (r.Status == "accepted" || r.Status == "waiting_approval") && !time.Now().Before(r.Deadline) {
			finish(v, r, "limit_reached", "duration_limit")
		}
		return nil
	})
	return e
}

// Approval is bound to immutable run, call, arguments, tool version, owner and
// authorization revision. It changes state once; duplicate/stale grants conflict.
func (s *Service) Approve(ctx context.Context, p Principal, id, rid, callID, hash string, allow bool) error {
	_, e := s.mutate(ctx, p, id, func(v *Session) error {
		r := run(v, rid)
		if r == nil {
			return ErrNotFound
		}
		if r.Status != "waiting_approval" || r.AuthRevision != p.Revision || !time.Now().Before(r.Deadline) {
			return ErrConflict
		}
		step := &r.Steps[len(r.Steps)-1]
		for i := range step.Calls {
			c := &step.Calls[i]
			if c.ID != callID {
				continue
			}
			t, ok := s.Tools.Lookup(c.Name)
			if !ok || c.State != "waiting_approval" || c.Hash != hash || !time.Now().Before(c.ApprovalExpires) || !p.Permissions[t.Spec().Permission] || t.Spec().Version != c.ToolVersion {
				return ErrConflict
			}
			if !allow {
				c.State = "denied"
				finish(v, r, "failed", "approval_denied")
				return nil
			}
			c.State = "approved"
			r.Status = "accepted"
			r.Executor = ""
			event(v, r, "approval.resolved", map[string]any{"call_id": callID, "allowed": true})
			return nil
		}
		return ErrNotFound
	})
	return e
}

// Recover fences the old executor. It never retries in-flight model or tool work.
// Call only after the owning process has stopped. Pure tools also stop conservatively.
func (s *Service) Recover(ctx context.Context, p Principal, id, rid string) error {
	_, e := s.mutate(ctx, p, id, func(v *Session) error {
		r := run(v, rid)
		if r == nil {
			return ErrNotFound
		}
		if r.Status != "running" {
			return nil
		}
		r.Executor = ""
		if r.Checkpoint.Phase == "model_inflight" || r.Checkpoint.Phase == "tool_inflight" {
			r.Status = "needs_confirmation"
			r.Reason = "execution_outcome_unknown"
			if len(r.Steps) > 0 {
				st := &r.Steps[len(r.Steps)-1]
				st.State = "unknown"
				for i := range st.Calls {
					if st.Calls[i].ID == r.Checkpoint.PendingCall {
						st.Calls[i].State = "unknown"
					}
				}
			}
			event(v, r, "run.needs_confirmation", r.Checkpoint)
		} else {
			r.Status = "accepted"
			event(v, r, "run.recovered", r.Checkpoint)
		}
		return nil
	})
	return e
}
func effective(p Principal, r Run) Principal {
	out := Principal{ID: p.ID, Revision: p.Revision, Permissions: map[string]bool{}}
	for _, k := range r.Granted {
		if p.Permissions[k] {
			out.Permissions[k] = true
		}
	}
	return out
}
func history(v Session, r Run) []Message {
	var current Message
	for _, m := range v.Messages {
		if m.ID == r.MessageID {
			current = m
			break
		}
	}
	// Rebuild the chosen branch, applying each completed edit to its original
	// prefix. Later turns must not append both the original and edited answer.
	memo := map[string][]Message{}
	var before func(string) []Message
	before = func(id string) []Message {
		if cached, ok := memo[id]; ok {
			return append([]Message{}, cached...)
		}
		out := []Message{}
		for _, m := range v.Messages {
			if m.ID == id {
				break
			}
			if m.Status == "partial" || m.Status == "interrupted" {
				continue
			}
			if m.RunID == r.ID {
				continue
			}
			old := run(&v, m.RunID)
			if old == nil || old.Status != "completed" {
				continue
			}
			if m.Role == "user" && m.ParentID != "" {
				out = before(m.ParentID)
			}
			out = append(out, m)
		}
		memo[id] = append([]Message{}, out...)
		return out
	}
	target := current.ID
	if current.ParentID != "" {
		target = current.ParentID
	}
	msgs := before(target)
	for _, m := range v.Messages {
		if m.RunID == r.ID && m.Status != "partial" && m.Status != "interrupted" {
			msgs = append(msgs, m)
		}
	}
	return msgs
}
func (s *Service) Drive(ctx context.Context, p Principal, id, rid string) (result error) {
	token := uuid.NewString()
	v, e := s.mutate(ctx, p, id, func(v *Session) error {
		r := run(v, rid)
		if r == nil {
			return ErrNotFound
		}
		if r.Status != "accepted" {
			return ErrConflict
		}
		if r.AuthRevision != p.Revision {
			return ErrForbidden
		}
		r.Status = "running"
		r.Executor = token
		if r.AR != nil {
			r.AR.Fence++
		}
		event(v, r, "run.started", nil)
		return nil
	})
	if e != nil {
		return e
	}
	r := *run(&v, rid)
	work, cancel := context.WithDeadline(ctx, r.Deadline)
	defer cancel()
	// Durable cancellation reaches whichever replica owns the active transport.
	watchDone := make(chan struct{})
	go func() {
		defer close(watchDone)
		ticker := time.NewTicker(25 * time.Millisecond)
		defer ticker.Stop()
		for {
			select {
			case <-work.Done():
				return
			case <-ticker.C:
				cur, err := s.Get(work, p, id)
				if err != nil {
					cancel()
					return
				}
				cr := run(&cur, rid)
				if cr == nil || cr.CancelRequested || cr.Executor != token {
					cancel()
					return
				}
			}
		}
	}()
	defer func() { cancel(); <-watchDone }()
	mut := func(f func(*Session, *Run) error) error {
		var err error
		persist, persistCancel := context.WithTimeout(context.WithoutCancel(ctx), 5*time.Second)
		defer persistCancel()
		next, mutationErr := s.mutate(persist, p, id, func(v *Session) error {
			r := run(v, rid)
			if r == nil || r.Executor != token || r.Status != "running" {
				return ErrConflict
			}
			return f(v, r)
		})
		err = mutationErr
		if err == nil {
			v = next
		}
		return err
	}
	stop := func(status, reason string) error {
		return mut(func(v *Session, r *Run) error { finish(v, r, status, reason); return nil })
	}
	for {
		r = *run(&v, rid)
		currentPrincipal := p
		if work.Err() != nil {
			status, reason := "failed", "execution_interrupted"
			fresh, err := s.Get(context.WithoutCancel(ctx), p, id)
			if err == nil {
				if cr := run(&fresh, rid); cr != nil && cr.CancelRequested {
					status, reason = "cancelled", "execution_stopped"
				}
			}
			if errors.Is(work.Err(), context.DeadlineExceeded) {
				status, reason = "limit_reached", "duration_limit"
			}
			return stop(status, reason)
		}
		if r.AR != nil {
			if s.Reauthorize == nil {
				return stop("failed", "authorization_unavailable")
			}
			fresh, authErr := s.Reauthorize(work, p)
			if authErr != nil || fresh.ID != p.ID || fresh.Revision != r.AuthRevision {
				return stop("failed", "authorization_changed")
			}
			currentPrincipal = fresh
			if digest(selectedSpecs(s.Tools, currentPrincipal, r)) != r.AR.RegistryHash {
				return stop("failed", "tool_registry_changed")
			}
		}
		if len(v.Events) >= r.Limits.Events-16 {
			return stop("limit_reached", "event_limit")
		}
		if r.Checkpoint.Phase == "tools" {
			step := r.Steps[len(r.Steps)-1]
			pending := false
			for _, c := range step.Calls {
				if c.State == "completed" {
					continue
				}
				pending = true
				t, ok := s.Tools.Lookup(c.Name)
				ep := effective(currentPrincipal, r)
				if !ok || !ep.Permissions[t.Spec().Permission] || t.Spec().Version != c.ToolVersion || !selectedTool(r, c.Name, c.ToolVersion) {
					return stop("failed", "tool_forbidden")
				}
				if t.Spec().Approval && c.State != "approved" {
					return mut(func(v *Session, r *Run) error {
						for i := range r.Steps[len(r.Steps)-1].Calls {
							cc := &r.Steps[len(r.Steps)-1].Calls[i]
							if cc.ID == c.ID {
								cc.State = "waiting_approval"
								cc.ApprovalExpires = time.Now().UTC().Add(r.Limits.ApprovalTTL)
							}
						}
						r.Status = "waiting_approval"
						r.Executor = ""
						event(v, r, "approval.needed", map[string]any{"call_id": c.ID, "sha256": c.Hash, "expires_at": time.Now().UTC().Add(r.Limits.ApprovalTTL)})
						return nil
					})
				}
				if c.State == "approved" && !time.Now().Before(c.ApprovalExpires) {
					return stop("failed", "approval_expired")
				}
				if e = mut(func(v *Session, r *Run) error {
					if r.CancelRequested {
						return context.Canceled
					}
					r.Checkpoint.Phase = "tool_inflight"
					r.Checkpoint.PendingCall = c.ID
					for i := range r.Steps[len(r.Steps)-1].Calls {
						cc := &r.Steps[len(r.Steps)-1].Calls[i]
						if cc.ID == c.ID {
							cc.State = "executing"
							cc.Attempt++
						}
					}
					event(v, r, "tool.started", map[string]any{"call_id": c.ID})
					return nil
				}); e != nil {
					if errors.Is(e, context.Canceled) {
						return stop("cancelled", "cancelled_before_tool")
					}
					return e
				}
				toolCtx, toolCancel := context.WithTimeout(work, r.Limits.ToolTimeout)
				output, toolErr := t.Execute(toolCtx, ep, c.ID, c.Arguments)
				expired := toolCtx.Err()
				toolCancel()
				if toolErr != nil || expired != nil {
					if t.Spec().Effect == "write" {
						return mut(func(v *Session, r *Run) error {
							r.Status, r.Executor, r.Reason = "needs_confirmation", "", "tool_outcome_unknown"
							st := &r.Steps[len(r.Steps)-1]
							st.State = "unknown"
							for i := range st.Calls {
								if st.Calls[i].ID == c.ID {
									st.Calls[i].State = "unknown"
								}
							}
							event(v, r, "run.needs_confirmation", r.Checkpoint)
							return nil
						})
					}
					if work.Err() != nil {
						break
					}
					reason := "tool_failed"
					if errors.Is(expired, context.DeadlineExceeded) {
						reason = "tool_timeout"
					}
					return stop("failed", reason)
				}
				if len(output) > r.Limits.OutputBytes || !utf8.ValidString(output) {
					return stop("failed", "tool_output_limit")
				}
				if r.AR != nil && validateOutput(t, output) != nil {
					return stop("failed", "tool_output_invalid")
				}
				if e = mut(func(v *Session, r *Run) error {
					for i := range r.Steps[len(r.Steps)-1].Calls {
						cc := &r.Steps[len(r.Steps)-1].Calls[i]
						if cc.ID == c.ID {
							cc.State = "completed"
							cc.Result = output
						}
					}
					msg := Message{ID: uuid.NewString(), RunID: rid, Role: "tool", Parts: []Part{{Type: "tool_result", CallID: c.ID, Name: c.Name, Text: output}}, Status: "committed", Created: time.Now().UTC()}
					v.Messages = append(v.Messages, msg)
					r.Checkpoint.Phase = "tools"
					r.Checkpoint.PendingCall = ""
					event(v, r, "tool.result", map[string]any{"call_id": c.ID, "output": output})
					if r.AR != nil {
						event(v, r, "message.created", map[string]any{"message_id": msg.ID})
						event(v, r, "message.completed", map[string]any{"message_id": msg.ID})
						event(v, r, "checkpoint.saved", nil)
					}
					return nil
				}); e != nil {
					return e
				}
				break
			}
			if pending {
				continue
			}
			if e = mut(func(v *Session, r *Run) error {
				r.Steps[len(r.Steps)-1].State = "completed"
				r.Checkpoint = Checkpoint{Phase: "ready", CompletedSteps: len(r.Steps)}
				event(v, r, "step.finished", map[string]any{"step": len(r.Steps)})
				if r.AR != nil {
					proposal := []any{}
					for _, c := range r.Steps[len(r.Steps)-1].Calls {
						proposal = append(proposal, []any{c.Name, c.ArgsHash, c.Result})
					}
					sig := digest(proposal)
					if sig == r.AR.LastSignature {
						r.AR.NoProgress++
					} else {
						r.AR.NoProgress = 0
					}
					r.AR.LastSignature = sig
					if r.AR.NoProgress >= r.AR.Limits.NoProgress {
						finish(v, r, "limit_reached", "no_progress_limit")
					}
					event(v, r, "checkpoint.saved", nil)
				}
				return nil
			}); e != nil {
				return e
			}
			if terminal(run(&v, rid).Status) {
				return nil
			}
			continue
		}
		if r.Checkpoint.Phase != "ready" {
			return stop("failed", "invalid_checkpoint")
		}
		if len(r.Steps) >= r.Limits.Steps || len(r.Steps) >= r.Limits.Calls {
			return stop("limit_reached", "step_or_call_limit")
		}
		usedT, usedM := int64(0), int64(0)
		for _, st := range r.Steps {
			if st.Usage.Tokens == nil || st.Usage.Money == nil {
				return stop("limit_reached", "usage_unknown")
			}
			usedT += *st.Usage.Tokens
			usedM += *st.Usage.Money
		}
		if usedT >= r.Limits.Tokens || usedM >= r.Limits.Money {
			return stop("limit_reached", "budget_limit")
		}
		requestID := uuid.NewString()
		messageID := uuid.NewString()
		ep := effective(currentPrincipal, r)
		specs := []ToolSpec{}
		if r.Mode == "agent" {
			for _, spec := range s.Tools.Specs(ep) {
				if selectedTool(r, spec.Name, spec.Version) {
					specs = append(specs, spec)
				}
			}
		}
		req := Request{Principal: ep, SessionID: id, RunID: rid, RequestID: requestID, Model: r.Model, Messages: history(v, r), Tools: specs, TokenUpper: r.Limits.Tokens - usedT, MoneyUpper: r.Limits.Money - usedM, Currency: r.Limits.Currency}
		contextBytes, _ := json.Marshal(struct {
			Messages []Message
			Tools    []ToolSpec
		}{req.Messages, req.Tools})
		if len(contextBytes) > r.Limits.InputBytes {
			return stop("limit_reached", "context_limit")
		}
		if r.AR != nil {
			req.ContextTokenLimit = int64(r.AR.Limits.ContextTokens)
			if s.CountContext == nil {
				return stop("failed", "context_bound_unavailable")
			}
			bound, boundErr := s.CountContext(work, req)
			if boundErr != nil || bound < 0 {
				return stop("failed", "context_bound_unavailable")
			}
			if bound > req.ContextTokenLimit {
				return stop("limit_reached", "context_limit")
			}
		}
		if e = mut(func(v *Session, r *Run) error {
			if r.CancelRequested {
				return context.Canceled
			}
			r.Steps = append(r.Steps, Step{Number: len(r.Steps) + 1, RequestID: requestID, State: "running", Calls: []Call{}, ID: uuid.NewString(), InputHash: digest(req)})
			r.Checkpoint.Phase = "model_inflight"
			r.Checkpoint.RequestID = requestID
			if r.AR != nil {
				r.AR.ContextHash = digest(req.Messages)
				r.AR.RegistryHash = digest(req.Tools)
				v.Messages = append(v.Messages, Message{ID: messageID, Role: "assistant", RunID: rid, Parts: []Part{{Type: "text", Text: ""}}, Status: "partial", Created: time.Now().UTC()})
				if r.AR.Operation == "regenerate" {
					v.Messages[len(v.Messages)-1].ParentID = r.AR.Reference
				}
				event(v, r, "message.created", map[string]any{"message_id": messageID})
				event(v, r, "checkpoint.saved", nil)
			}
			event(v, r, "step.started", map[string]any{"step": len(r.Steps), "request_id": requestID})
			return nil
		}); e != nil {
			if errors.Is(e, context.Canceled) {
				return stop("cancelled", "cancelled_before_model")
			}
			return e
		}
		r = *run(&v, rid)
		text := ""
		res, modelErr := s.Model.Generate(work, req, func(delta string) error {
			if work.Err() != nil {
				return work.Err()
			}
			if !utf8.ValidString(delta) || len(text)+len(delta) > r.Limits.OutputBytes {
				return ErrInvalid
			}
			offset := len(text)
			text += delta
			return mut(func(v *Session, r *Run) error {
				if r.CancelRequested {
					return context.Canceled
				}
				if len(v.Events) >= r.Limits.Events-16 {
					return ErrInvalid
				}
				if r.AR != nil {
					for i := range v.Messages {
						if v.Messages[i].ID == messageID {
							v.Messages[i].Parts[0].Text = text
						}
					}
				}
				event(v, r, "message.delta", map[string]any{"message_id": messageID, "text": delta, "request_id": requestID, "offset": decimal(int64(offset))})
				return nil
			})
		})
		if r.AR != nil && res.TerminalConfirmed && res.RequestID == requestID {
			if e = mut(func(v *Session, r *Run) error {
				r.Steps[len(r.Steps)-1].Usage = res.Usage
				r.Usage = aggregate(r.Steps)
				event(v, r, "usage", map[string]any{"request_id": requestID, "usage": res.Usage})
				return nil
			}); e != nil {
				return e
			}
		}
		if res.OutcomeUnknown || (r.AR != nil && modelErr == nil && res.Finish != "" && !res.TerminalConfirmed) {
			return mut(func(v *Session, r *Run) error {
				r.Status, r.Executor, r.Reason = "needs_confirmation", "", "model_outcome_unknown"
				r.Steps[len(r.Steps)-1].State = "unknown"
				event(v, r, "run.needs_confirmation", r.Checkpoint)
				return nil
			})
		}
		if work.Err() != nil {
			continue
		} // transport/tool has returned before terminal cancellation
		if modelErr != nil {
			return stop("failed", "model_failed_or_incomplete")
		}
		if res.RequestID != requestID || (res.Finish != "stop" && res.Finish != "tool_calls") || (res.Finish == "stop" && len(res.Calls) > 0) || (res.Finish == "tool_calls" && (len(res.Calls) == 0 || len(res.Calls) > 16 || r.Mode != "agent" || r.Model.Protocol != "tools-v1")) {
			return stop("failed", "model_protocol_error")
		}
		if res.Usage.Tokens != nil && (*res.Usage.Tokens < 0 || *res.Usage.Tokens > req.TokenUpper) || res.Usage.Money != nil && (*res.Usage.Money < 0 || *res.Usage.Money > req.MoneyUpper || res.Usage.Currency != req.Currency) {
			return stop("failed", "model_budget_bound_violated")
		}
		seen := map[string]bool{}
		priorCalls := 0
		for _, old := range r.Steps {
			for _, c := range old.Calls {
				priorCalls++
				key := c.SourceID
				if key == "" {
					key = c.ID
				}
				seen[key] = true
			}
		}
		if r.AR != nil && priorCalls+len(res.Calls) > r.AR.Limits.Tools {
			return stop("limit_reached", "tool_call_limit")
		}
		for i := range res.Calls {
			c := &res.Calls[i]
			t, ok := s.Tools.Lookup(c.Name)
			if !ok || !ep.Permissions[t.Spec().Permission] || !selectedTool(r, c.Name, t.Spec().Version) {
				return stop("failed", "tool_forbidden")
			}
			if c.ID == "" || len(c.ID) > 128 || seen[c.ID] || len(c.Arguments) > r.Limits.InputBytes || validate(t, c.Arguments) != nil {
				return stop("failed", "invalid_tool_call")
			}
			seen[c.ID] = true
			if r.AR != nil {
				c.SourceID = c.ID
				c.ID = uuid.NewString()
				c.Effect = t.Spec().Effect
				c.Arguments = mustCanonical(c.Arguments)
				c.ArgsHash = rawHash(mustCanonical(c.Arguments))
				c.ApprovalID = uuid.NewString()
			}
			c.State = "pending"
			c.Result = ""
			c.ToolVersion = t.Spec().Version
			c.Hash = digest([]any{Version, id, rid, p.ID, r.AuthRevision, c.ID, c.Name, c.ToolVersion, json.RawMessage(c.Arguments)})
			c.ApprovalExpires = time.Time{}
		}
		if len(v.Events)+len(res.Calls)+7 > r.Limits.Events {
			return stop("limit_reached", "event_limit")
		}
		if e = mut(func(v *Session, r *Run) error {
			st := &r.Steps[len(r.Steps)-1]
			st.Calls = res.Calls
			st.Usage = res.Usage
			st.OutputHash = digest([]any{text, res.Calls})
			r.Usage = aggregate(r.Steps)
			parts := []Part{{Type: "text", Text: text}}
			for _, c := range res.Calls {
				parts = append(parts, Part{Type: "tool_call", CallID: c.ID, Name: c.Name, Arguments: c.Arguments})
				event(v, r, "tool.call", c)
			}
			if r.AR == nil {
				v.Messages = append(v.Messages, Message{ID: messageID, Role: "assistant", RunID: rid, Parts: parts})
			} else {
				for i := range v.Messages {
					if v.Messages[i].ID == messageID {
						v.Messages[i].Parts = parts
						v.Messages[i].Status = "committed"
					}
				}
			}
			if r.AR == nil {
				event(v, r, "usage", map[string]any{"request_id": requestID, "usage": res.Usage, "aggregate": r.Usage})
			}
			event(v, r, "message.completed", map[string]any{"message_id": messageID})
			if res.Finish == "stop" {
				st.State = "completed"
				r.Checkpoint.CompletedSteps = len(r.Steps)
				event(v, r, "step.finished", map[string]any{"step": len(r.Steps)})
				finish(v, r, "completed", "")
			} else {
				r.Checkpoint.Phase = "tools"
			}
			if r.AR != nil {
				event(v, r, "checkpoint.saved", nil)
			}
			return nil
		}); e != nil {
			return e
		}
		if run(&v, rid).Status == "completed" {
			return nil
		}
	}
}
func aggregate(steps []Step) Usage {
	t, m := int64(0), int64(0)
	tk, mk := true, true
	for _, s := range steps {
		if s.Usage.Tokens == nil {
			tk = false
		} else {
			t += *s.Usage.Tokens
		}
		if s.Usage.Money == nil {
			mk = false
		} else {
			m += *s.Usage.Money
		}
	}
	u := Usage{}
	if len(steps) > 0 {
		u.Currency = steps[0].Usage.Currency
	}
	if tk {
		u.Tokens = &t
	}
	if mk {
		u.Money = &m
	}
	return u
}
