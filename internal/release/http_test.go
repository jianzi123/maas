package release

import (
	"context"
	"crypto/tls"
	"crypto/x509"
	"encoding/json"
	"github.com/google/uuid"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

func TestCommandClientMTLSAndNoRedirectOrSecretEcho(t *testing.T) {
	status := http.StatusAccepted
	calls := 0
	cmd := Command{ID: uuid.NewString(), Action: "CloseAdmission", CRUID: uuid.NewString(), Generation: 2, Fence: 3, Revision: strings.Repeat("a", 64), EvidenceRefs: []string{}}
	server := httptest.NewUnstartedServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		calls++
		if len(r.TLS.PeerCertificates) == 0 {
			t.Error("missing client identity")
		}
		if r.URL.Path != "/internal/v1/releases/"+cmd.CRUID+"/commands" {
			t.Error("wrong endpoint")
		}
		var got Command
		if json.NewDecoder(r.Body).Decode(&got) != nil || got.ID != cmd.ID {
			t.Error("wrong command")
		}
		if status == http.StatusFound {
			w.Header().Set("Location", "https://untrusted.invalid")
		}
		w.WriteHeader(status)
		_, _ = w.Write([]byte("SENSITIVE_SUPPLIER_BODY"))
	}))
	server.TLS = &tls.Config{ClientAuth: tls.RequireAnyClientCert, MinVersion: tls.VersionTLS12}
	server.StartTLS()
	defer server.Close()
	roots := x509.NewCertPool()
	roots.AddCert(server.Certificate())
	cfg := &tls.Config{RootCAs: roots, Certificates: server.TLS.Certificates, MinVersion: tls.VersionTLS12}
	c, err := NewCommandClient(server.URL, cfg)
	if err != nil {
		t.Fatal(err)
	}
	if err = c.Send(context.Background(), cmd); err != nil {
		t.Fatal(err)
	}
	status = http.StatusConflict
	if c.Send(context.Background(), cmd) != ErrConflict {
		t.Fatal("missing CAS conflict")
	}
	status = http.StatusFound
	err = c.Send(context.Background(), cmd)
	if err == nil || strings.Contains(err.Error(), "SENSITIVE") {
		t.Fatal("redirect or secret body accepted")
	}
	if calls != 3 {
		t.Fatal("command retried or redirect followed")
	}
	if _, err = NewCommandClient("http://plain.test", cfg); err == nil {
		t.Fatal("plaintext accepted")
	}
	cfg.InsecureSkipVerify = true
	if _, err = NewCommandClient(server.URL, cfg); err == nil {
		t.Fatal("insecure TLS accepted")
	}
}
