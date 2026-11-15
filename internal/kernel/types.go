// Package kernel owns the single durable business admission and settlement ledger.
// It has no supplier client and is deliberately not wired into the operator.
package kernel

import (
	"context"
	"database/sql"
	"errors"
	"time"

	"github.com/jianzi123/maas/internal/release"
	"github.com/jianzi123/maas/internal/release/mysqlstore"
)

var (
	ErrUnavailable   = errors.New("dependency_unavailable")
	ErrBusy          = errors.New("admission_busy")
	ErrConflict      = errors.New("state_conflict")
	ErrKey           = errors.New("invalid_api_key")
	ErrBudget        = errors.New("request_budget_exceeded")
	ErrTokens        = errors.New("token_budget_exceeded")
	ErrMoney         = errors.New("money_budget_exceeded")
	ErrCapacity      = errors.New("concurrency_exceeded")
	ErrBound         = errors.New("budget_bound_unavailable")
	ErrPrice         = errors.New("pricing_unavailable")
	ErrPolicy        = errors.New("policy_changed")
	ErrCommitUnknown = errors.New("commit outcome unknown; query durable identity, never retry generation")
)

const maxCounter = int64(9007199254740991)

type Limits struct {
	Requests *string     `json:"requests"`
	Tokens   *string     `json:"tokens"`
	Money    *MoneyLimit `json:"money"`
}
type MoneyLimit struct {
	Currency string `json:"currency"`
	Limit    string `json:"limit_atomic"`
}
type Policy struct {
	Window   string `json:"window_kind"`
	Limits   Limits `json:"limits"`
	Revision string `json:"revision"`
}
type Price struct {
	ID        string `json:"id"`
	Version   string `json:"version"`
	Source    string `json:"source_id"`
	Model     string `json:"upstream_model"`
	Currency  string `json:"currency"`
	Scale     int    `json:"scale"`
	Unit      int64  `json:"tokens_per_price_unit"`
	Effective string `json:"effective_at"`
	Input     string `json:"input_uncached_per_million_atomic"`
	Cached    string `json:"input_cached_per_million_atomic"`
	Output    string `json:"output_visible_per_million_atomic"`
	Reasoning string `json:"output_reasoning_per_million_atomic"`
}

// Profile is an immutable, installation-approved metadata snapshot. It contains
// no endpoint URL, Secret value, or claim that the gateway actually applied it.
type Profile struct {
	UsagePolicy                                                             *UsagePolicy     `json:",omitempty"`
	Catalog                                                                 *CatalogMetadata `json:",omitempty"`
	CRUID, Namespace, Name, Alias                                           string
	Binding                                                                 release.Binding
	SourceID, SourceType, UpstreamModel, ConfigRevision, CapabilityRevision string
	RouteDigest, RouteName, GatewayBinding, GatewayInstance                 string
	GatewayEpoch                                                            int64
	RouteID                                                                 string
	Host, SafetyProfile, ApprovalRef                                        string
	BoundVerified                                                           bool
	InputUpper, OutputUpper                                                 int64
	Price                                                                   *Price
}

type CatalogMetadata struct {
	DisplayName  string         `json:"display_name"`
	Capabilities map[string]any `json:"capabilities"`
}
type Plan struct {
	Version            string  `json:"schema_version"`
	Alias              string  `json:"model_alias"`
	SourceID           string  `json:"source_id"`
	ConfigRevision     string  `json:"config_revision"`
	CapabilityRevision string  `json:"capability_revision"`
	PolicyRevision     string  `json:"budget_policy_revision"`
	Window             string  `json:"window_kind"`
	Metric             string  `json:"token_metric"`
	Requests           string  `json:"request_reserved"`
	Input              *string `json:"input_upper_tokens"`
	Output             *string `json:"output_upper_tokens"`
	Total              *string `json:"total_upper_tokens"`
	Tokens             *string `json:"token_reserved"`
	Money              *string `json:"money_reserved_atomic"`
	Currency           *string `json:"currency"`
	PriceID            *string `json:"price_snapshot_id"`
	PriceHash          *string `json:"price_snapshot_sha256"`
	PriceVersion       *string `json:"price_version"`
	RateRevision       string  `json:"rate_policy_revision"`
}
type RateWindow struct {
	Scope string `json:"scope_id"`
	Start string `json:"window_start"`
	End   string `json:"window_end"`
	Limit string `json:"limit"`
}
type Permit struct {
	ID       string       `json:"permit_id"`
	Epoch    int64        `json:"rate_epoch"`
	PolicyID string       `json:"policy_id"`
	Revision string       `json:"policy_revision"`
	Windows  []RateWindow `json:"windows"`
}
type RatePolicy struct {
	RedisIdentity, RebuildNonce            string
	Revision                               string
	Epoch, WindowMS, GlobalLimit, KeyLimit int64
	Ready                                  bool
}

// RateGate must return permits from its authenticated Redis connection, never
// caller-supplied headers. It executes OUTSIDE any MySQL transaction.
type RateGate interface {
	Acquire(context.Context, string, string, RatePolicy) (Permit, error)
}
type ActiveGate interface {
	LockActive(context.Context, *sql.Tx, string) (release.Binding, error)
}

// Proofs reads previously authenticated evidence using the SAME primary Tx.
// Implementations MUST NOT call Redis/K8s/RPC inside these methods. No production
// implementation is installed until the real H1-H4 trust chain is available.
type Proofs interface {
	Publication(context.Context, *sql.Tx, mysqlstore.Publication) (mysqlstore.Evidence, error)
	Closure(context.Context, *sql.Tx, Snapshot, string) (Closure, error)
}
type Closure struct {
	ID, Kind, RequestID, TicketHash, GatewayInstance string
	GatewayEpoch, SlotID, AllocationFence            int64
	// These are verified receiver metadata, not reporter-controlled booleans.
	Sealed                  bool
	Attempts, ActiveStreams int64
	Observed                time.Time
}
type Input struct {
	Purpose, ValidationIntentID         string
	RequestID, KeyID, Owner, TicketHash string
	KeyEpoch                            int64
	Profile                             Profile
	Plan                                Plan
	Received, Issued, Expires, Deadline time.Time
}
type Snapshot struct {
	Input                               Input
	Policy                              Policy
	Rate                                Permit
	WindowStart, WindowEnd, Admitted    time.Time
	SlotID, AllocationFence, OwnerFence int64
}
type Usage struct {
	Input     *int64  `json:"input_tokens"`
	Output    *int64  `json:"output_tokens"`
	Total     *int64  `json:"total_tokens"`
	Source    string  `json:"source"`
	Missing   *string `json:"missing_reason"`
	Cached    *int64  `json:"input_cached_tokens"`
	Reasoning *int64  `json:"reasoning_tokens"`
}
type Final struct {
	ErrorCode                 string `json:"error_code,omitempty"`
	EventID, RequestID, Owner string
	OwnerFence                int64
	Result                    string
	Usage                     Usage
	EvidenceRef               string
	Submitted                 bool
	FirstChunkMS              *int64
}
type Counter struct{ Known, Reserved, Held string }
type Store struct {
	db      *sql.DB
	cluster string
	pepper  []byte
	rate    RateGate
	proofs  Proofs
}

func New(db *sql.DB, cluster string, pepper []byte, rate RateGate, proofs Proofs) (*Store, error) {
	if db == nil || cluster == "" || len(pepper) < 32 {
		return nil, ErrUnavailable
	}
	return &Store{db: db, cluster: cluster, pepper: append([]byte(nil), pepper...), rate: rate, proofs: proofs}, nil
}
