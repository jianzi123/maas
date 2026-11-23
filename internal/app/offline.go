package app

import (
	"context"
	"crypto/aes"
	"crypto/cipher"
	"crypto/rand"
	"crypto/sha256"
	"database/sql"
	_ "embed"
	"encoding/json"
	"errors"
	"strconv"
	"strings"
	"time"

	"github.com/google/uuid"
	api "github.com/jianzi123/maas/api/v1alpha1"
	a "github.com/jianzi123/maas/internal/agentruntime"
	"github.com/jianzi123/maas/internal/kernel"
	"github.com/jianzi123/maas/internal/release"
	"github.com/jianzi123/maas/internal/release/mysqlstore"
)

const OfflineAlias = "offline-controlled"

//go:embed migrations/002_offline.sql
var offlineMigration string

type offlineState struct {
	Publication, KeyID string
	Cipher             []byte
}

func offlineUID(cluster, kind string) string {
	return uuid.NewSHA1(uuid.NameSpaceOID, []byte("maas/offline-controlled/"+cluster+"/"+kind)).String()
}
func offlineCrypt(pepper, data []byte, encrypt bool) ([]byte, error) {
	key := sha256.Sum256(append([]byte("offline-platform-key-v1/"), pepper...))
	block, e := aes.NewCipher(key[:])
	if e != nil {
		return nil, e
	}
	g, e := cipher.NewGCM(block)
	if e != nil {
		return nil, e
	}
	if encrypt {
		nonce := make([]byte, g.NonceSize())
		if _, e = rand.Read(nonce); e != nil {
			return nil, e
		}
		return g.Seal(nonce, nonce, data, []byte("maas-offline-key")), nil
	}
	if len(data) < g.NonceSize() {
		return nil, ErrConfig
	}
	return g.Open(nil, data[:g.NonceSize()], data[g.NonceSize():], []byte("maas-offline-key"))
}
func loadOffline(ctx context.Context, db *sql.DB, c Config) (offlineState, error) {
	var s offlineState
	var cluster string
	e := db.QueryRowContext(ctx, "SELECT cluster_id,publication_id,key_id,key_cipher FROM product_offline_state WHERE id=1").Scan(&cluster, &s.Publication, &s.KeyID, &s.Cipher)
	if e != nil {
		return s, e
	}
	if cluster != c.Cluster {
		return s, errors.New("offline_profile_not_initialized")
	}
	return s, nil
}

// These witnesses are explicitly scoped to ONE offline publication/key. They
// never approve a production profile, real gateway or other platform key.
type offlineProofs struct{ UID, PubID, Source string }

func (p offlineProofs) Publication(ctx context.Context, tx *sql.Tx, pub mysqlstore.Publication) (mysqlstore.Evidence, error) {
	if pub.CRUID != p.UID || (p.PubID != "" && pub.PublicationID != p.PubID) {
		return mysqlstore.Evidence{}, release.ErrDependencyMissing
	}
	var now time.Time
	if e := tx.QueryRowContext(ctx, "SELECT UTC_TIMESTAMP(6)").Scan(&now); e != nil {
		return mysqlstore.Evidence{}, e
	}
	return mysqlstore.Evidence{CRUID: pub.CRUID, Binding: pub.Binding, FreshUntil: now.Add(time.Minute), RuntimeReady: true, GatewayApplied: true, AccountingReady: true, ValidationPassed: true, Refs: []string{offlineUID(p.UID, "witness")}}, nil
}
func (p offlineProofs) Closure(_ context.Context, _ *sql.Tx, s kernel.Snapshot, ref string) (kernel.Closure, error) {
	if s.Input.Profile.SourceID != p.Source || s.Input.Profile.Binding.PublicationID != p.PubID {
		return kernel.Closure{}, kernel.ErrUnavailable
	}
	return kernel.Closure{ID: ref, Kind: "upstream_transport_closed", RequestID: s.Input.RequestID, TicketHash: s.Input.TicketHash, GatewayInstance: s.Input.Profile.GatewayInstance, GatewayEpoch: s.Input.Profile.GatewayEpoch, SlotID: s.SlotID, AllocationFence: s.AllocationFence, Sealed: true, Attempts: 1, Observed: time.Now().UTC()}, nil
}

type offlineRate struct{ Key string }

func (r offlineRate) Acquire(_ context.Context, request, key string, p kernel.RatePolicy) (kernel.Permit, error) {
	if key != r.Key {
		return kernel.Permit{}, kernel.ErrUnavailable
	}
	start := time.UnixMilli(time.Now().UnixMilli() / p.WindowMS * p.WindowMS).UTC()
	end := start.Add(time.Duration(p.WindowMS) * time.Millisecond)
	return kernel.Permit{ID: uuid.NewString(), Epoch: p.Epoch, PolicyID: p.Revision, Revision: p.Revision, Windows: []kernel.RateWindow{{Scope: "global", Start: start.Format(time.RFC3339Nano), End: end.Format(time.RFC3339Nano), Limit: strconv.FormatInt(p.GlobalLimit, 10)}, {Scope: "key/" + key, Start: start.Format(time.RFC3339Nano), End: end.Format(time.RFC3339Nano), Limit: strconv.FormatInt(p.KeyLimit, 10)}}}, nil
}

