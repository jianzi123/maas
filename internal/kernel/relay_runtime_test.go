package kernel

import (
	"context"
	"crypto/ecdsa"
	"crypto/elliptic"
	"crypto/rand"
	"crypto/tls"
	"crypto/x509"
	"crypto/x509/pkix"
	"encoding/pem"
	"io"
	"math/big"
	"net"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"sync/atomic"
	"testing"
	"time"
)

func TestRelayTLSRuntime(t *testing.T) {
	dir := t.TempDir()
	key, _ := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	ca := &x509.Certificate{SerialNumber: big.NewInt(1), Subject: pkix.Name{CommonName: "controlled-relay-ca"}, NotBefore: time.Now().Add(-time.Hour), NotAfter: time.Now().Add(time.Hour), IsCA: true, BasicConstraintsValid: true, KeyUsage: x509.KeyUsageCertSign}
	der, err := x509.CreateCertificate(rand.Reader, ca, ca, &key.PublicKey, key)
	if err != nil {
		t.Fatal(err)
	}
	caPEM := pem.EncodeToMemory(&pem.Block{Type: "CERTIFICATE", Bytes: der})
	issue := func(serial int64, usage x509.ExtKeyUsage) ([]byte, []byte) {
		t.Helper()
		child, _ := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
		template := &x509.Certificate{SerialNumber: big.NewInt(serial), NotBefore: ca.NotBefore, NotAfter: ca.NotAfter, KeyUsage: x509.KeyUsageDigitalSignature, ExtKeyUsage: []x509.ExtKeyUsage{usage}, IPAddresses: []net.IP{net.ParseIP("127.0.0.1")}}
		b, e := x509.CreateCertificate(rand.Reader, template, ca, &child.PublicKey, key)
		if e != nil {
			t.Fatal(e)
		}
		private, _ := x509.MarshalECPrivateKey(child)
		return pem.EncodeToMemory(&pem.Block{Type: "CERTIFICATE", Bytes: b}), pem.EncodeToMemory(&pem.Block{Type: "EC PRIVATE KEY", Bytes: private})
	}
	serverCert, serverKey := issue(2, x509.ExtKeyUsageServerAuth)
	clientCert, clientKey := issue(3, x509.ExtKeyUsageClientAuth)
	write := func(name string, b []byte) string {
		p := filepath.Join(dir, name)
		if e := os.WriteFile(p, b, 0600); e != nil {
			t.Fatal(e)
		}
		return p
	}
	var called, escaped atomic.Int64
	escape := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { escaped.Add(1) }))
	defer escape.Close()
	server := httptest.NewUnstartedServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if len(r.TLS.PeerCertificates) != 1 {
			t.Error("client identity absent")
		}
		called.Add(1)
		if r.URL.Path == "/redirect" {
			http.Redirect(w, r, escape.URL, 302)
			return
		}
		if r.URL.Path == "/stream" {
			w.Header().Set("Content-Type", "text/event-stream")
			io.WriteString(w, "data: first\n\n")
			w.(http.Flusher).Flush()
			time.Sleep(50 * time.Millisecond)
			io.WriteString(w, "data: last\n\n")
			return
		}
		if r.URL.Path == "/slow" {
			time.Sleep(50 * time.Millisecond)
		}
		io.WriteString(w, "controlled transport only")
	}))
	pair, _ := tls.X509KeyPair(serverCert, serverKey)
	pool := x509.NewCertPool()
	pool.AppendCertsFromPEM(caPEM)
	server.TLS = &tls.Config{Certificates: []tls.Certificate{pair}, ClientAuth: tls.RequireAndVerifyClientCert, ClientCAs: pool, MinVersion: tls.VersionTLS12}
	server.StartTLS()
	defer server.Close()
	config := RelayTLSFiles{Endpoint: server.URL, CAFile: write("ca.pem", caPEM), CertificateFile: write("client.pem", clientCert), KeyFile: write("client-key.pem", clientKey), DialTimeout: time.Second, HeaderTimeout: time.Second, MaxBytes: 4096, MaxLine: 1024}
	t.Run("verified_mutual_TLS_and_no_environment_proxy", func(t *testing.T) {
		t.Setenv("HTTPS_PROXY", escape.URL)
		relay, e := OpenRelayTLS(&Store{}, config)
		if e != nil {
			t.Fatal(e)
		}
		defer relay.Close()
		response, e := relay.client.Get(server.URL)
		if e != nil {
			t.Fatal(e)
		}
		response.Body.Close()
		if response.StatusCode != 200 || escaped.Load() != 0 {
			t.Fatal("fixed transport bypassed")
		}
	})
	t.Run("stream_body_outlives_header_timeout", func(t *testing.T) {
		cfg := config
		cfg.HeaderTimeout = 20 * time.Millisecond
		relay, e := OpenRelayTLS(&Store{}, cfg)
		if e != nil {
			t.Fatal(e)
		}
		defer relay.Close()
		response, e := relay.client.Get(server.URL + "/stream")
		if e != nil {
			t.Fatal(e)
		}
		defer response.Body.Close()
		body, e := io.ReadAll(response.Body)
		if e != nil || string(body) != "data: first\n\ndata: last\n\n" {
			t.Fatal("stream was truncated", e)
		}
	})
	t.Run("redirect_not_followed", func(t *testing.T) {
		relay, e := OpenRelayTLS(&Store{}, config)
		if e != nil {
			t.Fatal(e)
		}
		defer relay.Close()
		response, e := relay.client.Get(server.URL + "/redirect")
		if e != nil {
			t.Fatal(e)
		}
		response.Body.Close()
		if response.StatusCode != 302 || escaped.Load() != 0 {
			t.Fatal("redirect followed")
		}
	})
	t.Run("cancelled_context_sends_nothing", func(t *testing.T) {
		relay, e := OpenRelayTLS(&Store{}, config)
		if e != nil {
			t.Fatal(e)
		}
		defer relay.Close()
		before := called.Load()
		ctx, cancel := context.WithCancel(context.Background())
		cancel()
		req, _ := http.NewRequestWithContext(ctx, "POST", server.URL, nil)
		if _, e = relay.client.Do(req); e == nil || called.Load() != before {
			t.Fatal("cancelled transport sent")
		}
	})
	t.Run("header_deadline", func(t *testing.T) {
		cfg := config
		cfg.HeaderTimeout = time.Millisecond
		relay, e := OpenRelayTLS(&Store{}, cfg)
		if e != nil {
			t.Fatal(e)
		}
		defer relay.Close()
		if response, e := relay.client.Get(server.URL + "/slow"); e == nil {
			response.Body.Close()
			t.Fatal("header deadline ignored")
		}
	})
	for _, mode := range []string{"missing-key", "invalid-ca", "oversized-ca", "http-endpoint", "missing-timeout", "missing-core", "wrong-client-key"} {
		t.Run(mode, func(t *testing.T) {
			cfg := config
			core := &Store{}
			switch mode {
			case "missing-key":
				cfg.KeyFile = filepath.Join(dir, "sensitive-do-not-echo")
			case "invalid-ca":
				cfg.CAFile = write("bad-ca", []byte("invalid"))
			case "oversized-ca":
				cfg.CAFile = write("big-ca", make([]byte, 65537))
			case "http-endpoint":
				cfg.Endpoint = escape.URL
			case "missing-timeout":
				cfg.DialTimeout = 0
			case "missing-core":
				core = nil
			case "wrong-client-key":
				cfg.KeyFile = write("wrong-key", serverKey)
			}
			if _, e := OpenRelayTLS(core, cfg); e != ErrUnavailable {
				t.Fatal("configuration did not fail closed", e)
			}
		})
	}
	t.Run("untrusted_server_rejected", func(t *testing.T) {
		other := httptest.NewTLSServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { t.Error("untrusted handler reached") }))
		defer other.Close()
		cfg := config
		cfg.Endpoint = other.URL
		relay, e := OpenRelayTLS(&Store{}, cfg)
		if e != nil {
			t.Fatal(e)
		}
		defer relay.Close()
		if response, e := relay.client.Get(other.URL); e == nil {
			response.Body.Close()
			t.Fatal("untrusted server accepted")
		}
	})
}
