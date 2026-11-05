package kernel

import (
	"bufio"
	"bytes"
	"context"
	"errors"
	"github.com/google/uuid"
	"io"
	"net/http"
	"strings"
	"time"
)

type relayDiagnostics struct {
	core     *Store
	call     RelayCall
	loaded   bool
	snap     Snapshot
	digest   string
	sequence int64
	received bool
}

func (d *relayDiagnostics) append(kind string, u *Usage, cause string) error {
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	if !d.loaded {
		var e error
		d.snap, d.digest, e = d.core.DiagnosticBinding(ctx, d.call.Input.RequestID, d.call.Input.Owner)
		if e != nil {
			return e
		}
		if d.snap.OwnerFence != 1 {
			return ErrConflict
		}
		d.loaded = true
	}
	var counts *DiagnosticCounts
	var reason *string
	if u != nil {
		counts = &DiagnosticCounts{u.Input, u.Output, u.Total, u.Cached, u.Reasoning}
	}
	if cause != "" {
		reason = ptr(cause)
	}
	record := Diagnostic{Version: "0.1-draft.1", Type: kind, ID: uuid.NewString(), RequestID: d.call.Input.RequestID, Owner: d.call.Input.Owner, Fence: d.snap.OwnerFence, Sequence: d.sequence + 1, Observed: time.Now().UTC(), SnapshotHash: d.digest, Binding: requestProjection(d.snap, "in_progress", nil)["invocation_binding"], Authority: "diagnostic_only", Usage: counts, Cause: reason}
	if e := d.core.AppendDiagnostic(ctx, record); e != nil {
		return e
	}
	d.sequence++
	if kind == "receipt" {
		d.received = true
	}
	return nil
}