func initializeOffline(ctx context.Context, db *sql.DB, c Config) error {
	if !c.Offline.Enabled {
		return nil
	}
	pepper, e := secret(c.Secrets.PepperFile, 32, 4096)
	if e != nil {
		return e
	}
	var unrelated int
	source := offlineUID(c.Cluster, "source")
	if e = db.QueryRowContext(ctx, "SELECT COUNT(*) FROM invocation_profiles WHERE JSON_UNQUOTE(JSON_EXTRACT(snapshot_json,'$.SourceID'))<>?", source).Scan(&unrelated); e != nil || unrelated != 0 {
		return errors.New("offline_requires_dedicated_model_store")
	}
	existing, loadErr := loadOffline(ctx, db, c)
	if loadErr != nil && !errors.Is(loadErr, sql.ErrNoRows) {
		return loadErr
	}
	if loadErr == nil {
		key, e := offlineCrypt(pepper, existing.Cipher, false)
		if e != nil {
			return errors.New("offline_key_decryption_failed")
		}
		core, e := kernel.New(db, c.Cluster, pepper, nil, nil)
		if e != nil {
			return e
		}
		id, _, e := core.Authenticate(ctx, string(key))
		for i := range key {
			key[i] = 0
		}
		if e != nil || id != existing.KeyID {
			return errors.New("offline_key_state_invalid")
		}
		return nil
	}
	var rows int
	if e = db.QueryRowContext(ctx, "SELECT COUNT(*) FROM key_metadata WHERE name='offline-controlled-internal-key'").Scan(&rows); e != nil {
		return e
	}
	if rows != 0 {
		return errors.New("offline_seed_needs_reconciliation")
	}
	proofs := offlineProofs{UID: offlineUID(c.Cluster, "release"), Source: source}
	core, e := kernel.New(db, c.Cluster, pepper, offlineRate{}, proofs)
	if e != nil {
		return e
	}
	gate, e := mysqlstore.New(db, c.Cluster, core)
	if e != nil {
		return e
	}
	revision := sum("offline-controlled-v1/" + c.Cluster + "/" + c.Agent.Limits.Currency)
	d := release.Desired{CRUID: proofs.UID, Namespace: "maas-offline", Name: OfflineAlias, Alias: OfflineAlias, Gateway: api.Ref{Name: "offline-controlled-not-higress"}, Generation: 1, Revision: revision}
	state, e := gate.Observe(ctx, d)
	if e != nil {
		return e
	}
	if state.Candidate == nil {
		return errors.New("offline_publication_missing")
	}
	proofs.PubID = state.Candidate.PublicationID
	core, e = kernel.New(db, c.Cluster, pepper, offlineRate{}, proofs)
	if e != nil {
		return e
	}
	gate, e = mysqlstore.New(db, c.Cluster, core)
	if e != nil {
		return e
	}
	p := kernel.Profile{CRUID: d.CRUID, Namespace: d.Namespace, Name: d.Name, Alias: d.Alias, Binding: *state.Candidate, SourceID: source, SourceType: "internal", UpstreamModel: "offline-controlled-v1", ConfigRevision: "offline-controlled-v1", CapabilityRevision: "offline-controlled-tools-v1", RouteID: "offline-controlled-route", RouteName: "offline-controlled-route", RouteDigest: revision, GatewayBinding: "offline-controlled", GatewayInstance: offlineUID(c.Cluster, "gateway"), GatewayEpoch: 1, Host: "offline.invalid", SafetyProfile: "explicit-offline-only", ApprovalRef: "controlled-not-production", BoundVerified: true, InputUpper: 64, OutputUpper: 32, Catalog: &kernel.CatalogMetadata{DisplayName: "离线受控模型（不调用供应商）", Capabilities: map[string]any{"streaming": true, "verified_max_output_tokens": 32, "temperature_supported": false, "usage_available": "verified", "capability_revision": "offline-controlled-tools-v1", "hard_budget_status": "verified", "budget_unavailable_reason": nil, "protocols": []string{"chat_completions"}}}}
	p.Price = &kernel.Price{ID: offlineUID(c.Cluster, "price"), Version: "offline-controlled-price-v1", Source: source, Model: p.UpstreamModel, Currency: c.Agent.Limits.Currency, Scale: 9, Unit: 1000000, Effective: "2026-01-01T00:00:00Z", Input: "1000000", Cached: "1000000", Output: "1000000", Reasoning: "1000000"}
	if e = core.RegisterProfile(ctx, p); e != nil {
		return e
	}
	state, e = gate.Read(ctx, d.CRUID)
	if e != nil {
		return e
	}
	target := p.Binding.PublicationID
	if e = gate.Apply(ctx, release.Command{ID: uuid.NewString(), Action: "Activate", CRUID: d.CRUID, Generation: state.Generation, Fence: state.Fence, Target: &target, Revision: state.Revision, EvidenceRefs: state.EvidenceRefs}); e != nil {
		return e
	}
	requests := "1000000"
	_, raw, e := core.CreateManagedKey(ctx, "offline-controlled-internal-key", kernel.Policy{Window: "utc_day", Revision: "offline-controlled-budget", Limits: kernel.Limits{Requests: &requests, Tokens: &c.Agent.Limits.Tokens, Money: &kernel.MoneyLimit{Currency: c.Agent.Limits.Currency, Limit: c.Agent.Limits.Money}}})
	if e != nil {
		return e
	}
	id, _, e := core.Authenticate(ctx, raw)
	if e != nil {
		return e
	}
	encrypted, e := offlineCrypt(pepper, []byte(raw), true)
	if e != nil {
		return e
	}
	if _, e = db.ExecContext(ctx, "INSERT INTO product_offline_state(id,cluster_id,publication_id,key_id,key_cipher) VALUES(1,?,?,?,?)", c.Cluster, p.Binding.PublicationID, id, encrypted); e != nil {
		return e
	}
	// This is the explicit synthetic rate producer's initial epoch, NOT a claim
	// that production Redis has been reconstructed or production is Ready.
	return core.ReadyRate(ctx, c.Ledger.Epoch)
}

