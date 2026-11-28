package publisher

import (
	"context"
	"crypto/tls"
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestConfigurationFailClosed(t *testing.T) {
	dir := t.TempDir()
	c := Config{Listen: "127.0.0.1:8443", Cluster: "local-controlled", DSNFile: "publisher.dsn", ServerCertificate: "server.crt", ServerKey: "server.key", ClientCA: "operator-ca.crt", OperatorIdentity: operatorID}
	b, _ := json.Marshal(c)
	path := filepath.Join(dir, "publisher.json")
	write := func(s string) {
		t.Helper()
		if e := os.WriteFile(path, []byte(s), 0600); e != nil {
			t.Fatal(e)
		}
	}
	write(string(b))
	loaded, e := Load(path)
	if e != nil || loaded.DSNFile != filepath.Join(dir, "publisher.dsn") {
		t.Fatal(loaded, e)
	}
	for _, body := range []string{string(b) + "{}", strings.TrimSuffix(string(b), "}") + `,"cluster_id":"other"}`, strings.TrimSuffix(string(b), "}") + `,"proofs_ready":true}`, strings.Replace(string(b), operatorID, "https://untrusted", 1), strings.Replace(string(b), "local-controlled", "../other", 1), strings.Repeat("x", 16385)} {
		write(body)
		if _, e = Load(path); !errors.Is(e, ErrConfiguration) {
			t.Fatal("configuration accepted", e)
		}
	}
	write(string(b))
	if _, e = loaded.TLS(); !errors.Is(e, ErrConfiguration) {
		t.Fatal("missing TLS accepted")
	}
	for _, dsn := range []string{"", "root:private-secret@tcp(127.0.0.1:1)/db?parseTime=true", "private-malformed-secret", "publisher@unix(/not-an-owned-socket)/db?parseTime=true&timeout=1s&readTimeout=1s&writeTimeout=1s&time_zone=%27%2B00%3A00%27&multiStatements=true", "publisher@tcp(127.0.0.1:1)/db?parseTime=true&timeout=1s&readTimeout=1s&writeTimeout=1s&time_zone=%27%2B00%3A00%27&tls=skip-verify"} {
		if e = os.WriteFile(loaded.DSNFile, []byte(dsn), 0600); e != nil {
			t.Fatal(e)
		}
		if _, e = loaded.Open(context.Background()); e == nil || strings.Contains(e.Error(), "secret") {
			t.Fatal("DSN accepted/disclosed", e)
		}
	}
	server, _, _ := certificates(t)
	if server.ClientAuth != tls.RequireAndVerifyClientCert || server.MinVersion != tls.VersionTLS13 {
		t.Fatal("TLS test contract")
	}
}
