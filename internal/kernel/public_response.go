package kernel

import (
	"bufio"
	"context"
	"encoding/json"
	"github.com/jianzi123/maas/internal/protocol"
	"io"
	"strings"
	"unicode/utf8"
)

type publicEventReader struct {
	scanner    *bufio.Scanner
	limit      int
	total, max int64
}

func newPublicEventReader(r io.Reader, lineLimit int, totalLimit int64) *publicEventReader {
	if lineLimit > 262144 {
		lineLimit = 262144
	}
	s := bufio.NewScanner(io.LimitReader(r, totalLimit+1))
	s.Buffer(make([]byte, 4096), lineLimit)
	return &publicEventReader{s, lineLimit, 0, totalLimit}
}
func (r *publicEventReader) Next() ([]byte, error) {
	data := []string{}
	event := ""
	size := 0
	for r.scanner.Scan() {
		line := r.scanner.Text()
		r.total += int64(len(line) + 1)
		if r.total > r.max {
			return nil, ErrConflict
		}
		if line == "" {
			if len(data) == 0 {
				event = ""
				continue
			}
			if event != "" && event != "message" {
				return nil, ErrConflict
			}
			b := []byte(strings.Join(data, "\n"))
			if !utf8.Valid(b) {
				return nil, ErrConflict
			}
			return b, nil
		}
		if strings.HasPrefix(line, ":") {
			continue
		}
		if strings.HasPrefix(line, "event:") {
			event = strings.TrimSpace(strings.TrimPrefix(line, "event:"))
			continue
		}
		if strings.HasPrefix(line, "data:") {
			value := strings.TrimPrefix(line, "data:")
			if strings.HasPrefix(value, " ") {
				value = value[1:]
			}
			size += len(value) + 1
			if size > r.limit {
				return nil, ErrConflict
			}
			data = append(data, value)
		}
	}
	if e := r.scanner.Err(); e != nil {
		return nil, e
	}
	if len(data) > 0 {
		return nil, io.ErrUnexpectedEOF
	}
	return nil, io.EOF
}
func publicRoot(in Input, chunk bool) map[string]any {
	object := "chat.completion"
	if chunk {
		object = "chat.completion.chunk"
	}
	return map[string]any{"id": "chatcmpl-" + in.RequestID, "object": object, "created": in.Received.Unix(), "model": in.Profile.Alias}
}
func sourceEnvelope(b []byte, in Input) (map[string]json.RawMessage, error) {
	canonical, e := protocol.Canonical(b)
	if e != nil {
		return nil, ErrConflict
	}
	var v map[string]json.RawMessage
	if json.Unmarshal(canonical, &v) != nil || v == nil {
		return nil, ErrConflict
	}
	// A provider error is terminal even in an ordinary SSE data event. Never
	// normalize it into an empty success chunk that a later finish can overwrite.
	if _, exists := v["error"]; exists {
		return nil, ErrConflict
	}
	if model, ok := v["model"]; ok {
		var s string
		if json.Unmarshal(model, &s) != nil || s != in.Profile.UpstreamModel {
			return nil, ErrConflict
		}
	}
	return v, nil
}
func normalizeChunk(b []byte, in Input) (map[string]any, bool, error) {
	v, e := sourceEnvelope(b, in)
	if e != nil {
		return nil, false, e
	}
	var choices []map[string]json.RawMessage
	if raw, ok := v["choices"]; ok {
		if json.Unmarshal(raw, &choices) != nil || len(choices) > 1 {
			return nil, false, ErrConflict
		}
	}
	out := publicRoot(in, true)
	normalized := []any{}
	finish := false
	for _, choice := range choices {
		var index int
		if raw, ok := choice["index"]; ok && json.Unmarshal(raw, &index) != nil {
			return nil, false, ErrConflict
		}
		if index != 0 {
			return nil, false, ErrConflict
		}
		var delta map[string]json.RawMessage
		if raw, ok := choice["delta"]; ok && json.Unmarshal(raw, &delta) != nil {
			return nil, false, ErrConflict
		}
		clean := map[string]any{}
		for k, raw := range delta {
			switch k {
			case "role":
				if string(raw) != "null" {
					var s string
					if json.Unmarshal(raw, &s) != nil || s != "assistant" {
						return nil, false, ErrConflict
					}
					clean[k] = s
				}
			case "content":
				if string(raw) != "null" {
					var s string
					if json.Unmarshal(raw, &s) != nil {
						return nil, false, ErrConflict
					}
					clean[k] = s
				}
			default:
				return nil, false, ErrConflict
			}
		}
		var reason any
		if raw, ok := choice["finish_reason"]; ok && string(raw) != "null" {
			var s string
			if json.Unmarshal(raw, &s) != nil || (s != "stop" && s != "length") {
				return nil, false, ErrConflict
			}
			reason = s
			finish = true
		}
		for k := range choice {
			if k != "index" && k != "delta" && k != "finish_reason" {
				return nil, false, ErrConflict
			}
		}
		normalized = append(normalized, map[string]any{"index": 0, "delta": clean, "finish_reason": reason})
	}
	out["choices"] = normalized
	if protocol.Validate("ChatChunk", out) != nil {
		return nil, false, ErrConflict
	}
	return out, finish, nil
}
func normalizeResponse(b []byte, in Input, usage Usage) (map[string]any, error) {
	v, e := sourceEnvelope(b, in)
	if e != nil {
		return nil, e
	}
	var choices []map[string]json.RawMessage
	if json.Unmarshal(v["choices"], &choices) != nil || len(choices) != 1 {
		return nil, ErrConflict
	}
	c := choices[0]
	var index int
	if raw, ok := c["index"]; ok && json.Unmarshal(raw, &index) != nil {
		return nil, ErrConflict
	}
	if index != 0 {
		return nil, ErrConflict
	}
	var message map[string]json.RawMessage
	if json.Unmarshal(c["message"], &message) != nil {
		return nil, ErrConflict
	}
	var role, content, finish string
	if json.Unmarshal(message["role"], &role) != nil || role != "assistant" || json.Unmarshal(message["content"], &content) != nil || json.Unmarshal(c["finish_reason"], &finish) != nil || (finish != "stop" && finish != "length") {
		return nil, ErrConflict
	}
	for k := range message {
		if k != "role" && k != "content" {
			return nil, ErrConflict
		}
	}
	for k := range c {
		if k != "index" && k != "message" && k != "finish_reason" {
			return nil, ErrConflict
		}
	}
	out := publicRoot(in, false)
	out["choices"] = []any{map[string]any{"index": 0, "message": map[string]any{"role": role, "content": content}, "finish_reason": finish}}
	out["usage"] = publicUsage(usage)
	if protocol.Validate("ChatResponse", out) != nil {
		return nil, ErrConflict
	}
	return out, nil
}
func publicUsage(u Usage) Usage {
	if u.Source == "upstream" {
		if u.Input == nil || u.Output == nil || u.Total == nil {
			u.Missing = ptr("partial")
		} else {
			u.Missing = nil
		}
	}
	return u
}
func (s *Store) successfulUsage(ctx context.Context, id string) (Usage, error) {
	var u Usage
	var b []byte
	e := s.db.QueryRowContext(ctx, `SELECT e.event_json FROM generation_requests r JOIN usage_events e ON e.event_id=r.terminal_event_id WHERE r.request_id=? AND r.result='succeeded'`, id).Scan(&b)
	if e != nil {
		return u, ErrUnavailable
	}
	var event struct {
		Usage Usage `json:"usage"`
	}
	if json.Unmarshal(b, &event) != nil {
		return u, ErrUnavailable
	}
	return event.Usage, nil
}
func publicError(in Input, code string) map[string]any {
	return map[string]any{"error": map[string]any{"code": code, "message": code, "request_id": in.RequestID, "retryable": false, "reset_at": nil, "retry_after_seconds": nil, "param": nil, "budget_dimension": nil, "policy_revision": nil}}
}
