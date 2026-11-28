package toolwire

import (
	"bufio"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"strings"
	"testing"
)

// The original captures are replayed over actual loopback HTTP. These assertions
// cover the wire layer, not the Python fixture's authorization/execution/timing.
func TestMAAS9ToolsWireVectors(t *testing.T) {
	raw, e := os.ReadFile("testdata/maas9-v08-vectors.json")
	if e != nil {
		t.Fatal(e)
	}
	var doc struct {
		Cases []struct {
			ID    string `json:"id"`
			Turns []struct {
				Binding struct {
					Model string `json:"model"`
				} `json:"binding"`
				Response struct {
					Wire string `json:"wire"`
				} `json:"response"`
			} `json:"turns"`
		} `json:"cases"`
	}
	if e = json.Unmarshal(raw, &doc); e != nil {
		t.Fatal(e)
	}
	reject := map[string]bool{}
	for _, prefix := range []string{"TC06_", "TC07_", "TC08_", "TC09_", "TC12_", "TC16_", "TC23_", "TC24_", "TC26_", "TC29_", "TC30_", "TC31_", "TC32_", "TC37_"} {
		reject[prefix] = true
	}
	tested := 0
	for _, c := range doc.Cases {
		if len(c.Turns) == 0 {
			continue
		}
		t.Run(c.ID, func(t *testing.T) {
			turn := c.Turns[0]
			server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				w.Header().Set("Content-Type", "text/event-stream")
				for i := 0; i < len(turn.Response.Wire); i += 7 {
					end := i + 7
					if end > len(turn.Response.Wire) {
						end = len(turn.Response.Wire)
					}
					io.WriteString(w, turn.Response.Wire[i:end])
					w.(http.Flusher).Flush()
				}
			}))
			defer server.Close()
			res, e := server.Client().Get(server.URL)
			if e != nil {
				t.Fatal(e)
			}
			defer res.Body.Close()
			stream := &Stream{MaxArguments: 256}
			scanner := bufio.NewScanner(res.Body)
			scanner.Buffer(make([]byte, 4096), 1<<20)
			done := false
			var wireErr error
			for scanner.Scan() {
				line := scanner.Text()
				if !strings.HasPrefix(line, "data: ") {
					continue
				}
				data := strings.TrimPrefix(line, "data: ")
				if done {
					wireErr = ErrProtocol
					break
				}
				if data == "[DONE]" {
					if stream.Finish == "" {
						wireErr = ErrProtocol
					}
					done = true
					continue
				}
				if _, _, e := stream.Push([]byte(data), turn.Binding.Model); e != nil {
					wireErr = e
					break
				}
			}
			if e := scanner.Err(); e != nil {
				t.Fatal(e)
			}
			wantReject := false
			for prefix := range reject {
				if strings.HasPrefix(c.ID, prefix) {
					wantReject = true
				}
			}
			if (wireErr != nil) != wantReject {
				t.Fatalf("wire rejection=%v expected=%v (semantic/transport fixture expectations are separate)", wireErr, wantReject)
			}
			if strings.HasPrefix(c.ID, "TC02_") {
				if len(stream.Calls) != 2 || stream.Calls[0].ID == stream.Calls[1].ID || !json.Valid([]byte(stream.Calls[0].Arguments)) || !json.Valid([]byte(stream.Calls[1].Arguments)) {
					t.Fatal("interleaved calls lost", stream.Calls)
				}
			}
		})
		tested++
	}
	if tested != 45 {
		t.Fatal("vector inventory drift", tested)
	}
}

func TestDeepSeekCacheUsageKeepsUnknownAndRejectsConflicts(t *testing.T) {
	partial := `{"usage":{"prompt_tokens":12,"completion_tokens":7,"total_tokens":19,"prompt_cache_miss_tokens":8}}`
	if b, e := NormalizeUsage([]byte(partial)); e != nil || string(b) != partial {
		t.Fatal("missing classification erased known dimensions", string(b), e)
	}
	nullHit := `{"usage":{"prompt_tokens":12,"completion_tokens":7,"total_tokens":19,"prompt_cache_hit_tokens":null,"prompt_cache_miss_tokens":8}}`
	if b, e := NormalizeUsage([]byte(nullHit)); e != nil || string(b) != nullHit {
		t.Fatal("null classification became zero", string(b), e)
	}
	for _, raw := range []string{`{"usage":{"prompt_tokens":12,"prompt_cache_hit_tokens":4}}`, `{"usage":{"prompt_tokens":12,"prompt_cache_hit_tokens":4,"prompt_cache_miss_tokens":8,"prompt_tokens_details":{"cached_tokens":null}}}`} {
		if b, e := NormalizeUsage([]byte(raw)); e != nil || !strings.Contains(string(b), `"cached_tokens":4`) {
			t.Fatal("explicit hit lost", string(b), e)
		}
	}
	for _, raw := range []string{`{"usage":null}`, `{"choices":[]}`} {
		out, e := NormalizeUsage([]byte(raw))
		if e != nil || string(out) != raw {
			t.Fatal("missing became known", e)
		}
	}
	for _, raw := range []string{`{"usage":{"prompt_tokens":12,"prompt_cache_hit_tokens":4,"prompt_cache_miss_tokens":7}}`, `{"usage":{"prompt_tokens":12,"prompt_cache_hit_tokens":4,"prompt_cache_miss_tokens":8,"prompt_tokens_details":{"cached_tokens":5}}}`} {
		if _, e := NormalizeUsage([]byte(raw)); e == nil {
			t.Fatal("conflict accepted")
		}
	}
	b, e := NormalizeUsage([]byte(`{"usage":{"prompt_tokens":12,"prompt_cache_hit_tokens":4,"prompt_cache_miss_tokens":8}}`))
	if e != nil || !strings.Contains(string(b), `"cached_tokens":4`) {
		t.Fatal(string(b), e)
	}
}
