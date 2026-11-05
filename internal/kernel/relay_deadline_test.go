package kernel

import (
	"context"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"
)

func TestMySQLRelayHardDeadline(t *testing.T) {
	for _, stream := range []bool{true, false} {
		name := "nonstream"
		if stream {
			name = "stream"
		}
		t.Run(name, func(t *testing.T) {
			f := setup(t, 1)
			in := f.input(t)
			in.Expires = time.Now().UTC().Add(time.Second)
			in.Deadline = in.Expires.Add(250 * time.Millisecond)
			server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				if _, e := f.core.Admit(r.Context(), f.gate, in); e != nil {
					w.WriteHeader(503)
					return
				}
				if stream {
					io.WriteString(w, "data: {\"choices\":[]}\n\n")
				} else {
					io.WriteString(w, `{"choices":[`)
				}
				w.(http.Flusher).Flush()
				<-r.Context().Done()
			}))
			defer server.Close()
			relay := &Relay{core: f.core, endpoint: server.URL, client: server.Client(), maxBytes: 65536, maxLine: 65536}
			recorder := httptest.NewRecorder()
			e := relay.Forward(context.Background(), recorder, RelayCall{Input: in, Body: []byte(`{"model":"synthetic"}`), Stream: stream})
			if e == nil || strings.Contains(recorder.Body.String(), "[DONE]") {
				t.Fatal("deadline reported success")
			}
			_, state, e := f.core.ReadRequest(context.Background(), in.RequestID)
			if e != nil || state != "timed_out" {
				t.Fatal("deadline classification", state, e)
			}
			if c := readCounter(t, f, "tokens"); c.Held != "140" {
				t.Fatal(c)
			}
			assertSQL(t, f.db, "SELECT COUNT(*) FROM concurrency_slots WHERE state='QUARANTINED'", 1)
		})
	}
}