type OfflineModel struct {
	Config  Config
	Core    *kernel.Store
	Gate    kernel.ActiveGate
	Profile kernel.Profile
	State   offlineState
	Key     []byte
}

func (o *OfflineModel) Close() {
	for i := range o.Key {
		o.Key[i] = 0
	}
}
func (o *OfflineModel) Namespaces() map[string]bool {
	return map[string]bool{o.Profile.Namespace: true}
}
func (o *OfflineModel) Visible(_ context.Context, p a.Principal) ([]string, error) {
	if !p.Permissions["models.read"] {
		return nil, a.ErrForbidden
	}
	return []string{OfflineAlias}, nil
}
func (o *OfflineModel) Resolve(_ context.Context, p a.Principal, alias, mode string) (a.Model, error) {
	if alias != OfflineAlias || !p.Permissions["models.read"] {
		return a.Model{}, a.ErrCapability
	}
	protocol := "text-v1"
	if mode == "agent" {
		protocol = "tools-v1"
	}
	return a.Model{Alias: alias, Source: o.Profile.SourceID, Revision: o.Profile.ConfigRevision, Protocol: protocol}, nil
}
func (o *OfflineModel) Modes(context.Context, a.Principal) ([]map[string]any, error) {
	return []map[string]any{{"model_alias": OfflineAlias, "text_protocol": "text-v1", "tools_protocol": "tools-v1", "capability_revision": o.Profile.CapabilityRevision, "approval_state": "controlled"}}, nil
}
func (o *OfflineModel) Supports(_ context.Context, m a.Model) error {
	if m.Alias != OfflineAlias || m.Source != o.Profile.SourceID || m.Revision != o.Profile.ConfigRevision || (m.Protocol != "text-v1" && m.Protocol != "tools-v1") {
		return a.ErrCapability
	}
	return nil
}
func (o *OfflineModel) CountContext(context.Context, a.Request) (int64, error) {
	return o.Profile.InputUpper, nil
}
func (o *OfflineModel) Generate(ctx context.Context, r a.Request, emit func(string) error) (response a.Response, err error) {
	response.RequestID = r.RequestID
	if e := o.Supports(ctx, r.Model); e != nil {
		return response, e
	}
	existing, e := o.Core.LookupRequest(ctx, r.RequestID)
	if e != nil {
		return response, e
	}
	if data, ok := existing["data"].([]any); ok && len(data) > 0 {
		response.OutcomeUnknown = true
		return response, a.ErrConflict
	}
	id, epoch, e := o.Core.Authenticate(ctx, string(o.Key))
	if e != nil {
		return response, e
	}
	policy, rate, e := o.Core.AdmissionConfiguration(ctx, id)
	if e != nil {
		return response, e
	}
	plan, e := kernel.BuildPlan(o.Profile, policy, rate.Revision)
	if e != nil {
		return response, e
	}
	reserved, _ := strconv.ParseInt(*plan.Tokens, 10, 64)
	money, _ := strconv.ParseInt(*plan.Money, 10, 64)
	if reserved > r.TokenUpper || money > r.MoneyUpper || r.Currency != *plan.Currency {
		return response, a.ErrInvalid
	}
	now := time.Now().UTC().Truncate(time.Millisecond)
	deadline := now.Add(time.Minute)
	if d, ok := ctx.Deadline(); ok {
		deadline = d
	}
	expires := now.Add(time.Millisecond)
	if !expires.Before(deadline) {
		return response, context.DeadlineExceeded
	}
	in := kernel.Input{Purpose: "serving", RequestID: r.RequestID, KeyID: id, KeyEpoch: epoch, Owner: offlineUID(o.Config.Cluster, "model-owner"), TicketHash: sum("offline-controlled/" + r.RequestID), Profile: o.Profile, Plan: plan, Received: now.Add(-time.Millisecond), Issued: now, Expires: expires, Deadline: deadline}
	// Issued/expiry are checked against DB time. Keep a small bounded allowance
	// while still respecting the actual parent deadline.
	in.Expires = now.Add(500 * time.Millisecond)
	if !in.Expires.Before(deadline) {
		return response, context.DeadlineExceeded
	}
	snapshot, e := o.Core.Admit(ctx, o.Gate, in)
	if e != nil {
		response.OutcomeUnknown = errors.Is(e, kernel.ErrCommitUnknown)
		return response, e
	}
	defer func() {
		read, cancel := context.WithTimeout(context.WithoutCancel(ctx), 5*time.Second)
		defer cancel()
		result := "succeeded"
		if err != nil {
			result = "failed"
		}
		if ctx.Err() != nil {
			result = "cancelled"
		}
		i, out, total, zero := int64(6), int64(4), int64(10), int64(0)
		final := kernel.Final{EventID: uuid.NewSHA1(uuid.NameSpaceOID, []byte(r.RequestID+"/terminal")).String(), RequestID: r.RequestID, Owner: in.Owner, OwnerFence: snapshot.OwnerFence, Result: result, Submitted: true, EvidenceRef: uuid.NewSHA1(uuid.NameSpaceOID, []byte(r.RequestID+"/closure")).String(), Usage: kernel.Usage{Input: &i, Output: &out, Total: &total, Cached: &zero, Reasoning: &zero, Source: "upstream"}}
		if e := o.Core.Finalize(read, final); e != nil {
			response.OutcomeUnknown = true
			err = e
			return
		}
		projection := &Models{Core: o.Core}
		u, e := projection.usage(read, r.RequestID)
		if e != nil {
			response.OutcomeUnknown = true
			err = e
			return
		}
		response.Usage = u
		response.TerminalConfirmed = true
	}()
	delay := time.Duration(o.Config.Offline.StepDelayMS) * time.Millisecond
	if delay > 0 {
		timer := time.NewTimer(delay)
		select {
		case <-ctx.Done():
			timer.Stop()
			return response, ctx.Err()
		case <-timer.C:
		}
	}
	observed := map[string]bool{}
	for _, msg := range r.Messages {
		if msg.RunID == r.RunID && msg.Role == "tool" {
			for _, part := range msg.Parts {
				observed[part.Name] = true
			}
		}
	}
	if r.Model.Protocol == "tools-v1" && (!observed["bounded_arithmetic"] || !observed["list_visible_models"]) {
		response.Finish = "tool_calls"
		response.Calls = []a.Call{{ID: uuid.NewSHA1(uuid.NameSpaceOID, []byte(r.RequestID+"/calculate")).String(), Name: "bounded_arithmetic", Arguments: json.RawMessage(`{"a":6,"b":7,"op":"multiply"}`)}, {ID: uuid.NewSHA1(uuid.NameSpaceOID, []byte(r.RequestID+"/models")).String(), Name: "list_visible_models", Arguments: json.RawMessage(`{}`)}}
		return response, nil
	}
	response.Finish = "stop"
	answer := []string{"【离线受控模型；未调用真实供应商】", "6 × 7 = 42。", "目录工具仅返回当前授权的离线模型。"}
	if r.Model.Protocol == "text-v1" {
		answer = []string{"【离线受控模型；未调用真实供应商】", "这是MySQL持久化Chat演示🙂。"}
	}
	for _, chunk := range answer {
		if e := emit(chunk); e != nil {
			return response, e
		}
		if delay > 0 {
			timer := time.NewTimer(delay)
			select {
			case <-ctx.Done():
				timer.Stop()
				return response, ctx.Err()
			case <-timer.C:
			}
		}
	}
	return response, nil
}

type approvalTool struct{ a.Tool }

func (t approvalTool) Spec() a.ToolSpec { s := t.Tool.Spec(); s.Approval = true; return s }

var _ a.ModelClient = (*OfflineModel)(nil)
var _ = strings.TrimSpace
