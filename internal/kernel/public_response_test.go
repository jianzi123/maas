package kernel

import (
	"encoding/json"
	"github.com/google/uuid"
	"github.com/jianzi123/maas/internal/protocol"
	"io"
	"strings"
	"testing"
	"time"
)

func publicInput() Input {
	return Input{RequestID: uuid.NewString(), Received: time.Date(2026, 11, 5, 0, 0, 0, 0, time.UTC), Profile: Profile{Alias: "public-alias", UpstreamModel: "approved-physical"}}
}
func TestPublicResponseProjection(t *testing.T) {
	in := publicInput()
	u, ok, e := parseUsage([]byte(`{"usage":{"prompt_tokens":12,"completion_tokens":7,"total_tokens":19,"prompt_tokens_details":{"cached_tokens":4},"completion_tokens_details":{"reasoning_tokens":3}}}`))
	if e != nil || !ok {
		t.Fatal(e)
	}
	response, e := normalizeResponse([]byte(`{"id":"provider-private","model":"approved-physical","system_fingerprint":"private-meta","choices":[{"index":0,"message":{"role":"assistant","content":"answer"},"finish_reason":"stop"}]}`), in, u)
	if e != nil || protocol.Validate("ChatResponse", response) != nil {
		t.Fatal(response, e)
	}
	b, _ := json.Marshal(response)
	if strings.Contains(string(b), "provider-private") || strings.Contains(string(b), "private-meta") || response["id"] != "chatcmpl-"+in.RequestID || response["model"] != "public-alias" {
		t.Fatal(string(b))
	}
	chunk, _, e := normalizeChunk([]byte(`{"id":"other","choices":[{"delta":{"content":"你好"},"finish_reason":null}],"usage":{"prompt_tokens":12,"completion_tokens":7,"total_tokens":19}}`), in)
	if e != nil || protocol.Validate("ChatChunk", chunk) != nil {
		t.Fatal(chunk, e)
	}
	if _, exists := chunk["usage"]; exists {
		t.Fatal("intermediate diagnostic exposed as accounting")
	}
	for _, bad := range []string{`{"model":"unapproved","choices":[]}`, `{"choices":[{"delta":{"tool_calls":[]}}]}`, `{"choices":[{"delta":{},"finish_reason":"tool_calls"}]}`, `{"choices":[{},{}]}`} {
		if _, _, e = normalizeChunk([]byte(bad), in); e == nil {
			t.Fatal("unsupported business behavior", bad)
		}
	}
}
func TestCompleteSSEEvents(t *testing.T) {
	input := ": keepalive\r\n\r\ndata: {\r\ndata: \"choices\":[{\"delta\":{\"content\":\"你好\"},\"finish_reason\":null}]\r\ndata: }\r\n\r\ndata: [DONE]\r\n\r\n"
	r := newPublicEventReader(strings.NewReader(input), 65536, 1<<20)
	b, e := r.Next()
	if e != nil {
		t.Fatal(e)
	}
	if _, _, e = normalizeChunk(b, publicInput()); e != nil {
		t.Fatal(string(b), e)
	}
	b, e = r.Next()
	if e != nil || string(b) != "[DONE]" {
		t.Fatal(string(b), e)
	}
	if _, e = r.Next(); e != io.EOF {
		t.Fatal(e)
	}
	r = newPublicEventReader(strings.NewReader("data: {\"choices\":[]}"), 65536, 1<<20)
	if _, e = r.Next(); e != io.ErrUnexpectedEOF {
		t.Fatal("incomplete event dispatched", e)
	}
	r = newPublicEventReader(strings.NewReader("data: "+strings.Repeat("a", 200)+"\n\n"), 64, 1024)
	if _, e = r.Next(); e == nil {
		t.Fatal("event limit ignored")
	}
}
