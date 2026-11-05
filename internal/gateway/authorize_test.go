package gateway

import (
	"context"
	"crypto/hmac"
	"crypto/sha256"
	"database/sql"
	"encoding/base64"
	"encoding/json"
	"github.com/jianzi123/maas/internal/kernel"
	"github.com/jianzi123/maas/internal/protocol"
	"github.com/jianzi123/maas/internal/release"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

type admissionFixture struct {
	p     kernel.Profile
	count int
	err   error
}

func (f *admissionFixture) Profile(context.Context, string) (kernel.Profile, error) { return f.p, nil }
func (f *admissionFixture) Admit(context.Context, kernel.ActiveGate, kernel.Input) (kernel.Snapshot, error) {
	f.count++
	return kernel.Snapshot{}, f.err
}

type gateFixture struct{}

func (gateFixture) LockActive(context.Context, *sql.Tx, string) (release.Binding, error) {
	return release.Binding{}, nil
}
func TestAuthorizerConsumerContract(t *testing.T) {
	uid := "00000000-0000-4000-8000-000000000001"
	digest := strings.Repeat("a", 64)
	f := &admissionFixture{p: kernel.Profile{CRUID: uid, Alias: "synthetic", Binding: release.Binding{PublicationID: uid, Revision: digest, Generation: 1, Epoch: 1}, RouteID: "route-v1", RouteDigest: digest, ConfigRevision: "cfg-v1", GatewayBinding: "gateway-v1", GatewayInstance: uid, GatewayEpoch: 1, Host: "synthetic.internal", RouteName: "route-v1"}}
	key := []byte(strings.Repeat("s", 32))
	a := &Authorizer{Core: f, Gate: gateFixture{}, Key: key, Kid: "test-key", SignerOwner: uid, Instance: uid, Epoch: 1, Peer: func(*http.Request) bool { return true }}
	plan := kernel.Plan{Version: "1.0", Alias: "synthetic", SourceID: uid, ConfigRevision: "cfg-v1", CapabilityRevision: "cap-v1", PolicyRevision: "budget-v1", Window: "utc_day", Metric: "prompt_plus_completion", Requests: "1", RateRevision: "rate-v1"}
	pb, _ := json.Marshal(plan)
	pb, _ = protocol.Canonical(pb)
	hb, _ := json.Marshal(map[string]any{"alg": "HS256", "kid": "test-key", "typ": "maas-admission+jws", "v": 3})
	hb, _ = protocol.Canonical(hb)
	claims := map[string]any{"aud": "maas-infer-admission-v3", "ticket_version": 3, "request_id": uid, "key_id": uid, "owner_instance_id": uid, "key_epoch": 1, "model_alias": "synthetic", "route_id": "route-v1", "config_revision": "cfg-v1", "gateway_binding_id": "gateway-v1", "upstream_host": "synthetic.internal", "method": "POST", "path": "/v1/chat/completions", "body_sha256": digest, "received_at_ms": 1, "issued_at_ms": 1, "expires_at_ms": 2, "hard_deadline_ms": 3, "budget_plan_sha256": protocol.Digest(pb), "model_release_uid": uid, "model_release_generation": 1, "release_revision": digest, "publication_id": uid, "activation_epoch": 1, "route_binding_sha256": digest, "admission_purpose": "serving"}
	cb, _ := json.Marshal(claims)
	cb, _ = protocol.Canonical(cb)
	input := base64.RawURLEncoding.EncodeToString(hb) + "." + base64.RawURLEncoding.EncodeToString(cb)
	mac := hmac.New(sha256.New, key)
	mac.Write([]byte(input))
	ticket := input + "." + base64.RawURLEncoding.EncodeToString(mac.Sum(nil))
	request := func() *http.Request {
		r := httptest.NewRequest("POST", "https://auth.internal/internal/v1/authorize", nil)
		for k, v := range map[string]string{"X-Request-ID": uid, "X-Maas-Admission-Ticket": ticket, "X-Maas-Reservation-Plan": base64.RawURLEncoding.EncodeToString(pb), "X-Maas-Auth-Route-Name": "route-v1", "X-Forwarded-Method": "POST", "X-Forwarded-Uri": "/v1/chat/completions", "X-Forwarded-Host": "synthetic.internal", "X-Forwarded-Proto": "https"} {
			r.Header.Set(k, v)
		}
		return r
	}
	w := httptest.NewRecorder()
	a.ServeHTTP(w, request())
	if w.Code != 200 || f.count != 1 || w.Header().Get("X-Maas-Admission-Id") != uid {
		t.Fatal(w.Code, f.count)
	}
	f.err = kernel.ErrCommitUnknown
	w = httptest.NewRecorder()
	a.ServeHTTP(w, request())
	if w.Code == 200 {
		t.Fatal("unknown commit replays success")
	}
	f.err = nil
	before := f.count
	r := request()
	r.Header.Add("X-Request-ID", uid)
	w = httptest.NewRecorder()
	a.ServeHTTP(w, r)
	if w.Code != 403 || f.count != before {
		t.Fatal("duplicate sensitive header")
	}
	r = request()
	r.Header.Set("X-Forwarded-Host", "wrong.internal")
	w = httptest.NewRecorder()
	a.ServeHTTP(w, r)
	if w.Code != 403 || f.count != before {
		t.Fatal("wrong trusted route")
	}
	a.Peer = nil
	w = httptest.NewRecorder()
	a.ServeHTTP(w, request())
	if w.Code == 200 {
		t.Fatal("missing identity adapter")
	}
}
