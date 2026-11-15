package kernel

import (
	"context"
	"crypto/tls"
	"encoding/json"
	"errors"
	"net"
	"net/http"
	"net/url"
	"strings"
)

// Relay has one installation-approved PRIVATE Higress endpoint. It never takes
// a supplier URL from a caller/profile and has no fallback, redirect or retry.
// No binary exposes it while the real H1-H4/registry chain is unavailable.
type Relay struct {
	Sampler  *RelaySampler
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
	pinned := transport.Clone()
	pinned.TLSClientConfig = transport.TLSClientConfig.Clone()
	if pinned.TLSClientConfig.MinVersion < tls.VersionTLS12 {
		pinned.TLSClientConfig.MinVersion = tls.VersionTLS12
	}
	if pinned.TLSClientConfig.RootCAs != nil {
		pinned.TLSClientConfig.RootCAs = pinned.TLSClientConfig.RootCAs.Clone()
	}
	return &Relay{core: core, endpoint: strings.TrimSuffix(endpoint, "/"), client: &http.Client{Transport: pinned, CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }}, maxBytes: maxBytes, maxLine: maxLine}, nil
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

func relayFailure(client, transport context.Context, err error, fallback string) (string, string) {
	// sendCtx remembers its first termination even if the parent is cancelled
	// later; inspect it before cleanup, rather than letting later parent cancel
	// overwrite an already observed hard deadline.
	reason := transport.Err()
	if reason == nil {
		reason = client.Err()
	}
	if errors.Is(reason, context.Canceled) {
		return "cancelled", "cancelled_before_usage"
	}
	var n net.Error
	if errors.Is(reason, context.DeadlineExceeded) || (errors.As(err, &n) && n.Timeout()) {
		return "timed_out", "interrupted_before_usage"
	}
	return fallback, "interrupted_before_usage"
}

// Cumulative snapshots replace previous snapshots; they are never summed.
func monotonicUsage(old, next Usage) bool {
	for _, p := range [][2]*int64{{old.Input, next.Input}, {old.Output, next.Output}, {old.Total, next.Total}, {old.Cached, next.Cached}, {old.Reasoning, next.Reasoning}} {
		if p[0] != nil && p[1] != nil && *p[1] < *p[0] {
			return false
		}
	}
	return true
}