// Forward uses the one approved private gateway. Diagnostic receipts commit
// before frame forwarding; observations never become final usage on interruption.
func (r *Relay) Forward(ctx context.Context, w http.ResponseWriter, call RelayCall) error {
	if r == nil || r.core == nil || r.client == nil || r.endpoint == "" || len(call.Body) == 0 || int64(len(call.Body)) > r.maxBytes {
		return ErrUnavailable
	}
	sendCtx, cancel := context.WithDeadline(ctx, call.Input.Deadline)
	defer cancel()
	req, e := http.NewRequestWithContext(sendCtx, "POST", r.endpoint+"/v1/chat/completions", bytes.NewReader(call.Body))
	if e != nil {
		return ErrUnavailable
	}
	req.GetBody = nil
	req.Host = call.Input.Profile.Host
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("X-Request-ID", call.Input.RequestID)
	req.Header.Set("X-Maas-Admission-Ticket", call.Ticket)
	req.Header.Set("X-Maas-Reservation-Plan", call.PlanHeader)
	diagnostic := &relayDiagnostics{core: r.core, call: call}
	finish := func(result string, usage Usage, first *int64) error {
		terminalCtx, done := context.WithTimeout(context.Background(), 5*time.Second)
		defer done()
		snap, state, e := r.core.ReadRequest(terminalCtx, call.Input.RequestID)
		if e != nil || state != "in_progress" || snap.Input.Owner != call.Input.Owner || snap.OwnerFence != 1 {
			return ErrUnavailable
		}
		f := Final{EventID: uuid.NewSHA1(uuid.NameSpaceOID, []byte(call.Input.RequestID+"/owner-terminal")).String(), RequestID: call.Input.RequestID, Owner: call.Input.Owner, OwnerFence: 1, Result: result, Usage: usage, FirstChunkMS: first, Submitted: result == "succeeded"}
		if e = r.core.Finalize(terminalCtx, f); e != nil {
			return e
		}
		_, state, e = r.core.ReadRequest(terminalCtx, call.Input.RequestID)
		if e != nil {
			return e
		}
		if result == "succeeded" && state != "succeeded" {
			return ErrUnavailable
		}
		return nil
	}
	unknown := func(reason string) Usage {
		if diagnostic.received {
			reason = "not_provided"
		}
		return unavailableUsage(reason)
	}
	end := func(cause, result string, usage Usage, first *int64) error {
		diagErr := diagnostic.append("termination", nil, cause)
		if diagErr != nil {
			if result == "succeeded" {
				result = "failed"
			}
			usage = unavailableUsage("not_provided")
		}
		finalErr := finish(result, usage, first)
		if diagErr != nil {
			return ErrUnavailable
		}
		return finalErr
	}
	receiptFailure := func(err error, first *int64) error {
		cancel()
		if errors.Is(err, ErrDiagnosticLimit) {
			_ = end("diagnostic_limit", "failed", unavailableUsage("not_provided"), first)
		} else {
			_ = finish("failed", unavailableUsage("not_provided"), first)
		}
		return ErrUnavailable
	}
	resp, sendErr := r.client.Do(req)
	if sendErr != nil {
		result, reason := relayFailure(ctx, sendCtx, sendErr, "interrupted")
		if result == "timed_out" {
			_ = end("deadline_exceeded", result, unknown(reason), nil)
		} else if result == "cancelled" {
			_ = end("explicit_cancel", result, unknown(reason), nil)
		} else {
			_ = finish(result, unknown(reason), nil)
		}
		return ErrUnavailable
	}
	defer resp.Body.Close()
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		_ = finish("failed", unknown("not_provided"), nil)
		return ErrUnavailable
	}
	if !call.Stream {
		body, e := io.ReadAll(io.LimitReader(resp.Body, r.maxBytes+1))
		if e != nil || int64(len(body)) > r.maxBytes {
			result, reason := relayFailure(ctx, sendCtx, e, "failed")
			cause := "eof"
			if result == "timed_out" {
				cause = "deadline_exceeded"
			} else if result == "cancelled" {
				cause = "explicit_cancel"
			}
			_ = end(cause, result, unknown(reason), nil)
			return ErrUnavailable
		}
		usage, ok, e := parseUsage(body)
		if e != nil {
			_ = end("parse_invalid", "failed", unknown("not_provided"), nil)
			return ErrUnavailable
		}
		if !ok {
			usage = unavailableUsage("not_provided")
		} else if e = diagnostic.append("receipt", &usage, ""); e != nil {
			return receiptFailure(e, nil)
		}
		if e = end("normal_completion", "succeeded", usage, nil); e != nil {
			return e
		}
		w.Header().Set("Content-Type", "application/json")
		w.Header().Set("X-Request-ID", call.Input.RequestID)
		_, e = w.Write(body)
		if e != nil {
			_ = diagnostic.append("termination", nil, "client_write_error")
		}
		return e
	}
	w.Header().Set("Content-Type", "text/event-stream")
	w.Header().Set("X-Request-ID", call.Input.RequestID)
	scanner := bufio.NewScanner(io.LimitReader(resp.Body, r.maxBytes+1))
	scanner.Buffer(make([]byte, 4096), r.maxLine)
	usage := unavailableUsage("not_provided")
	var first *int64
	var total int64
	for scanner.Scan() {
		line := scanner.Text()
		total += int64(len(line) + 1)
		if total > r.maxBytes {
			cancel()
			_ = end("parse_invalid", "failed", unknown("interrupted_before_usage"), first)
			return ErrUnavailable
		}
		if strings.HasPrefix(line, "data:") {
			data := strings.TrimSpace(strings.TrimPrefix(line, "data:"))
			if data == "[DONE]" {
				if e = end("normal_completion", "succeeded", usage, first); e != nil {
					return e
				}
				_, e = io.WriteString(w, "data: [DONE]\n\n")
				if e != nil {
					_ = diagnostic.append("termination", nil, "client_write_error")
				}
				if flush, ok := w.(http.Flusher); ok {
					flush.Flush()
				}
				return e
			}
			if data != "" {
				u, ok, parseErr := parseUsage([]byte(data))
				if parseErr != nil {
					cancel()
					_ = end("parse_invalid", "failed", unknown("not_provided"), first)
					return ErrUnavailable
				}
				if ok {
					if usage.Source == "upstream" && !monotonicUsage(usage, u) {
						cancel()
						_ = end("usage_conflict", "failed", unknown("not_provided"), first)
						return ErrUnavailable
					}
					if e = diagnostic.append("receipt", &u, ""); e != nil {
						return receiptFailure(e, first)
					}
					usage = u
				}
			}
		}
		// A context may expire during the diagnostic commit; classify it before any
		// cleanup cancel and before forwarding another frame.
		if sendCtx.Err() != nil {
			result, reason := relayFailure(ctx, sendCtx, sendCtx.Err(), "interrupted")
			cause := "deadline_exceeded"
			if result == "cancelled" {
				cause = "explicit_cancel"
			}
			_ = end(cause, result, unknown(reason), first)
			return ErrUnavailable
		}
		if first == nil && line != "" {
			ms := time.Since(call.Input.Received).Milliseconds()
			first = &ms
		}
		if _, e = io.WriteString(w, line+"\n"); e != nil {
			result, reason := relayFailure(ctx, sendCtx, e, "cancelled")
			cancel()
			_ = end("client_write_error", result, unknown(reason), first)
			return ErrUnavailable
		}
		if flush, ok := w.(http.Flusher); ok {
			flush.Flush()
		}
	}
	result, reason := relayFailure(ctx, sendCtx, scanner.Err(), "interrupted")
	cause := "eof"
	if result == "timed_out" {
		cause = "deadline_exceeded"
	} else if result == "cancelled" {
		cause = "explicit_cancel"
	}
	_ = end(cause, result, unknown(reason), first)
	return ErrUnavailable
}
