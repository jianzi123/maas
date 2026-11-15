package protocol

import (
	"crypto/hmac"
	"crypto/sha256"
	"encoding/base64"
	"encoding/json"
	"strings"
	"testing"
)

func TestCanonicalRejectsAmbiguity(t *testing.T) {
	for _, b := range []string{`{"a":1,"a":2}`, `{"a":{"b":1,"b":2}}`, `{"a":1e0}`, `{"a":1.0}`, `{"a":9007199254740992}`, `{"a":-1}`, `{} {}`} {
		if _, e := Canonical([]byte(b)); e == nil {
			t.Fatalf("accepted %s", b)
		}
	}
	b, e := Canonical([]byte(`{"z":null,"a":1}`))
	if e != nil || string(b) != `{"a":1,"z":null}` {
		t.Fatal(string(b), e)
	}
}
func signFixture(h, c any, key []byte) string {
	hb, _ := json.Marshal(h)
	hb, _ = Canonical(hb)
	cb, _ := json.Marshal(c)
	cb, _ = Canonical(cb)
	input := base64.RawURLEncoding.EncodeToString(hb) + "." + base64.RawURLEncoding.EncodeToString(cb)
	mac := hmac.New(sha256.New, key)
	mac.Write([]byte(input))
	return input + "." + base64.RawURLEncoding.EncodeToString(mac.Sum(nil))
}
func TestTicketV3StrictPurposeAndPlan(t *testing.T) {
	uid := "00000000-0000-4000-8000-000000000001"
	digest := strings.Repeat("a", 64)
	plan := map[string]any{"schema_version": "1.0", "model_alias": "synthetic", "source_id": uid, "config_revision": "cfg-v1", "capability_revision": "cap-v1", "budget_policy_revision": "budget-v1", "window_kind": "utc_day", "token_metric": "prompt_plus_completion", "request_reserved": "1", "input_upper_tokens": nil, "output_upper_tokens": nil, "total_upper_tokens": nil, "token_reserved": nil, "money_reserved_atomic": nil, "currency": nil, "price_snapshot_id": nil, "price_snapshot_sha256": nil, "price_version": nil, "rate_policy_revision": "rate-v1"}
	pb, _ := json.Marshal(plan)
	pb, _ = Canonical(pb)
	encoded := base64.RawURLEncoding.EncodeToString(pb)
	claims := map[string]any{"aud": "maas-infer-admission-v3", "ticket_version": 3, "request_id": uid, "key_id": uid, "owner_instance_id": uid, "key_epoch": 1, "model_alias": "synthetic", "route_id": "route-v1", "config_revision": "cfg-v1", "gateway_binding_id": "gateway-v1", "upstream_host": "synthetic.internal", "method": "POST", "path": "/v1/chat/completions", "body_sha256": digest, "received_at_ms": 1, "issued_at_ms": 1, "expires_at_ms": 2, "hard_deadline_ms": 3, "budget_plan_sha256": Digest(pb), "model_release_uid": uid, "model_release_generation": 1, "release_revision": digest, "publication_id": uid, "activation_epoch": 1, "route_binding_sha256": digest, "admission_purpose": "serving"}
	header := map[string]any{"alg": "HS256", "kid": "test-key", "typ": "maas-admission+jws", "v": 3}
	key := []byte(strings.Repeat("t", 32))
	ticket := signFixture(header, claims, key)
	if _, e := VerifyTicket(ticket, encoded, key); e != nil {
		t.Fatal("valid frozen v3", e)
	}
	if _, e := VerifyTicket(ticket, encoded+"=", key); e == nil {
		t.Fatal("padding")
	}
	claims["aud"] = "maas-infer-admission-v2"
	if _, e := VerifyTicket(signFixture(header, claims, key), encoded, key); e == nil {
		t.Fatal("old protocol")
	}
	claims["aud"] = "maas-infer-admission-v3"
	claims["unexpected"] = true
	if _, e := VerifyTicket(signFixture(header, claims, key), encoded, key); e == nil {
		t.Fatal("unknown claim")
	}
	delete(claims, "unexpected")
	header["typ"] = "maas-transport-evidence+jws"
	if _, e := VerifyTicket(signFixture(header, claims, key), encoded, key); e == nil {
		t.Fatal("cross-purpose key use")
	}
	if _, e := VerifyTicket(ticket, encoded, []byte(strings.Repeat("q", 32))); e == nil {
		t.Fatal("wrong key")
	}
}
