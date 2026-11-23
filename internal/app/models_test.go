package app

import (
	"context"
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/google/uuid"
	api "github.com/jianzi123/maas/api/v1alpha1"
	a "github.com/jianzi123/maas/internal/agentruntime"
	"github.com/jianzi123/maas/internal/kernel"
	"github.com/jianzi123/maas/internal/protocol"
	"github.com/jianzi123/maas/internal/release"
	"github.com/jianzi123/maas/internal/release/mysqlstore"
)

func TestProductConfiguredModelPreparesOriginalTicketWithoutSending(t *testing.T) {
	c, db := productFixture(t)
	ctx := context.Background()
	if e := Migrate(ctx, c); e != nil {
		t.Fatal(e)
	}
	pepper, e := secret(c.Secrets.PepperFile, 32, 4096)
	if e != nil {
		t.Fatal(e)
	}
	core, e := kernel.New(db, c.Cluster, pepper, nil, nil)
	if e != nil {
		t.Fatal(e)
	}
	gate, e := mysqlstore.New(db, c.Cluster, core)
	if e != nil {
		t.Fatal(e)
	}
	desired := release.Desired{CRUID: uuid.NewString(), Namespace: "product-test", Name: "provider-config", Alias: "configured", Gateway: api.Ref{Name: "higress"}, Generation: 1, Revision: strings.Repeat("a", 64)}
	state, e := gate.Observe(ctx, desired)
	if e != nil {
		t.Fatal(e)
	}
	p := kernel.Profile{CRUID: desired.CRUID, Namespace: desired.Namespace, Name: desired.Name, Alias: desired.Alias, Binding: *state.Candidate, SourceID: uuid.NewString(), SourceType: "external", UpstreamModel: "configured-upstream", ConfigRevision: "config-test-v1", CapabilityRevision: "text-test-v1", RouteDigest: strings.Repeat("b", 64), RouteName: "configured-route", GatewayBinding: "configured-binding", GatewayInstance: uuid.NewString(), GatewayEpoch: 1, Host: "approved.internal", SafetyProfile: "test-only", ApprovalRef: "controlled-setup-not-production", BoundVerified: true, InputUpper: 100, OutputUpper: 40}
	p.Price = &kernel.Price{ID: uuid.NewString(), Version: "test-price", Source: p.SourceID, Model: p.UpstreamModel, Currency: "USD", Scale: 9, Unit: 1000000, Effective: "2026-01-01T00:00:00Z", Input: "2000000000", Cached: "2000000000", Output: "8000000000", Reasoning: "8000000000"}
	p.RouteID = "configured-route-id"
	if e = core.RegisterProfile(ctx, p); e != nil {
		t.Fatal(e)
	}
	requests, tokens := "100", "14000"
	_, key, e := core.CreateManagedKey(ctx, "model-runtime", kernel.Policy{Window: "utc_day", Revision: "test-key-policy", Limits: kernel.Limits{Requests: &requests, Tokens: &tokens, Money: &kernel.MoneyLimit{Currency: "USD", Limit: "52000000"}}})
	if e != nil {
		t.Fatal(e)
	}
	dir := t.TempDir()
	keyfile := filepath.Join(dir, "platform-key")
	signfile := filepath.Join(dir, "admission-key")
	if e = os.WriteFile(keyfile, []byte(key), 0600); e != nil {
		t.Fatal(e)
	}
	signing := []byte(strings.Repeat("s", 32))
	if e = os.WriteFile(signfile, signing, 0600); e != nil {
		t.Fatal(e)
	}
	c.Models = []ModelConfig{{Alias: p.Alias, PublicationID: p.Binding.PublicationID, PlatformKeyFile: keyfile, Protocol: "text-v1", TimeoutMS: 5000}}
	c.Gateway = GatewayConfig{AdmissionKeyFile: signfile, Kid: "test-signer", Owner: uuid.NewString(), RateRevision: c.Ledger.Revision, TicketTTLMS: 1000}
	m := &Models{Config: c, Core: core, Gate: gate}
	req := a.Request{RequestID: uuid.NewString(), Model: a.Model{Alias: p.Alias, Source: p.SourceID, Revision: p.ConfigRevision, Protocol: "text-v1"}, Messages: []a.Message{{Role: "user", Parts: []a.Part{{Type: "text", Text: "configuration witness"}}}}, TokenUpper: 1000, MoneyUpper: 1000000, Currency: "USD", ContextTokenLimit: 100}
	call, e := m.prepare(ctx, req)
	if e != nil {
		t.Fatal(e)
	}
	ticket, e := protocol.VerifyTicket(call.Ticket, call.PlanHeader, signing)
	if e != nil {
		t.Fatal(e)
	}
	if ticket.Claims["request_id"] != req.RequestID || ticket.Claims["upstream_host"] != p.Host || call.Input.Profile.Binding != p.Binding {
		t.Fatal("configuration binding lost")
	}
	var body map[string]any
	json.Unmarshal(call.Body, &body)
	if body["model"] != p.UpstreamModel || body["max_tokens"] != float64(40) {
		t.Fatal("body did not consume profile")
	}
	if bound, e := m.CountContext(ctx, req); e != nil || bound != 100 {
		t.Fatal(bound, e)
	}
	req.Model.Protocol = "tools-v1"
	if e = m.Supports(ctx, req.Model); e == nil {
		t.Fatal("tools mode silently accepted")
	}
	var n int
	if e = db.QueryRow("SELECT COUNT(*) FROM generation_requests").Scan(&n); e != nil || n != 0 {
		t.Fatal("prepare sent/admitted a model call", n, e)
	}
}

func TestProductUsageReadsAuthoritativeReleaseAndHeld(t *testing.T) {
	tokens, money, currency, price := "140", "520000", "USD", "price-v1"
	plan := kernel.Plan{Tokens: &tokens, Money: &money, Currency: &currency, PriceVersion: &price}
	for _, state := range []string{"released", "held"} {
		t.Run(state, func(t *testing.T) {
			heldT, heldM := "0", "0"
			if state == "held" {
				heldT, heldM = tokens, money
			}
			record := map[string]any{"status": "failed", "reservation_plan": plan, "budget_accounting": map[string]any{"token_actual": nil, "cost_actual_atomic": nil, "token": map[string]any{"known_used": "0", "unknown_held": heldT, "state": state}, "money": map[string]any{"known_used": "0", "unknown_held": heldM, "state": state}}}
			u, e := projectUsage(record)
			if e != nil {
				t.Fatal(e)
			}
			if u.Groups[0].HeldTokens != heldT || u.Groups[0].HeldMoney != heldM {
				t.Fatal("settlement projection changed")
			}
			if state == "released" && (u.Tokens == nil || *u.Tokens != 0) {
				t.Fatal("proven release not represented")
			}
			if state == "held" && (u.Tokens != nil || u.Money != nil) {
				t.Fatal("unknown was changed to zero")
			}
		})
	}
}
