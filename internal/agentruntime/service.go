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
}

func NewService(store SessionStore, model ModelClient, tools ToolRegistry, limits Limits) (*Service, error) {
	if store == nil || model == nil || tools == nil || !limits.valid() || len(limits.Currency) != 3 {
		return nil, ErrInvalid
	}
	return &Service{store, model, tools, limits}, nil
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
	v.Events = append(v.Events, Event{Cursor: int64(len(v.Events) + 1), RunID: r.ID, Type: kind, At: time.Now().UTC(), Data: b})
}
func finish(v *Session, r *Run, status, reason string) {
	if len(r.Steps) > 0 {
		st := &r.Steps[len(r.Steps)-1]
		if st.State != "completed" {
			st.State = status
		}
		for i := range st.Calls {
			c := &st.Calls[i]
			if c.State == "executing" {
				c.State = status
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
	rid, mid := uuid.NewString(), uuid.NewString()
	v, e := s.mutate(ctx, p, id, func(v *Session) error {
		for _, r := range v.Runs {
			if r.ClientID == in.ClientID {
				if r.InputHash != inputHash {
					return ErrConflict
				}
				return nil
			}
		}
		if len(v.Events) > s.Limits.Events-24 || len(v.Messages) >= 2048 {
			return ErrInvalid
		}
		for _, r := range v.Runs {
			if !terminal(r.Status) {
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
		r := Run{ID: rid, MessageID: mid, ClientID: in.ClientID, InputHash: inputHash, AuthRevision: p.Revision, Granted: granted, Mode: in.Mode, Model: in.Model, Status: "queued", Deadline: time.Now().UTC().Add(s.Limits.Duration), Limits: s.Limits, Steps: []Step{}, Checkpoint: Checkpoint{Phase: "ready"}}
		v.Messages = append(v.Messages, Message{ID: mid, Role: "user", RunID: rid, ParentID: in.ParentID, Parts: []Part{{Type: "text", Text: in.Text}}})
		v.Runs = append(v.Runs, r)
		event(v, &v.Runs[len(v.Runs)-1], "run.queued", map[string]any{"message_id": mid})
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
		if r.Status == "queued" || r.Status == "waiting_approval" {
			finish(v, r, "cancelled", "cancelled_before_execution")
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
			r.Status = "queued"
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
			r.Status = "queued"
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
		if m.RunID == r.ID {
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
		if r.Status != "queued" {
			return ErrConflict
		}
		if r.AuthRevision != p.Revision {
			return ErrForbidden
		}
		r.Status = "running"
		r.Executor = token
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
				ep := effective(p, r)
				if !ok || !ep.Permissions[t.Spec().Permission] || t.Spec().Version != c.ToolVersion {
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
				if e = mut(func(v *Session, r *Run) error {
					for i := range r.Steps[len(r.Steps)-1].Calls {
						cc := &r.Steps[len(r.Steps)-1].Calls[i]
						if cc.ID == c.ID {
							cc.State = "completed"
							cc.Result = output
						}
					}
					v.Messages = append(v.Messages, Message{ID: uuid.NewString(), RunID: rid, Role: "tool", Parts: []Part{{Type: "tool_result", CallID: c.ID, Name: c.Name, Text: output}}})
					r.Checkpoint.Phase = "tools"
					r.Checkpoint.PendingCall = ""
					event(v, r, "tool.result", map[string]any{"call_id": c.ID, "output": output})
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
				return nil
			}); e != nil {
				return e
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
		if e = mut(func(v *Session, r *Run) error {
			if r.CancelRequested {
				return context.Canceled
			}
			r.Steps = append(r.Steps, Step{Number: len(r.Steps) + 1, RequestID: requestID, State: "running", Calls: []Call{}})
			r.Checkpoint.Phase = "model_inflight"
			r.Checkpoint.RequestID = requestID
			event(v, r, "step.started", map[string]any{"step": len(r.Steps), "request_id": requestID})
			return nil
		}); e != nil {
			if errors.Is(e, context.Canceled) {
				return stop("cancelled", "cancelled_before_model")
			}
			return e
		}
		r = *run(&v, rid)
		ep := effective(p, r)
		specs := []ToolSpec{}
		if r.Mode == "agent" {
			specs = s.Tools.Specs(ep)
		}
		req := Request{Principal: ep, SessionID: id, RunID: rid, RequestID: requestID, Model: r.Model, Messages: history(v, r), Tools: specs, TokenUpper: r.Limits.Tokens - usedT, MoneyUpper: r.Limits.Money - usedM, Currency: r.Limits.Currency}
		inputBytes := 0
		for _, m := range req.Messages {
			b, _ := json.Marshal(m)
			inputBytes += len(b)
		}
		if inputBytes > r.Limits.InputBytes {
			return stop("limit_reached", "context_limit")
		}
		text := ""
		res, modelErr := s.Model.Generate(work, req, func(delta string) error {
			if work.Err() != nil {
				return work.Err()
			}
			if !utf8.ValidString(delta) || len(text)+len(delta) > r.Limits.OutputBytes {
				return ErrInvalid
			}
			text += delta
			return mut(func(v *Session, r *Run) error {
				if r.CancelRequested {
					return context.Canceled
				}
				if len(v.Events) >= r.Limits.Events-16 {
					return ErrInvalid
				}
				event(v, r, "message.delta", map[string]any{"message_id": messageID, "text": delta, "request_id": requestID})
				return nil
			})
		})
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
		for _, old := range r.Steps {
			for _, c := range old.Calls {
				seen[c.ID] = true
			}
		}
		for i := range res.Calls {
			c := &res.Calls[i]
			t, ok := s.Tools.Lookup(c.Name)
			if !ok || !ep.Permissions[t.Spec().Permission] {
				return stop("failed", "tool_forbidden")
			}
			if c.ID == "" || len(c.ID) > 128 || seen[c.ID] || len(c.Arguments) > r.Limits.InputBytes || validate(t, c.Arguments) != nil {
				return stop("failed", "invalid_tool_call")
			}
			seen[c.ID] = true
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
			r.Usage = aggregate(r.Steps)
			parts := []Part{{Type: "text", Text: text}}
			for _, c := range res.Calls {
				parts = append(parts, Part{Type: "tool_call", CallID: c.ID, Name: c.Name, Arguments: c.Arguments})
				event(v, r, "tool.call", c)
			}
			v.Messages = append(v.Messages, Message{ID: messageID, Role: "assistant", RunID: rid, Parts: parts})
			event(v, r, "usage", map[string]any{"request_id": requestID, "usage": res.Usage, "aggregate": r.Usage})
			event(v, r, "message.completed", map[string]any{"message_id": messageID})
			if res.Finish == "stop" {
				st.State = "completed"
				r.Checkpoint.CompletedSteps = len(r.Steps)
				event(v, r, "step.finished", map[string]any{"step": len(r.Steps)})
				finish(v, r, "completed", "")
			} else {
				r.Checkpoint.Phase = "tools"
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
