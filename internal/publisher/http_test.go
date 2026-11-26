package publisher

import (
	"context"
	"crypto/ecdsa"
	"crypto/elliptic"
	"crypto/rand"
	"crypto/tls"
	"crypto/x509"
	"crypto/x509/pkix"
	"encoding/json"
	"errors"
	"io"
	"log"
	"math/big"
	"net"
	"net/http"
	"net/http/httptest"
	"net/url"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/google/uuid"
	"github.com/jianzi123/maas/internal/release"
	"github.com/jianzi123/maas/internal/release/mysqlstore"
)

type commandRecorder struct {
	mu    sync.Mutex
	calls int
	err   error
}

func (c *commandRecorder) Apply(context.Context, release.Command) error {
	c.mu.Lock()
	defer c.mu.Unlock()
	c.calls++
	return c.err
}
func (c *commandRecorder) set(err error) { c.mu.Lock(); defer c.mu.Unlock(); c.err = err }
func (c *commandRecorder) count() int    { c.mu.Lock(); defer c.mu.Unlock(); return c.calls }

const operatorID = "spiffe://maas.test/release/operator"

func certificates(t *testing.T) (*tls.Config, *tls.Config, *tls.Config) {
	t.Helper()
	key, _ := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	ca := &x509.Certificate{SerialNumber: big.NewInt(1), Subject: pkix.Name{CommonName: "owned-test-ca"}, NotBefore: time.Now().Add(-time.Minute), NotAfter: time.Now().Add(time.Hour), IsCA: true, BasicConstraintsValid: true, KeyUsage: x509.KeyUsageCertSign}
	der, err := x509.CreateCertificate(rand.Reader, ca, ca, &key.PublicKey, key)
	if err != nil {
		t.Fatal(err)
	}
	ca, _ = x509.ParseCertificate(der)
	roots := x509.NewCertPool()
	roots.AddCert(ca)
	leaf := func(serial int64, client bool, identity string) tls.Certificate {
		k, _ := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
		c := &x509.Certificate{SerialNumber: big.NewInt(serial), NotBefore: ca.NotBefore, NotAfter: ca.NotAfter, KeyUsage: x509.KeyUsageDigitalSignature}
		if client {
			u, _ := url.Parse(identity)
			c.URIs = []*url.URL{u}
			c.ExtKeyUsage = []x509.ExtKeyUsage{x509.ExtKeyUsageClientAuth}
		} else {
			c.IPAddresses = []net.IP{net.ParseIP("127.0.0.1")}
			c.ExtKeyUsage = []x509.ExtKeyUsage{x509.ExtKeyUsageServerAuth}
		}
		b, e := x509.CreateCertificate(rand.Reader, c, ca, &k.PublicKey, key)
		if e != nil {
			t.Fatal(e)
		}
		return tls.Certificate{Certificate: [][]byte{b, ca.Raw}, PrivateKey: k}
	}
	server := &tls.Config{MinVersion: tls.VersionTLS13, ClientAuth: tls.RequireAndVerifyClientCert, ClientCAs: roots, Certificates: []tls.Certificate{leaf(2, false, "")}}
	good := &tls.Config{MinVersion: tls.VersionTLS13, RootCAs: roots, Certificates: []tls.Certificate{leaf(3, true, operatorID)}}
	wrong := good.Clone()
	wrong.Certificates = []tls.Certificate{leaf(4, true, "spiffe://maas.test/core")}
	return server, good, wrong
}
func commandBody() (release.Command, string) {
	c := release.Command{ID: uuid.NewString(), CRUID: uuid.NewString(), Generation: 1, Fence: 1, Revision: strings.Repeat("a", 64), Action: "CloseAdmission", EvidenceRefs: []string{}}
	b, _ := json.Marshal(c)
	return c, string(b)
}
func TestCommandMTLSBoundary(t *testing.T) {
	recorder := new(commandRecorder)
	serverTLS, good, wrong := certificates(t)
	server := httptest.NewUnstartedServer(Handler{Control: recorder, OperatorIdentity: operatorID})
	server.TLS = serverTLS
	server.Config.ErrorLog = log.New(io.Discard, "", 0)
	server.StartTLS()
	defer server.Close()
	clientFor := func(cfg *tls.Config) *http.Client {
		tr := &http.Transport{TLSClientConfig: cfg}
		t.Cleanup(tr.CloseIdleConnections)
		return &http.Client{Transport: tr, Timeout: time.Second * 3}
	}
	client := clientFor(good)
	command, body := commandBody()
	path := "/internal/v1/releases/" + command.CRUID + "/commands"
	send := func(c *http.Client, method, path, content string) (int, string) {
		r, _ := http.NewRequest(method, server.URL+path, strings.NewReader(content))
		r.Header.Set("Content-Type", "application/json")
		r.Header.Set("Authorization", "Bearer not-a-management-identity")
		res, e := c.Do(r)
		if e != nil {
			return 0, "transport rejected"
		}
		defer res.Body.Close()
		b, _ := io.ReadAll(res.Body)
		return res.StatusCode, string(b)
	}
	t.Run("no_certificate", func(t *testing.T) {
		cfg := good.Clone()
		cfg.Certificates = nil
		if s, _ := send(clientFor(cfg), "POST", path, body); s != 0 {
			t.Fatal(s)
		}
	})
	t.Run("wrong_trusted_identity", func(t *testing.T) {
		if s, _ := send(clientFor(wrong), "POST", path, body); s != 403 {
			t.Fatal(s)
		}
	})
	t.Run("no_verified_chain", func(t *testing.T) {
		r := httptest.NewRequest("POST", path, strings.NewReader(body))
		r.TLS = &tls.ConnectionState{PeerCertificates: []*x509.Certificate{{}}}
		w := httptest.NewRecorder()
		Handler{Control: recorder, OperatorIdentity: operatorID}.ServeHTTP(w, r)
		if w.Code != 403 {
			t.Fatal(w.Code)
		}
	})
	for _, test := range []struct {
		name, method, path, body string
		status                   int
	}{
		{"path_uid_mismatch", "POST", "/internal/v1/releases/" + uuid.NewString() + "/commands", body, 400},
		{"encoded_path", "POST", strings.Replace(path, "/commands", "/%63ommands", 1), body, 404},
		{"query", "POST", path + "?target=other", body, 404},
		{"public_route", "POST", "/v1/chat/completions", body, 404},
		{"wrong_method", "GET", path, body, 405},
		{"duplicate_field", "POST", path, strings.TrimSuffix(body, "}") + `,"action":"Activate"}`, 400},
		{"unknown_field", "POST", path, strings.TrimSuffix(body, "}") + `,"supplier_secret":"must-not-leak"}`, 400},
		{"trailing_json", "POST", path, body + "{}", 400},
		{"oversize", "POST", path, strings.Repeat("x", 16385), 400},
	} {
		t.Run(test.name, func(t *testing.T) {
			if s, b := send(client, test.method, test.path, test.body); s != test.status || strings.Contains(b, "must-not-leak") {
				t.Fatal(s, b)
			}
		})
	}
	if recorder.count() != 0 {
		t.Fatal("rejected requests reached publisher")
	}
	for _, test := range []struct {
		name   string
		err    error
		status int
		code   string
	}{
		{"success", nil, 204, ""},
		{"conflict", release.ErrConflict, 409, "release_conflict"},
		{"missing", release.ErrDependencyMissing, 503, "DependencyMissing"},
		{"unknown_commit", mysqlstore.ErrCommitUnknown, 503, "release_commit_unknown"},
		{"private_error", errors.New("private-dsn-and-supplier-body"), 503, "DependencyMissing"},
	} {
		t.Run(test.name, func(t *testing.T) {
			recorder.set(test.err)
			before := recorder.count()
			s, b := send(client, "POST", path, body)
			if s != test.status || !strings.Contains(b, test.code) || strings.Contains(b, "private-dsn") || recorder.count() != before+1 {
				t.Fatal(s, b)
			}
		})
	}
	recorder.set(nil)
	commandClient, e := release.NewCommandClient(server.URL, good)
	if e != nil {
		t.Fatal(e)
	}
	before := recorder.count()
	if e = commandClient.Send(context.Background(), command); e != nil || recorder.count() != before+1 {
		t.Fatal(e)
	}
	recorder.set(mysqlstore.ErrCommitUnknown)
	before = recorder.count()
	if e = commandClient.Send(context.Background(), command); e == nil || recorder.count() != before+1 {
		t.Fatal("client retried or accepted unknown", e)
	}
}
