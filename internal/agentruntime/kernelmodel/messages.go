package kernelmodel

import (
	"encoding/json"
	a "github.com/jianzi123/maas/internal/agentruntime"
	"github.com/jianzi123/maas/internal/protocol"
)

// ToolMessages maps durable runtime UUIDs back to the supplier's original call
// identities. The mapping is stored on assistant Parts and survives restart.
func ToolMessages(messages []a.Message) ([]map[string]any, error) {
	out := []map[string]any{}
	source := map[string]string{}
	pending := map[string]bool{}
	for _, msg := range messages {
		text := ""
		calls := []any{}
		if msg.Role == "tool" {
			if len(msg.Parts) != 1 || msg.Parts[0].Type != "tool_result" {
				return nil, a.ErrInvalid
			}
			p := msg.Parts[0]
			if !pending[p.CallID] {
				return nil, a.ErrInvalid
			}
			delete(pending, p.CallID)
			out = append(out, map[string]any{"role": "tool", "tool_call_id": source[p.CallID], "content": p.Text})
			continue
		}
		if msg.Role != "user" && msg.Role != "assistant" {
			return nil, a.ErrInvalid
		}
		if len(pending) > 0 {
			return nil, a.ErrInvalid
		}
		for _, p := range msg.Parts {
			switch p.Type {
			case "text":
				text += p.Text
			case "tool_call":
				if msg.Role != "assistant" || p.CallID == "" || pending[p.CallID] {
					return nil, a.ErrInvalid
				}
				args, e := protocol.CanonicalToolJSON(p.Arguments)
				if e != nil || len(args) == 0 || args[0] != '{' {
					return nil, a.ErrInvalid
				}
				id := p.SourceCallID
				if id == "" {
					id = p.CallID
				}
				source[p.CallID] = id
				pending[p.CallID] = true
				calls = append(calls, map[string]any{"id": id, "type": "function", "function": map[string]any{"name": p.Name, "arguments": string(args)}})
			default:
				return nil, a.ErrInvalid
			}
		}
		row := map[string]any{"role": msg.Role, "content": text}
		if len(calls) > 0 {
			row["tool_calls"] = calls
		}
		out = append(out, row)
	}
	if len(pending) > 0 {
		return nil, a.ErrInvalid
	}
	return out, nil
}

func ToolDefinitions(specs []a.ToolSpec) ([]any, error) {
	out := []any{}
	seen := map[string]bool{}
	for _, s := range specs {
		if s.Name == "" || seen[s.Name] {
			return nil, a.ErrInvalid
		}
		seen[s.Name] = true
		b, e := protocol.CanonicalToolJSON(s.Schema)
		if e != nil {
			return nil, a.ErrInvalid
		}
		var shape struct {
			Type string `json:"type"`
		}
		if json.Unmarshal(b, &shape) != nil || shape.Type != "object" {
			return nil, a.ErrInvalid
		}
		out = append(out, map[string]any{"type": "function", "function": map[string]any{"name": s.Name, "parameters": json.RawMessage(b)}})
	}
	return out, nil
}
