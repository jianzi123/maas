package kernelmodel

import (
	"bytes"
	"context"
	"encoding/json"
	"io"
	"net/http"
	"strconv"
	"strings"
	"time"

	a "github.com/jianzi123/maas/internal/agentruntime"
	"github.com/jianzi123/maas/internal/kernel"
	"github.com/jianzi123/maas/internal/protocol"
	"github.com/jianzi123/maas/internal/toolwire"
)

// RelayModel consumes the existing protected Relay. Prepare must use the original
// approved Key/profile/ticket/plan factory, bound to the trusted principal. There
// is no URL, credential, new ledger, direct provider client or fallback here.
// Until that installation factory is supplied this adapter fails closed.
type RelayModel struct {
	Relay   *kernel.Relay
	Prepare func(context.Context, a.Request) (kernel.RelayCall, error)
	// Usage reads the unique durable accounting record, including currency/price
	// approval, and returns only the run's already-approved currency's atomic value.
	Usage func(context.Context, string) (a.Usage, error)
	// FailureResolved consults the original durable request identity. Absent or
	// unavailable proof remains unknown and cannot unlock the Session barrier.
	FailureResolved func(context.Context, string) (bool, error)
}

func (m RelayModel) Supports(_ context.Context, v a.Model) error {
	if v.Protocol != "text-v1" && v.Protocol != "tools-v1" {
		return a.ErrCapability
	}
	if m.Relay == nil || m.Prepare == nil || m.Usage == nil {
		return a.ErrUnavailable
	}
	return nil
}
func (m RelayModel) Generate(ctx context.Context, req a.Request, emit func(string) error) (a.Response, error) {
	out := a.Response{RequestID: req.RequestID}
	if e := m.Supports(ctx, req.Model); e != nil {
		return out, e
	}
	if len(req.Tools) != 0 && req.Model.Protocol != "tools-v1" {
		return out, a.ErrCapability
	}
	call, e := m.Prepare(ctx, req)
	if e != nil {
		return out, e
	}
	if call.Input.RequestID != req.RequestID || call.Input.Profile.Alias != req.Model.Alias || call.Input.Profile.SourceID != req.Model.Source || call.Input.Profile.ConfigRevision != req.Model.Revision || !call.Stream {
		return out, a.ErrConflict
	}
	if e = checkPlan(req, call.Input.Plan); e != nil {
		return out, e
	}
	if call.Protocol != req.Model.Protocol && !(req.Model.Protocol == "text-v1" && call.Protocol == "") {
		return out, a.ErrConflict
	}
	if req.Model.Protocol == "tools-v1" && (call.Protocol != "tools-v1" || !call.Input.Profile.SupportsTools()) {
		return out, a.ErrCapability
	}
	w := &relayWriter{header: http.Header{}, emit: emit}
	if req.Model.Protocol == "tools-v1" {
		w.tools = &toolwire.Stream{}
		w.model = req.Model.Alias
	}
	e = m.Relay.Forward(ctx, w, call)
	if e != nil {
		out.OutcomeUnknown = true
		if m.FailureResolved != nil {
			proof, cancel := context.WithTimeout(context.WithoutCancel(ctx), 5*time.Second)
			resolved, resolveErr := m.FailureResolved(proof, req.RequestID)
			cancel()
			if resolveErr == nil && resolved {
				out.OutcomeUnknown = false
				out.TerminalConfirmed = true
			}
		}
		if out.TerminalConfirmed {
			read, cancel := context.WithTimeout(context.WithoutCancel(ctx), 5*time.Second)
			usage, readErr := m.Usage(read, req.RequestID)
			cancel()
			if readErr == nil {
				out.Usage = usage
			}
		}
		return out, e
	}
	if w.err != nil {
		return out, w.err
	}
	if !w.done || len(bytes.TrimSpace(w.pending)) != 0 {
		return out, io.ErrUnexpectedEOF
	}
	out.Finish = "stop"
	if w.tools != nil {
		out.Finish = w.tools.Finish
	}
	out.Usage, e = m.Usage(ctx, req.RequestID)
	out.TerminalConfirmed = e == nil
	if e != nil {
		out.OutcomeUnknown = true
	}
	if e == nil && w.tools != nil {
		if out.Finish != "stop" && out.Finish != "tool_calls" {
			return out, a.ErrInvalid
		}
		for _, c := range w.tools.Calls {
			args, err := protocol.CanonicalToolJSON([]byte(c.Arguments))
			if err != nil || len(args) == 0 || args[0] != '{' {
				return out, a.ErrInvalid
			}
			out.Calls = append(out.Calls, a.Call{ID: c.ID, Name: c.Name, Arguments: args})
		}
	}
	return out, e
}

func checkPlan(req a.Request, p kernel.Plan) error {
	within := func(n *string, limit int64) bool {
		if n == nil || limit < 1 {
			return false
		}
		value, e := strconv.ParseInt(*n, 10, 64)
		return e == nil && value >= 0 && value <= limit
	}
	if !within(p.Tokens, req.TokenUpper) || !within(p.Money, req.MoneyUpper) || p.Currency == nil || *p.Currency != req.Currency {
		return a.ErrInvalid
	}
	if req.ContextTokenLimit > 0 && !within(p.Input, req.ContextTokenLimit) {
		return a.ErrInvalid
	}
	return nil
}

type relayWriter struct {
	tools   *toolwire.Stream
	model   string
	header  http.Header
	status  int
	pending []byte
	emit    func(string) error
	err     error
	done    bool
}

func (w *relayWriter) Header() http.Header { return w.header }
func (w *relayWriter) WriteHeader(n int)   { w.status = n }
func (w *relayWriter) Flush()              {}
func (w *relayWriter) Write(b []byte) (int, error) {
	if w.err != nil {
		return 0, w.err
	}
	if w.status >= 400 {
		w.err = a.ErrUnavailable
		return 0, w.err
	}
	w.pending = append(w.pending, b...)
	if len(w.pending) > 2<<20 {
		w.err = a.ErrInvalid
		return 0, w.err
	}
	for {
		idx := bytes.Index(w.pending, []byte("\n\n"))
		if idx < 0 {
			break
		}
		frame := string(w.pending[:idx])
		w.pending = w.pending[idx+2:]
		if strings.HasPrefix(frame, "event: error") {
			w.err = a.ErrUnavailable
			return 0, w.err
		}
		for _, line := range strings.Split(frame, "\n") {
			if !strings.HasPrefix(line, "data: ") {
				continue
			}
			data := strings.TrimPrefix(line, "data: ")
			if w.done {
				w.err = a.ErrInvalid
				return 0, w.err
			}
			if data == "[DONE]" {
				w.done = true
				continue
			}
			if w.tools != nil {
				if _, _, e := w.tools.Push([]byte(data), w.model); e != nil {
					w.err = e
					return 0, e
				}
			}
			var value struct {
				Choices []struct {
					Delta struct {
						Content string `json:"content"`
					} `json:"delta"`
				} `json:"choices"`
			}
			if json.Unmarshal([]byte(data), &value) != nil {
				w.err = a.ErrInvalid
				return 0, w.err
			}
			for _, c := range value.Choices {
				if c.Delta.Content != "" {
					if w.err = w.emit(c.Delta.Content); w.err != nil {
						return 0, w.err
					}
				}
			}
		}
	}
	return len(b), nil
}
