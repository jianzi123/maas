package app

import (
	"context"
	"crypto/hmac"
	"crypto/sha256"
	"database/sql"
	"encoding/base64"
	"encoding/json"
	"strconv"
	"sync"
	"time"

	a "github.com/jianzi123/maas/internal/agentruntime"
	"github.com/jianzi123/maas/internal/agentruntime/kernelmodel"
	"github.com/jianzi123/maas/internal/kernel"
	"github.com/jianzi123/maas/internal/protocol"
)

type Models struct {
	DB     *sql.DB
	Config Config
	Core   *kernel.Store
	Gate   kernel.ActiveGate
	mu     sync.Mutex
	relay  *kernel.Relay
}

func (m *Models) Open() error {
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	return m.diagnosticReady(ctx)
}
func (m *Models) Close() {
	m.mu.Lock()
	defer m.mu.Unlock()
	if m.relay != nil {
		m.relay.Close()
	}
}
func (m *Models) entry(alias string) (ModelConfig, error) {
	for _, e := range m.Config.Models {
		if e.Alias == alias {
			return e, nil
		}
	}
	return ModelConfig{}, a.NewFailure(422, "model_not_configured")
}
func (m *Models) profile(ctx context.Context, alias string) (ModelConfig, kernel.Profile, error) {
	e, err := m.entry(alias)
	if err != nil {
		return e, kernel.Profile{}, err
	}
	p, err := m.Core.Profile(ctx, e.PublicationID)
	if err != nil || p.Alias != alias {
		return e, p, a.NewFailure(422, "model_publication_unavailable")
	}
	return e, p, nil
}
func (m *Models) Namespaces() map[string]bool {
	out := map[string]bool{}
	for _, e := range m.Config.Models {
		ctx, cancel := context.WithTimeout(context.Background(), time.Second)
		_, p, err := m.profile(ctx, e.Alias)
		cancel()
		if err == nil {
			out[p.Namespace] = true
		}
	}
	return out
}
func (m *Models) Visible(ctx context.Context, p a.Principal) ([]string, error) {
	if !p.Permissions["models.read"] {
		return nil, a.ErrForbidden
	}
	out := []string{}
	for _, e := range m.Config.Models {
		if _, _, err := m.profile(ctx, e.Alias); err == nil {
			out = append(out, e.Alias)
		}
	}
	return out, nil
}
func (m *Models) Resolve(ctx context.Context, p a.Principal, alias, mode string) (a.Model, error) {
	e, profile, err := m.profile(ctx, alias)
	if err != nil {
		return a.Model{}, err
	}
	if !p.Permissions["models.read"] {
		return a.Model{}, a.ErrForbidden
	}
	if mode == "agent" && (e.Protocol != "tools-v1" || !toolsConfigured(e, profile)) {
		return a.Model{}, a.NewFailure(422, "tools_protocol_unavailable")
	}
	modelProtocol := "text-v1"
	if mode == "agent" {
		modelProtocol = "tools-v1"
	}
	view, err := m.Core.AdminModels(ctx, m.Gate, map[string]bool{profile.Namespace: true})
	if err != nil {
		return a.Model{}, a.ErrUnavailable
	}
	callable := false
	if rows, ok := view["data"].([]any); ok {
		for _, row := range rows {
			record, _ := row.(map[string]any)
			if record["id"] == alias && record["callable"] == true {
				callable = true
			}
		}
	}
	if !callable {
		return a.Model{}, a.NewFailure(422, "release_not_callable")
	}
	if _, err = secret(e.PlatformKeyFile, 40, 128); err != nil {
		return a.Model{}, a.NewFailure(503, "model_credentials_unavailable")
	}
	if err = m.diagnosticReady(ctx); err != nil {
		return a.Model{}, err
	}
	if _, err = m.openRelay(); err != nil {
		return a.Model{}, err
	}
	return a.Model{Alias: alias, Source: profile.SourceID, Revision: profile.ConfigRevision, Protocol: modelProtocol}, nil
}
func (m *Models) Modes(ctx context.Context, p a.Principal) ([]map[string]any, error) {
	out := []map[string]any{}
	for _, e := range m.Config.Models {
		revision, state := "pending", "pending"
		_, profile, err := m.profile(ctx, e.Alias)
		if err == nil {
			revision = profile.CapabilityRevision
		}
		if _, err = m.Resolve(ctx, p, e.Alias, "chat"); err == nil {
			state = "approved"
		}
		var tools any
		if toolsConfigured(e, profile) && state == "approved" {
			tools = "tools-v1"
		}
		out = append(out, map[string]any{"model_alias": e.Alias, "text_protocol": "text-v1", "tools_protocol": tools, "capability_revision": revision, "approval_state": state})
	}
	return out, nil
}
func (m *Models) Supports(ctx context.Context, model a.Model) error {
	c, p, e := m.profile(ctx, model.Alias)
	if e != nil {
		return e
	}
	if model.Protocol != "text-v1" && (model.Protocol != "tools-v1" || !toolsConfigured(c, p)) {
		return a.NewFailure(422, "tools_protocol_unavailable")
	}
	if model.Source != p.SourceID || model.Revision != p.ConfigRevision {
		return a.ErrConflict
	}
	return nil
}
func (m *Models) openRelay() (*kernel.Relay, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	if m.relay != nil {
		return m.relay, nil
	}
	g := m.Config.Gateway
	r, e := kernel.OpenRelayTLS(m.Core, kernel.RelayTLSFiles{Endpoint: g.Endpoint, CAFile: g.CAFile, CertificateFile: g.CertificateFile, KeyFile: g.PrivateKeyFile, DialTimeout: time.Duration(g.DialTimeoutMS) * time.Millisecond, HeaderTimeout: time.Duration(g.HeaderTimeoutMS) * time.Millisecond, MaxBytes: g.MaxResponseBytes, MaxLine: g.MaxEventBytes})
	if e != nil {
		return nil, a.NewFailure(503, "gateway_tls_unavailable")
	}
	m.relay = r
	return r, nil
}
func (m *Models) CountContext(ctx context.Context, r a.Request) (int64, error) {
	_, p, e := m.profile(ctx, r.Model.Alias)
	if e != nil {
		return 0, e
	}
	if !p.BoundVerified {
		return 0, a.NewFailure(422, "input_bound_unavailable")
	}
	b, _ := json.Marshal(r.Messages)
	if len(b) > m.Config.Agent.InputBytes {
		return int64(m.Config.Agent.InputBytes + 1), nil
	}
	return p.InputUpper, nil
}
func (m *Models) Generate(ctx context.Context, req a.Request, emit func(string) error) (a.Response, error) {
	if e := m.Supports(ctx, req.Model); e != nil {
		return a.Response{}, e
	}
	relay, e := m.openRelay()
	if e != nil {
		return a.Response{}, e
	}
	client := kernelmodel.RelayModel{Relay: relay, Prepare: m.prepare, Usage: m.usage, FailureResolved: m.resolved}
	return client.Generate(ctx, req, emit)
}
func (m *Models) prepare(ctx context.Context, req a.Request) (kernel.RelayCall, error) {
	if err := m.diagnosticReady(ctx); err != nil {
		return kernel.RelayCall{}, err
	}
	e, p, err := m.profile(ctx, req.Model.Alias)
	if err != nil {
		return kernel.RelayCall{}, err
	}
	if err := m.Supports(ctx, req.Model); err != nil {
		return kernel.RelayCall{}, err
	}
	if len(req.Tools) > 0 && req.Model.Protocol != "tools-v1" {
		return kernel.RelayCall{}, a.NewFailure(422, "tools_protocol_unavailable")
	}
	raw, err := secret(e.PlatformKeyFile, 40, 128)
	if err != nil {
		return kernel.RelayCall{}, a.NewFailure(503, "model_credentials_unavailable")
	}
	keyID, epoch, err := m.Core.Authenticate(ctx, string(raw))
	for i := range raw {
		raw[i] = 0
	}
	if err != nil {
		return kernel.RelayCall{}, err
	}
	policy, rate, err := m.Core.AdmissionConfiguration(ctx, keyID)
	if err != nil {
		return kernel.RelayCall{}, err
	}
	if rate.Revision != m.Config.Gateway.RateRevision {
		return kernel.RelayCall{}, a.NewFailure(503, "rate_policy_mismatch")
	}
	plan, err := kernel.BuildPlan(p, policy, rate.Revision)
	if err != nil {
		return kernel.RelayCall{}, err
	}
	if protocol.Validate("ReservationPlan", plan) != nil {
		return kernel.RelayCall{}, a.NewFailure(503, "reservation_plan_invalid")
	}
	messages := []map[string]string{}
	for _, msg := range req.Messages {
		if req.Model.Protocol == "tools-v1" {
			break
		}
		if msg.Role != "user" && msg.Role != "assistant" {
			return kernel.RelayCall{}, a.NewFailure(422, "text_context_unsupported")
		}
		text := ""
		for _, part := range msg.Parts {
			if part.Type != "text" {
				return kernel.RelayCall{}, a.NewFailure(422, "text_context_unsupported")
			}
			text += part.Text
		}
		messages = append(messages, map[string]string{"role": msg.Role, "content": text})
	}
	requestBody := map[string]any{"model": p.UpstreamModel, "messages": messages, "stream": true, "max_tokens": p.OutputUpper, "stream_options": map[string]any{"include_usage": true}}
	if req.Model.Protocol == "tools-v1" {
		wire, e := kernelmodel.ToolMessages(req.Messages)
		if e != nil {
			return kernel.RelayCall{}, e
		}
		definitions, e := kernelmodel.ToolDefinitions(req.Tools)
		if e != nil {
			return kernel.RelayCall{}, e
		}
		requestBody["messages"] = wire
		if len(definitions) > 0 {
			requestBody["tools"] = definitions
		}
		requestBody["thinking"] = map[string]string{"type": "disabled"}
	}
	body, err := json.Marshal(requestBody)
	if err != nil {
		return kernel.RelayCall{}, err
	}
	if req.Model.Protocol == "tools-v1" {
		body, err = protocol.CanonicalToolJSON(body)
	} else {
		body, err = protocol.Canonical(body)
	}
	if err != nil || len(body) > m.Config.Agent.InputBytes {
		return kernel.RelayCall{}, a.ErrInvalid
	}
	pb, _ := json.Marshal(plan)
	pb, err = protocol.Canonical(pb)
	if err != nil {
		return kernel.RelayCall{}, err
	}
	now := time.Now().UTC().Truncate(time.Millisecond)
	deadline := now.Add(time.Duration(e.TimeoutMS) * time.Millisecond)
	if bound, ok := ctx.Deadline(); ok && bound.Before(deadline) {
		deadline = bound.Truncate(time.Millisecond)
	}
	g := m.Config.Gateway
	expires := now.Add(time.Duration(g.TicketTTLMS) * time.Millisecond)
	if g.TicketTTLMS < 1 || !expires.Before(deadline) {
		return kernel.RelayCall{}, a.NewFailure(503, "request_deadline_too_short")
	}
	signing, err := secret(g.AdmissionKeyFile, 32, 8192)
	if err != nil {
		return kernel.RelayCall{}, a.NewFailure(503, "admission_key_unavailable")
	}
	defer func() {
		for i := range signing {
			signing[i] = 0
		}
	}()
	claims := map[string]any{"aud": "maas-infer-admission-v3", "ticket_version": 3, "request_id": req.RequestID, "key_id": keyID, "owner_instance_id": g.Owner, "key_epoch": epoch, "model_alias": p.Alias, "route_id": p.RouteID, "config_revision": p.ConfigRevision, "gateway_binding_id": p.GatewayBinding, "upstream_host": p.Host, "method": "POST", "path": "/v1/chat/completions", "body_sha256": protocol.Digest(body), "received_at_ms": now.UnixMilli(), "issued_at_ms": now.UnixMilli(), "expires_at_ms": expires.UnixMilli(), "hard_deadline_ms": deadline.UnixMilli(), "budget_plan_sha256": protocol.Digest(pb), "model_release_uid": p.CRUID, "model_release_generation": p.Binding.Generation, "release_revision": p.Binding.Revision, "publication_id": p.Binding.PublicationID, "activation_epoch": p.Binding.Epoch, "route_binding_sha256": p.RouteDigest, "admission_purpose": "serving"}
	header, _ := json.Marshal(map[string]any{"alg": "HS256", "kid": g.Kid, "typ": "maas-admission+jws", "v": 3})
	header, err = protocol.Canonical(header)
	if err != nil {
		return kernel.RelayCall{}, err
	}
	payload, _ := json.Marshal(claims)
	payload, err = protocol.Canonical(payload)
	if err != nil {
		return kernel.RelayCall{}, err
	}
	if protocol.Validate("AdmissionClaims", claims) != nil {
		return kernel.RelayCall{}, a.NewFailure(503, "admission_claims_invalid")
	}
	input := base64.RawURLEncoding.EncodeToString(header) + "." + base64.RawURLEncoding.EncodeToString(payload)
	mac := hmac.New(sha256.New, signing)
	_, _ = mac.Write([]byte(input))
	ticket := input + "." + base64.RawURLEncoding.EncodeToString(mac.Sum(nil))
	encoded := base64.RawURLEncoding.EncodeToString(pb)
	verified, err := protocol.VerifyTicket(ticket, encoded, signing)
	if err != nil {
		return kernel.RelayCall{}, a.ErrInvalid
	}
	in := kernel.Input{Purpose: "serving", RequestID: req.RequestID, KeyID: keyID, KeyEpoch: epoch, Owner: g.Owner, TicketHash: verified.Digest, Profile: p, Plan: plan, Received: now, Issued: now, Expires: expires, Deadline: deadline}
	return kernel.RelayCall{Input: in, Body: body, Ticket: ticket, PlanHeader: encoded, Stream: true, Protocol: req.Model.Protocol}, nil
}

