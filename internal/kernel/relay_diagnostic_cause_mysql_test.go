package kernel

import (
	"context"
	"errors"
	"net/http"
	"net/http/httptest"
	"testing"
)

type unavailableDiagnosticTransport struct{}

func (unavailableDiagnosticTransport) RoundTrip(*http.Request) (*http.Response, error) {
	return nil, errors.New("controlled transport unavailable")
}
func TestMySQLRelayDoesNotInventDiagnosticCause(t *testing.T) {
	for _, mode := range []string{"http_status", "transport_error"} {
		t.Run(mode, func(t *testing.T) {
			f := setup(t, 1)
			in := f.input(t)
			mustAdmit(t, f, in)
			gateway := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { w.WriteHeader(502) }))
			defer gateway.Close()
			client := gateway.Client()
			if mode == "transport_error" {
				client = &http.Client{Transport: unavailableDiagnosticTransport{}}
			}
			relay := &Relay{core: f.core, endpoint: gateway.URL, client: client, maxBytes: 1 << 20, maxLine: 65536}
			if err := relay.Forward(context.Background(), httptest.NewRecorder(), RelayCall{Input: in, Body: []byte("{}"), Stream: true}); err == nil {
				t.Fatal("failure became success")
			}
			rows, err := f.core.ReadUsageDiagnostics(context.Background(), in.RequestID)
			if err != nil || len(rows) != 0 {
				t.Fatal("invented EOF/parse-invalid cause", rows, err)
			}
			assertSQL(t, f.db, "SELECT COUNT(*) FROM usage_events", 1)
			if c := readCounter(t, f, "tokens"); c.Held != "140" {
				t.Fatal(c)
			}
		})
	}
}
