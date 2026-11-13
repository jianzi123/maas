package kernel

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"github.com/google/uuid"
	"github.com/jianzi123/maas/internal/protocol"
	"io"
	"net/http"
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

// Forward emits only the stable public schema. Raw provider usage is diagnostic
// until the one successful terminal is confirmed; it is never a public midstream
// accounting claim. No redirect, retry, fallback or direct supplier path exists.
func (r *Relay) Forward(ctx context.Context, w http.ResponseWriter, call RelayCall) error {
	if r == nil || r.core == nil || r.client == nil || r.endpoint == "" || len(call.Body) == 0 || int64(len(call.Body)) > r.maxBytes || !validUUID(call.Input.RequestID) {
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
	w.Header().Set("X-Request-ID", call.Input.RequestID)
	diagnostic := &relayDiagnostics{core: r.core, call: call}
	wrote := false
	finalCode := ""
	finish := func(result string, usage Usage, first *int64) error {
		terminalCtx, done := context.WithTimeout(context.Background(), 5*time.Second)
		defer done()
		snap, state, e := r.core.ReadRequest(terminalCtx, call.Input.RequestID)
		if e != nil || state != "in_progress" || snap.Input.Owner != call.Input.Owner || snap.OwnerFence != 1 {
			return ErrUnavailable
		}
		f := Final{ErrorCode: finalCode, EventID: uuid.NewSHA1(uuid.NameSpaceOID, []byte(call.Input.RequestID+"/owner-terminal")).String(), RequestID: call.Input.RequestID, Owner: call.Input.Owner, OwnerFence: 1, Result: result, Usage: usage, FirstChunkMS: first, Submitted: result == "succeeded"}
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
		err := finish(result, usage, first)
		if diagErr != nil {
			return ErrUnavailable
		}
		return err
	}
	errorOutput := func(code string) {
		b, _ := json.Marshal(publicError(call.Input, code))
		if call.Stream && wrote {
			_, _ = io.WriteString(w, "event: error\ndata: "+string(b)+"\n\n")
			if flush, ok := w.(http.Flusher); ok {
				flush.Flush()
			}
		} else {
			w.Header().Set("Content-Type", "application/json")
			status := 502
			if code == "upstream_timeout" {
				status = 504
			}
			if code == "accounting_unavailable" {
				status = 503
			}
			w.WriteHeader(status)
			_, _ = w.Write(b)
		}
	}
	abort := func(cause, result, reason, code string, first *int64) error {
		finalCode = code
		_ = end(cause, result, unknown(reason), first)
		errorOutput(code)
		return ErrUnavailable
	}
	receiptFailure := func(err error, first *int64) error {
		cancel()
		finalCode = "accounting_unavailable"
		if errors.Is(err, ErrDiagnosticLimit) {
			_ = end("diagnostic_limit", "failed", unavailableUsage("not_provided"), first)
		} else {
			_ = finish("failed", unavailableUsage("not_provided"), first)
		}
		errorOutput(finalCode)
		return ErrUnavailable
	}
	writeChunk := func(value map[string]any) error {
		b, _ := json.Marshal(value)
		w.Header().Set("Content-Type", "text/event-stream")
		n, err := io.WriteString(w, "data: "+string(b)+"\n\n")
		if n > 0 {
			wrote = true
		}
		if flush, ok := w.(http.Flusher); ok {
			flush.Flush()
		}
		return err
	}
	resp, sendErr := r.client.Do(req)
	if sendErr != nil {
		result, reason := relayFailure(ctx, sendCtx, sendErr, "interrupted")
		cause, code := "eof", "upstream_error"
		if result == "timed_out" {
			cause, code = "deadline_exceeded", "upstream_timeout"
		} else if result == "cancelled" {
			cause, code = "explicit_cancel", "client_cancelled"
		}
		return abort(cause, result, reason, code, nil)
	}
	defer resp.Body.Close()
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		finalCode = "upstream_error"
		_ = finish("failed", unknown("not_provided"), nil)
		errorOutput(finalCode)
		return ErrUnavailable
	}
	if !call.Stream {
		body, err := io.ReadAll(io.LimitReader(resp.Body, r.maxBytes+1))
		if err != nil || int64(len(body)) > r.maxBytes {
			result, reason := relayFailure(ctx, sendCtx, err, "failed")
			cause, code := "eof", "upstream_error"
			if result == "timed_out" {
				cause, code = "deadline_exceeded", "upstream_timeout"
			} else if result == "cancelled" {
				cause, code = "explicit_cancel", "client_cancelled"
			}
			return abort(cause, result, reason, code, nil)
		}
		usage, ok, err := parseUsage(body)
		if err != nil {
			return abort("parse_invalid", "failed", "not_provided", "upstream_protocol_error", nil)
		}
		if !ok {
			usage = unavailableUsage("not_provided")
		} else if err = diagnostic.append("receipt", &usage, ""); err != nil {
			return receiptFailure(err, nil)
		}
		if _, err = normalizeResponse(body, call.Input, usage); err != nil {
			return abort("parse_invalid", "failed", "not_provided", "upstream_protocol_error", nil)
		}
		usage = approvedResponseUsage(call.Input.Profile.UsagePolicy, usage)
		if err = end("normal_completion", "succeeded", usage, nil); err != nil {
			errorOutput("accounting_unavailable")
			return err
		}
		terminalCtx, done := context.WithTimeout(context.Background(), 5*time.Second)
		defer done()
		finalUsage, err := r.core.successfulUsage(terminalCtx, call.Input.RequestID)
		if err != nil {
			errorOutput("accounting_unavailable")
			return err
		}
		out, err := normalizeResponse(body, call.Input, finalUsage)
		if err != nil {
			return ErrUnavailable
		}
		b, _ := json.Marshal(out)
		w.Header().Set("Content-Type", "application/json")
		_, err = w.Write(b)
		if err != nil {
			_ = diagnostic.append("termination", nil, "client_write_error")
		}
		return err
	}
	reader := newPublicEventReader(resp.Body, r.maxLine, r.maxBytes)
	authority := usageAuthority{policy: call.Input.Profile.UsagePolicy}
	var first *int64
	seenFinish, seenDone := false, false
	for {
		data, err := reader.Next()
		if err != nil {
			if err == io.EOF && seenDone && seenFinish {
				break
			}
			result, reason := relayFailure(ctx, sendCtx, err, "interrupted")
			cause, code := "eof", "upstream_error"
			if result == "timed_out" {
				cause, code = "deadline_exceeded", "upstream_timeout"
			} else if result == "cancelled" {
				cause, code = "explicit_cancel", "client_cancelled"
			} else if errors.Is(err, ErrConflict) {
				cause, code, result = "parse_invalid", "upstream_protocol_error", "failed"
			}
			return abort(cause, result, reason, code, first)
		}
		if seenDone {
			return abort("parse_invalid", "failed", "not_provided", "upstream_protocol_error", first)
		}
		if string(data) == "[DONE]" {
			if !seenFinish {
				return abort("parse_invalid", "failed", "not_provided", "upstream_protocol_error", first)
			}
			seenDone = true
			continue
		}
		u, ok, parseErr := parseUsage(data)
		if parseErr != nil {
			cancel()
			return abort("parse_invalid", "failed", "not_provided", "upstream_protocol_error", first)
		}
		if ok {
			if err = diagnostic.append("receipt", &u, ""); err != nil {
				return receiptFailure(err, first)
			}
			if authority.observe(u) != nil {
				cancel()
				return abort("usage_conflict", "failed", "not_provided", "upstream_protocol_error", first)
			}
		}
		out, finished, err := normalizeChunk(data, call.Input)
		if err != nil {
			cancel()
			return abort("parse_invalid", "failed", "not_provided", "upstream_protocol_error", first)
		}
		seenFinish = seenFinish || finished
		if finished {
			authority.finish()
		}
		if sendCtx.Err() != nil {
			result, reason := relayFailure(ctx, sendCtx, sendCtx.Err(), "interrupted")
			cause, code := "deadline_exceeded", "upstream_timeout"
			if result == "cancelled" {
				cause, code = "explicit_cancel", "client_cancelled"
			}
			return abort(cause, result, reason, code, first)
		}
		if first == nil {
			ms := time.Since(call.Input.Received).Milliseconds()
			first = &ms
		}
		if err = writeChunk(out); err != nil {
			result, reason := relayFailure(ctx, sendCtx, err, "cancelled")
			cancel()
			return abort("client_write_error", result, reason, "client_cancelled", first)
		}
	}
	if e = end("normal_completion", "succeeded", authority.result(), first); e != nil {
		errorOutput("accounting_unavailable")
		return e
	}
	terminalCtx, done := context.WithTimeout(context.Background(), 5*time.Second)
	defer done()
	finalUsage, e := r.core.successfulUsage(terminalCtx, call.Input.RequestID)
	if e != nil {
		errorOutput("accounting_unavailable")
		return e
	}
	out := publicRoot(call.Input, true)
	out["choices"] = []any{}
	out["usage"] = finalUsage
	if protocol.Validate("ChatChunk", out) != nil {
		return ErrUnavailable
	}
	if e = writeChunk(out); e != nil {
		_ = diagnostic.append("termination", nil, "client_write_error")
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