func toolsConfigured(c ModelConfig, p kernel.Profile) bool {
	return c.Protocol == "tools-v1" && c.Adapter == "deepseek-chat-tools/1" && c.Mode == "non-thinking" && p.SupportsTools()
}
func (m *Models) record(ctx context.Context, id string) (map[string]any, error) {
	v, e := m.Core.LookupRequest(ctx, id)
	if e != nil {
		return nil, e
	}
	rows, ok := v["data"].([]any)
	if !ok || len(rows) != 1 {
		return nil, a.ErrUnavailable
	}
	r, ok := rows[0].(map[string]any)
	if !ok || r["request_id"] != id {
		return nil, a.ErrUnavailable
	}
	return r, nil
}
func (m *Models) resolved(ctx context.Context, id string) (bool, error) {
	r, e := m.record(ctx, id)
	if e != nil {
		return false, e
	}
	return r["status"] != "in_progress", nil
}
func (m *Models) usage(ctx context.Context, id string) (a.Usage, error) {
	r, e := m.record(ctx, id)
	if e != nil {
		return a.Usage{}, e
	}
	return projectUsage(r)
}
func projectUsage(r map[string]any) (a.Usage, error) {
	var e error
	b, _ := json.Marshal(r["reservation_plan"])
	var p kernel.Plan
	if json.Unmarshal(b, &p) != nil || p.Tokens == nil || p.Money == nil || p.Currency == nil || p.PriceVersion == nil {
		return a.Usage{}, a.ErrUnavailable
	}
	u := a.Usage{Currency: *p.Currency}
	g := a.ARUsageGroup{Currency: *p.Currency, Price: *p.PriceVersion, KnownTokens: "0", KnownMoney: "0", HeldTokens: "0", HeldMoney: "0", InflightTokens: "0", InflightMoney: "0"}
	if r["status"] == "in_progress" {
		g.InflightTokens = *p.Tokens
		g.InflightMoney = *p.Money
		u.Groups = []a.ARUsageGroup{g}
		return u, nil
	}
	account, ok := r["budget_accounting"].(map[string]any)
	if !ok {
		return u, a.ErrUnavailable
	}
	read := func(key string) (*int64, error) {
		v := account[key]
		if v == nil {
			return nil, nil
		}
		s, ok := v.(string)
		if !ok {
			return nil, a.ErrUnavailable
		}
		n, e := strconv.ParseInt(s, 10, 64)
		if e != nil || n < 0 {
			return nil, a.ErrUnavailable
		}
		return &n, nil
	}
	u.Tokens, e = read("token_actual")
	if e != nil {
		return u, e
	}
	u.Money, e = read("cost_actual_atomic")
	if e != nil {
		return u, e
	}
	if u.Tokens != nil {
		g.KnownTokens = strconv.FormatInt(*u.Tokens, 10)
	} else {
		g.HeldTokens = *p.Tokens
	}
	if u.Money != nil {
		g.KnownMoney = strconv.FormatInt(*u.Money, 10)
	} else {
		g.HeldMoney = *p.Money
	}
	u.Groups = []a.ARUsageGroup{g}
	// Read actual per-dimension settlements, including proven no-send releases.
	// A null actual alone must never be interpreted as either zero or full held.
	token, ok := account["token"].(map[string]any)
	if !ok {
		return u, a.ErrUnavailable
	}
	money, ok := account["money"].(map[string]any)
	if !ok {
		return u, a.ErrUnavailable
	}
	for _, pair := range []struct {
		source      map[string]any
		known, held *string
	}{{token, &g.KnownTokens, &g.HeldTokens}, {money, &g.KnownMoney, &g.HeldMoney}} {
		known, ok := pair.source["known_used"].(string)
		if !ok {
			return u, a.ErrUnavailable
		}
		held, ok := pair.source["unknown_held"].(string)
		if !ok {
			return u, a.ErrUnavailable
		}
		*pair.known = known
		*pair.held = held
	}
	zero := int64(0)
	if token["state"] == "released" && g.KnownTokens == "0" && g.HeldTokens == "0" {
		u.Tokens = &zero
	}
	if money["state"] == "released" && g.KnownMoney == "0" && g.HeldMoney == "0" {
		u.Money = &zero
	}
	u.Groups = []a.ARUsageGroup{g}
	u.Complete = true
	return u, nil
}

var _ a.ModelClient = (*Models)(nil)
