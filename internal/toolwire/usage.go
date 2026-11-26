package toolwire

import "encoding/json"

// NormalizeUsage maps the approved DeepSeek cache counters into the existing
// ledger parser's names. It neither estimates missing usage nor sums snapshots.
func NormalizeUsage(b []byte) ([]byte, error) {
	var root map[string]json.RawMessage
	if json.Unmarshal(b, &root) != nil {
		return nil, ErrProtocol
	}
	raw, ok := root["usage"]
	if !ok || string(raw) == "null" {
		return b, nil
	}
	var usage map[string]json.RawMessage
	if json.Unmarshal(raw, &usage) != nil || usage == nil {
		return nil, ErrProtocol
	}
	hit, hasHit := usage["prompt_cache_hit_tokens"]
	miss, hasMiss := usage["prompt_cache_miss_tokens"]
	if string(hit) == "null" {
		hasHit = false
	}
	if string(miss) == "null" {
		hasMiss = false
	}
	if !hasHit && !hasMiss {
		return b, nil
	}
	var h, m, p int64
	if hasHit && (json.Unmarshal(hit, &h) != nil || h < 0) || hasMiss && (json.Unmarshal(miss, &m) != nil || m < 0) {
		return nil, ErrProtocol
	}
	if input, ok := usage["prompt_tokens"]; !ok || string(input) == "null" {
		return b, nil
	} else if json.Unmarshal(input, &p) != nil || p < 0 {
		return nil, ErrProtocol
	}
	if hasHit && h > p || hasMiss && m > p || hasHit && hasMiss && m != p-h {
		return nil, ErrProtocol
	}
	// An absent classification is unknown, not a conflicting or zero counter.
	// Let the original ledger preserve known Tokens and hold unknown Money.
	if !hasHit {
		return b, nil
	}
	details := map[string]json.RawMessage{}
	if raw, ok := usage["prompt_tokens_details"]; ok && string(raw) != "null" {
		if json.Unmarshal(raw, &details) != nil || details == nil {
			return nil, ErrProtocol
		}
	}
	if old, ok := details["cached_tokens"]; ok && string(old) != "null" {
		var n int64
		if json.Unmarshal(old, &n) != nil || n != h {
			return nil, ErrProtocol
		}
	}
	details["cached_tokens"] = hit
	usage["prompt_tokens_details"], _ = json.Marshal(details)
	root["usage"], _ = json.Marshal(usage)
	out, e := json.Marshal(root)
	return out, e
}
