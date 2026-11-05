package kernel

import (
	"bufio"
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"github.com/google/uuid"
	"io"
	"net/http"
	"net/url"
	"strings"
	"time"
)

// Relay has one installation-approved PRIVATE Higress endpoint. It never takes
// a supplier URL from a caller/profile and has no fallback, redirect or retry.
// No binary exposes it while the real H1-H4/registry chain is unavailable.
type Relay struct {
	core     *Store
	endpoint string
	client   *http.Client
	maxBytes int64
	maxLine  int
}

func NewRelay(core *Store, endpoint string, transport *http.Transport, maxBytes int64, maxLine int) (*Relay, error) {
	u, e := url.Parse(endpoint)
	if core == nil || e != nil || u.Scheme != "https" || u.Host == "" || u.User != nil || u.RawQuery != "" || u.Fragment != "" || (u.Path != "" && u.Path != "/") || transport == nil || transport.TLSClientConfig == nil || transport.TLSClientConfig.InsecureSkipVerify || len(transport.TLSClientConfig.Certificates) == 0 || maxBytes < 1 || maxBytes > 16<<20 || maxLine < 1 || maxLine > 1<<20 {
		return nil, ErrUnavailable
	}
	return &Relay{core: core, endpoint: strings.TrimSuffix(endpoint, "/"), client: &http.Client{Transport: transport, CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }}, maxBytes: maxBytes, maxLine: maxLine}, nil
}

type RelayCall struct {
	Input              Input
	Body               []byte
	Ticket, PlanHeader string
	Stream             bool
}

func unavailableUsage(reason string) Usage { return Usage{Source: "unavailable", Missing: ptr(reason)} }
func parseUsage(body []byte) (Usage, bool, error) {
	var envelope map[string]json.RawMessage
	if json.Unmarshal(body, &envelope) != nil {
		return Usage{}, false, ErrConflict
	}
	raw, exists := envelope["usage"]
	if !exists || string(raw) == "null" {
		return Usage{}, false, nil
	}
	var v map[string]json.RawMessage
	if json.Unmarshal(raw, &v) != nil {
		return Usage{}, false, ErrConflict
	}
	u := Usage{Source: "upstream"}
	read := func(m map[string]json.RawMessage, k string) (*int64, error) {
		b, ok := m[k]
		if !ok || string(b) == "null" {
			return nil, nil
		}
		var n int64
		if json.Unmarshal(b, &n) != nil || n < 0 || n > maxCounter {
			return nil, ErrConflict
		}
		return &n, nil
	}
	var e error
	if u.Input, e = read(v, "prompt_tokens"); e != nil {
		return u, false, e
	}
	if u.Output, e = read(v, "completion_tokens"); e != nil {
		return u, false, e
	}
	if u.Total, e = read(v, "total_tokens"); e != nil {
		return u, false, e
	}
	var details map[string]json.RawMessage
	if b, ok := v["prompt_tokens_details"]; ok && string(b) != "null" {
		if json.Unmarshal(b, &details) != nil {
			return u, false, ErrConflict
		}
		if u.Cached, e = read(details, "cached_tokens"); e != nil {
			return u, false, e
		}
	}
	details = nil
	if b, ok := v["completion_tokens_details"]; ok && string(b) != "null" {
		if json.Unmarshal(b, &details) != nil {
			return u, false, ErrConflict
		}
		if u.Reasoning, e = read(details, "reasoning_tokens"); e != nil {
			return u, false, e
		}
	}
	if u.Input == nil && u.Output == nil && u.Total == nil && u.Cached == nil && u.Reasoning == nil {
		return Usage{}, false, ErrConflict
	}
	if _, _, _, e = actualUsage(u, nil); e != nil {
		return u, false, e
	}
	return u, true, nil
}

