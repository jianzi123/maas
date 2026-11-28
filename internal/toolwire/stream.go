// Package toolwire implements the private tools-v1 Chat Completions dialect.
// It assembles data only; tool authorization/execution and accounting live elsewhere.
package toolwire

import (
	"encoding/json"
	"errors"
	"github.com/jianzi123/maas/internal/protocol"
)

var ErrProtocol = errors.New("tools_stream_invalid")

type Call struct{ ID, Name, Arguments string }
type Stream struct {
	MaxArguments int
	Calls        []Call
	Finish       string
	role         bool
	identity     string
	output       int
}

// Push accepts a complete UTF-8 SSE data value. Byte/frame limits and EOF/DONE
// ordering are enforced by the protected Relay's existing event reader.
func (s *Stream) Push(b []byte, model string) ([]any, bool, error) {
	b, e := protocol.Canonical(b)
	if e != nil {
		return nil, false, ErrProtocol
	}
	var root map[string]json.RawMessage
	if json.Unmarshal(b, &root) != nil || root == nil {
		return nil, false, ErrProtocol
	}
	if _, ok := root["error"]; ok {
		return nil, false, ErrProtocol
	}
	if raw, ok := root["model"]; ok {
		var v string
		if json.Unmarshal(raw, &v) != nil || v != model {
			return nil, false, ErrProtocol
		}
	}
	// If source metadata is present, it must remain stable throughout the turn.
	metadata := map[string]json.RawMessage{}
	for _, k := range []string{"id", "created", "system_fingerprint", "object"} {
		if v, ok := root[k]; ok {
			metadata[k] = v
		}
	}
	if len(metadata) > 0 {
		v, _ := json.Marshal(metadata)
		if s.identity != "" && s.identity != string(v) {
			return nil, false, ErrProtocol
		}
		s.identity = string(v)
	}
	var choices []map[string]json.RawMessage
	if json.Unmarshal(root["choices"], &choices) != nil || choices == nil || len(choices) > 1 {
		return nil, false, ErrProtocol
	}
	if len(choices) == 0 {
		if s.Finish == "" {
			return nil, false, ErrProtocol
		}
		return []any{}, false, nil
	} // usage-only final snapshot
	if s.Finish != "" {
		return nil, false, ErrProtocol
	}
	c := choices[0]
	var index int
	if json.Unmarshal(c["index"], &index) != nil || index != 0 {
		return nil, false, ErrProtocol
	}
	for k := range c {
		if k != "index" && k != "delta" && k != "finish_reason" {
			return nil, false, ErrProtocol
		}
	}
	var delta map[string]json.RawMessage
	if json.Unmarshal(c["delta"], &delta) != nil || delta == nil {
		return nil, false, ErrProtocol
	}
	clean := map[string]any{}
	for k, v := range delta {
		switch k {
		case "role":
			var role string
			if json.Unmarshal(v, &role) != nil || role != "assistant" || s.role {
				return nil, false, ErrProtocol
			}
			s.role = true
			clean[k] = role
		case "content":
			if string(v) != "null" {
				var text string
				if json.Unmarshal(v, &text) != nil {
					return nil, false, ErrProtocol
				}
				s.output += len(text)
				if s.output > 1<<20 {
					return nil, false, ErrProtocol
				}
				clean[k] = text
			}
		case "tool_calls":
			var fragments []map[string]json.RawMessage
			if json.Unmarshal(v, &fragments) != nil || fragments == nil || len(fragments) > 16 {
				return nil, false, ErrProtocol
			}
			for _, f := range fragments {
				var i int
				if json.Unmarshal(f["index"], &i) != nil || i < 0 || i > 15 || i > len(s.Calls) {
					return nil, false, ErrProtocol
				}
				var fn map[string]json.RawMessage
				if json.Unmarshal(f["function"], &fn) != nil || fn == nil {
					return nil, false, ErrProtocol
				}
				if i == len(s.Calls) {
					var id, kind, name string
					if len(f) != 4 || json.Unmarshal(f["id"], &id) != nil || id == "" || len(id) > 128 || json.Unmarshal(f["type"], &kind) != nil || kind != "function" || json.Unmarshal(fn["name"], &name) != nil || name == "" || len(name) > 128 {
						return nil, false, ErrProtocol
					}
					for _, old := range s.Calls {
						if old.ID == id {
							return nil, false, ErrProtocol
						}
					}
					if len(fn) > 2 {
						return nil, false, ErrProtocol
					}
					s.Calls = append(s.Calls, Call{ID: id, Name: name})
				} else if len(f) != 2 || len(fn) != 1 {
					return nil, false, ErrProtocol
				}
				for k := range fn {
					if k != "arguments" && !(k == "name" && len(f) == 4) {
						return nil, false, ErrProtocol
					}
				}
				if v, ok := fn["arguments"]; ok {
					var part string
					if json.Unmarshal(v, &part) != nil {
						return nil, false, ErrProtocol
					}
					s.Calls[i].Arguments += part
					limit := s.MaxArguments
					if limit == 0 {
						limit = 65536
					}
					if len(s.Calls[i].Arguments) > limit {
						return nil, false, ErrProtocol
					}
				} else if len(f) == 2 {
					return nil, false, ErrProtocol
				}
			}
			clean[k] = json.RawMessage(v)
		default:
			return nil, false, ErrProtocol
		}
	}
	if !s.role {
		return nil, false, ErrProtocol
	}
	if raw, ok := root["usage"]; ok && string(raw) != "null" {
		if v, ok := c["finish_reason"]; !ok || string(v) == "null" {
			return nil, false, ErrProtocol
		}
	}
	var reason any
	if raw, ok := c["finish_reason"]; ok && string(raw) != "null" {
		var finish string
		if json.Unmarshal(raw, &finish) != nil {
			return nil, false, ErrProtocol
		}
		switch finish {
		case "stop", "tool_calls", "length", "content_filter", "insufficient_system_resource", "aborted":
		default:
			return nil, false, ErrProtocol
		}
		if text, _ := clean["content"].(string); text != "" {
			return nil, false, ErrProtocol
		}
		if _, ok := clean["tool_calls"]; ok {
			return nil, false, ErrProtocol
		}
		if finish == "tool_calls" && len(s.Calls) == 0 || finish == "stop" && len(s.Calls) > 0 {
			return nil, false, ErrProtocol
		}
		s.Finish = finish
		reason = finish
	}
	return []any{map[string]any{"index": 0, "delta": clean, "finish_reason": reason}}, s.Finish != "", nil
}
