package kernel

import (
	"context"
	"encoding/json"
	"github.com/jianzi123/maas/internal/protocol"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

func TestMySQLPublicStreamContract(t *testing.T) {
	for _, mode := range []string{"success", "missing_finish", "duplicate_done", "data_after_done", "wrong_model", "multiline"} {
		t.Run(mode, func(t *testing.T) {
			f := setup(t, 1)
			in := f.input(t)
			server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				_, _ = io.Copy(io.Discard, r.Body)
				if _, e := f.core.Admit(r.Context(), f.gate, in); e != nil {
					w.WriteHeader(503)
					return
				}
				w.Header().Set("X-Request-ID", "provider-forged")
				if mode == "wrong_model" {
					io.WriteString(w, "data: {\"model\":\"other-source\",\"choices\":[]}\n\n")
					return
				}
				if mode == "multiline" {
					io.WriteString(w, "data: {\r\ndata: \"choices\":[{\"delta\":{\"content\":\"你好\"},\"finish_reason\":null}]\r\ndata: }\r\n\r\n")
				} else {
					io.WriteString(w, "data: {\"id\":\"upstream-id\",\"choices\":[{\"delta\":{\"content\":\"answer\"}}],\"system_fingerprint\":\"not-public\"}\n\n")
				}
				io.WriteString(w, diagnosticFrame)
				if mode != "missing_finish" {
					io.WriteString(w, "data: {\"choices\":[{\"index\":0,\"delta\":{},\"finish_reason\":\"stop\"}]}\n\n")
				}
				io.WriteString(w, "data: [DONE]\n\n")
				if mode == "duplicate_done" {
					io.WriteString(w, "data: [DONE]\n\n")
				}
				if mode == "data_after_done" {
					io.WriteString(w, "data: {\"choices\":[]}\n\n")
				}
			}))
			defer server.Close()
			relay := &Relay{core: f.core, endpoint: server.URL, client: server.Client(), maxBytes: 65536, maxLine: 65536}
			recorder := httptest.NewRecorder()
			err := relay.Forward(context.Background(), recorder, RelayCall{Input: in, Body: []byte(`{"model":"synthetic"}`), Stream: true})
			success := mode == "success" || mode == "multiline"
			if success && err != nil {
				t.Fatal(err)
			}
			if !success && err == nil {
				t.Fatal("invalid completion succeeded")
			}
			if recorder.Header().Get("X-Request-ID") != in.RequestID {
				t.Fatal("trusted ID lost")
			}
			text := recorder.Body.String()
			if strings.Contains(text, "upstream-id") || strings.Contains(text, "not-public") {
				t.Fatal("provider metadata leaked")
			}
			usageCount := 0
			for _, event := range strings.Split(text, "\n\n") {
				if strings.HasPrefix(event, "event: error\n") {
					var value map[string]any
					_ = json.Unmarshal([]byte(strings.TrimPrefix(event, "event: error\ndata: ")), &value)
					if protocol.Validate("Error", value) != nil {
						t.Fatal("public error schema", event)
					}
					continue
				}
				if !strings.HasPrefix(event, "data: ") {
					continue
				}
				data := strings.TrimPrefix(event, "data: ")
				if data == "[DONE]" {
					continue
				}
				var value map[string]any
				if json.Unmarshal([]byte(data), &value) != nil || protocol.Validate("ChatChunk", value) != nil {
					t.Fatal("strict chunk", event)
				}
				if value["id"] != "chatcmpl-"+in.RequestID || value["model"] != in.Profile.Alias {
					t.Fatal(value)
				}
				if _, ok := value["usage"]; ok {
					usageCount++
					if value["usage"].(map[string]any)["total_tokens"] != float64(19) {
						t.Fatal(value)
					}
				}
			}
			if success {
				if usageCount != 1 || strings.Count(text, "data: [DONE]") != 1 {
					t.Fatal("final usage/DONE count", text)
				}
			} else {
				if usageCount != 0 || strings.Contains(text, "[DONE]") {
					t.Fatal("premature usage/DONE", text)
				}
			}
		})
	}
}