// Forward's caller is the verified Go entrypoint. The private gateway performs
// final ext-auth itself; Forward never calls Admit or sends directly upstream.
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
	req.GetBody = nil // POST is never replayed by a transport on a reused connection.
	req.Host = call.Input.Profile.Host
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("X-Request-ID", call.Input.RequestID)
	req.Header.Set("X-Maas-Admission-Ticket", call.Ticket)
	req.Header.Set("X-Maas-Reservation-Plan", call.PlanHeader)
	resp, sendErr := r.client.Do(req)
	// A cancelled caller must not cancel the durable terminal transaction.
	finish := func(result string, usage Usage, first *int64) error {
		terminalCtx, done := context.WithTimeout(context.Background(), 5*time.Second)
		defer done()
		snap, state, e := r.core.ReadRequest(terminalCtx, call.Input.RequestID)
		if e != nil || state != "in_progress" || snap.Input.Owner != call.Input.Owner {
			return ErrUnavailable
		}
		f := Final{EventID: uuid.NewSHA1(uuid.NameSpaceOID, []byte(call.Input.RequestID+"/owner-terminal")).String(), RequestID: call.Input.RequestID, Owner: call.Input.Owner, OwnerFence: snap.OwnerFence, Result: result, Usage: usage, FirstChunkMS: first, Submitted: result == "succeeded"}
		// HTTP EOF/DONE/cancel is deliberately not supplied as H2 closure evidence.
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
	if sendErr != nil {
		result, reason := "interrupted", "interrupted_before_usage"
		if errors.Is(ctx.Err(), context.Canceled) {
			result, reason = "cancelled", "cancelled_before_usage"
		} else if errors.Is(sendCtx.Err(), context.DeadlineExceeded) {
			result = "timed_out"
		}
		_ = finish(result, unavailableUsage(reason), nil)
		return ErrUnavailable
	}
	defer resp.Body.Close()
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		_ = finish("failed", unavailableUsage("not_provided"), nil)
		return ErrUnavailable
	}
	if !call.Stream {
		body, e := io.ReadAll(io.LimitReader(resp.Body, r.maxBytes+1))
		if e != nil || int64(len(body)) > r.maxBytes {
			_ = finish("failed", unavailableUsage("interrupted_before_usage"), nil)
			return ErrUnavailable
		}
		usage, ok, e := parseUsage(body)
		if e != nil {
			_ = finish("failed", unavailableUsage("not_provided"), nil)
			return ErrUnavailable
		}
		if !ok {
			usage = unavailableUsage("not_provided")
		}
		if e = finish("succeeded", usage, nil); e != nil {
			return e
		}
		w.Header().Set("Content-Type", "application/json")
		w.Header().Set("X-Request-ID", call.Input.RequestID)
		_, e = w.Write(body)
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
			_ = finish("failed", unavailableUsage("interrupted_before_usage"), first)
			return ErrUnavailable
		}
		if strings.HasPrefix(line, "data:") {
			data := strings.TrimSpace(strings.TrimPrefix(line, "data:"))
			if data == "[DONE]" {
				if e = finish("succeeded", usage, first); e != nil {
					return e
				}
				_, e = io.WriteString(w, "data: [DONE]\n\n")
				if flush, ok := w.(http.Flusher); ok {
					flush.Flush()
				}
				return e
			}
			if data != "" {
				u, ok, parseErr := parseUsage([]byte(data))
				if parseErr != nil {
					cancel()
					_ = finish("failed", unavailableUsage("not_provided"), first)
					return ErrUnavailable
				}
				if ok {
					if usage.Source == "upstream" && hash(usage) != hash(u) {
						cancel()
						_ = finish("failed", unavailableUsage("not_provided"), first)
						return ErrUnavailable
					}
					usage = u
				}
			}
		}
		if first == nil && line != "" {
			ms := time.Since(call.Input.Received).Milliseconds()
			first = &ms
		}
		if _, e = io.WriteString(w, line+"\n"); e != nil {
			cancel()
			_ = finish("cancelled", unavailableUsage("cancelled_before_usage"), first)
			return ErrUnavailable
		}
		if flush, ok := w.(http.Flusher); ok {
			flush.Flush()
		}
	}
	result, reason := "interrupted", "interrupted_before_usage"
	if ctx.Err() != nil {
		result, reason = "cancelled", "cancelled_before_usage"
	}
	_ = finish(result, unavailableUsage(reason), first)
	return ErrUnavailable
}
