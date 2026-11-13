package gateway

import (
	"context"
	"encoding/json"
	"errors"
	"github.com/jianzi123/maas/internal/kernel"
	"github.com/jianzi123/maas/internal/protocol"
	"net/http"
	"time"
)

type AdmissionKernel interface {
	Profile(context.Context, string) (kernel.Profile, error)
	Admit(context.Context, kernel.ActiveGate, kernel.Input) (kernel.Snapshot, error)
}

// Candidate H4 consumer bound to one authenticated instance and admission signer.
// No binary registers this handler. An installation needs a private mTLS listener
// and a revocable signer registry adapter before exposing it.
type Authorizer struct {
	ValidationIntentID         string
	Core                       AdmissionKernel
	Gate                       kernel.ActiveGate
	Key                        []byte
	Kid, SignerOwner, Instance string
	Epoch                      int64
	Peer                       func(*http.Request) bool
}

func (a *Authorizer) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Cache-Control", "no-store")
	deny := func(status int, code string) { w.Header().Set("X-Maas-Error-Code", code); w.WriteHeader(status) }
	if a.Core == nil || a.Gate == nil || a.Peer == nil || !a.Peer(r) || len(a.Key) < 32 || a.Instance == "" || a.Epoch < 1 {
		deny(503, "dependency_unavailable")
		return
	}
	if r.Method != "POST" || r.URL.Path != "/internal/v1/authorize" || r.ContentLength > 0 {
		deny(403, "forbidden")
		return
	}
	total := 0
	for k, v := range r.Header {
		for _, s := range v {
			total += len(k) + len(s)
		}
	}
	if total > 16384 {
		deny(403, "forbidden")
		return
	}
	for _, name := range []string{"X-Request-ID", "X-Maas-Admission-Ticket", "X-Maas-Reservation-Plan", "X-Maas-Auth-Route-Name", "X-Forwarded-Method", "X-Forwarded-Uri", "X-Forwarded-Host", "X-Forwarded-Proto"} {
		if len(r.Header.Values(name)) != 1 || r.Header.Get(name) == "" {
			deny(403, "forbidden")
			return
		}
	}
	ticket, e := protocol.VerifyTicket(r.Header.Get("X-Maas-Admission-Ticket"), r.Header.Get("X-Maas-Reservation-Plan"), a.Key)
	if e != nil {
		deny(403, "forbidden")
		return
	}
	c := ticket.Claims
	str := func(k string) string { v, _ := c[k].(string); return v }
	integer := func(k string) int64 { v, _ := c[k].(json.Number); n, _ := v.Int64(); return n }
	expectedPurpose := "serving"
	if a.ValidationIntentID != "" {
		expectedPurpose = "validation"
	}
	if ticket.Header["kid"] != a.Kid || str("owner_instance_id") != a.SignerOwner || str("request_id") != r.Header.Get("X-Request-ID") || str("admission_purpose") != expectedPurpose {
		deny(403, "forbidden")
		return
	}
	profile, e := a.Core.Profile(r.Context(), str("publication_id"))
	if e != nil {
		deny(503, "release_dependency_unavailable")
		return
	}
	if profile.RouteID != str("route_id") || profile.CRUID != str("model_release_uid") || profile.Binding.Generation != integer("model_release_generation") || profile.Binding.Revision != str("release_revision") || profile.Binding.Epoch != integer("activation_epoch") || profile.RouteDigest != str("route_binding_sha256") || profile.ConfigRevision != str("config_revision") || profile.Alias != str("model_alias") || profile.GatewayBinding != str("gateway_binding_id") || profile.GatewayInstance != a.Instance || profile.GatewayEpoch != a.Epoch || profile.Host != str("upstream_host") || profile.RouteName != r.Header.Get("X-Maas-Auth-Route-Name") || r.Header.Get("X-Forwarded-Method") != "POST" || r.Header.Get("X-Forwarded-Uri") != "/v1/chat/completions" || r.Header.Get("X-Forwarded-Proto") != "https" || r.Header.Get("X-Forwarded-Host") != profile.Host {
		deny(403, "forbidden")
		return
	}
	var plan kernel.Plan
	if json.Unmarshal(ticket.Plan, &plan) != nil {
		deny(403, "forbidden")
		return
	}
	in := kernel.Input{Purpose: str("admission_purpose"), ValidationIntentID: a.ValidationIntentID, RequestID: str("request_id"), KeyID: str("key_id"), KeyEpoch: integer("key_epoch"), Owner: str("owner_instance_id"), TicketHash: ticket.Digest, Profile: profile, Plan: plan, Received: time.UnixMilli(integer("received_at_ms")), Issued: time.UnixMilli(integer("issued_at_ms")), Expires: time.UnixMilli(integer("expires_at_ms")), Deadline: time.UnixMilli(integer("hard_deadline_ms"))}
	if _, e = a.Core.Admit(r.Context(), a.Gate, in); e != nil {
		status, code := 503, "dependency_unavailable"
		for _, v := range []struct {
			e      error
			status int
			code   string
		}{{kernel.ErrConflict, 409, "state_conflict"}, {kernel.ErrKey, 401, "invalid_api_key"}, {kernel.ErrCapacity, 429, "concurrency_exceeded"}, {kernel.ErrBusy, 503, "admission_busy"}, {kernel.ErrBudget, 429, "request_budget_exceeded"}, {kernel.ErrTokens, 429, "token_budget_exceeded"}, {kernel.ErrMoney, 429, "money_budget_exceeded"}, {kernel.ErrBound, 503, "budget_bound_unavailable"}, {kernel.ErrPrice, 503, "pricing_unavailable"}, {kernel.ErrPolicy, 409, "policy_changed"}} {
			if errors.Is(e, v.e) {
				status, code = v.status, v.code
				break
			}
		}
		deny(status, code)
		return
	}
	w.Header().Set("X-Request-ID", in.RequestID)
	w.Header().Set("X-Maas-Admission-Id", in.RequestID)
	w.WriteHeader(http.StatusOK)
}
