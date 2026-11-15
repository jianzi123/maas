package gateway

import (
	"context"
	"crypto/hmac"
	"crypto/sha256"
	"encoding/base64"
	"encoding/json"
	"github.com/jianzi123/maas/internal/protocol"
	"strings"
	"testing"
	"time"
)

type secretFixture struct {
	version string
	calls   int
}

func (f *secretFixture) Read(context.Context, SecretRef) (SecretValue, error) {
	f.calls++
	return SecretValue{UID: "uid-1", ResourceVersion: f.version, Value: []byte("controlled-test-credential")}, nil
}
func TestSecretAgentPinsMetadataAndFailsClosed(t *testing.T) {
	b := CredentialBinding{Handle: "opaque-1", PublicationID: "publication-1", InstanceID: "instance-1", Epoch: 1, Secret: SecretRef{Namespace: "approved", Name: "provider", UID: "uid-1", ResourceVersion: "10", DataKey: "token"}}
	reader := &secretFixture{version: "10"}
	a, e := NewSecretAgent(reader, []CredentialBinding{b})
	if e != nil {
		t.Fatal(e)
	}
	v, e := a.Lookup(context.Background(), b)
	if e != nil || len(v) == 0 {
		t.Fatal(e)
	}
	v[0] = 'X'
	reader.version = "11"
	v, e = a.Lookup(context.Background(), b)
	if e != nil || v[0] == 'X' {
		t.Fatal("cached snapshot/copy", e)
	}
	wrong := b
	wrong.PublicationID = "other"
	if _, e = a.Lookup(context.Background(), wrong); e == nil {
		t.Fatal("cross-publication lookup")
	}
	restarted, _ := NewSecretAgent(reader, []CredentialBinding{b})
	if _, e = restarted.Lookup(context.Background(), b); e == nil {
		t.Fatal("restart silently substituted latest Secret")
	}
	a.Revoke(b.Handle)
	if _, e = a.Lookup(context.Background(), b); e == nil {
		t.Fatal("revoked handle")
	}
}
func TestReceiptIdentityFreshnessAndConfiguration(t *testing.T) {
	n := time.Now().UTC().Truncate(time.Millisecond)
	r := Receipt{ID: "receipt-1", Instance: "gateway-1", Epoch: 2, Publication: "publication-1", ActivationEpoch: 4, RouteDigest: strings.Repeat("a", 64), ConfigDigest: strings.Repeat("b", 64), PluginDigest: "sha256:" + strings.Repeat("c", 64), CredentialGeneration: "opaque-2", Listener: "private", ObservedMS: n.Add(-time.Second).UnixMilli(), ExpiresMS: n.Add(time.Second).UnixMilli()}
	key := []byte(strings.Repeat("r", 32))
	b, _ := json.Marshal(r)
	b, _ = protocol.Canonical(b)
	mac := hmac.New(sha256.New, key)
	mac.Write(b)
	sig := base64.RawURLEncoding.EncodeToString(mac.Sum(nil))
	expected := ReceiptExpectation{Receipt: r, MaxAge: 10 * time.Second}
	if _, e := VerifyReceipt(b, sig, key, "gateway-1", expected, n); e != nil {
		t.Fatal(e)
	}
	for _, change := range []func(*ReceiptExpectation){func(x *ReceiptExpectation) { x.Epoch++ }, func(x *ReceiptExpectation) { x.ActivationEpoch++ }, func(x *ReceiptExpectation) { x.ConfigDigest = strings.Repeat("d", 64) }, func(x *ReceiptExpectation) { x.CredentialGeneration = "different" }} {
		wrong := expected
		change(&wrong)
		if _, e := VerifyReceipt(b, sig, key, "gateway-1", wrong, n); e == nil {
			t.Fatal("mismatched receipt")
		}
	}
	if _, e := VerifyReceipt(b, sig, key, "wrong-peer", expected, n); e == nil {
		t.Fatal("wrong peer")
	}
	if _, e := VerifyReceipt(b, sig, key, "gateway-1", expected, n.Add(2*time.Second)); e == nil {
		t.Fatal("expired receipt")
	}
	if _, e := VerifyReceipt(b, sig, []byte(strings.Repeat("s", 32)), "gateway-1", expected, n); e == nil {
		t.Fatal("wrong purpose key")
	}
}
