// Package release is the control-plane lifecycle, never a budget or inference path.
package release

import (
	"context"
	"errors"
	api "github.com/jianzi123/maas/api/v1alpha1"
	"k8s.io/apimachinery/pkg/apis/meta/v1/unstructured"
	"time"
)

var ErrDependencyMissing = errors.New("DependencyMissing")
var ErrConflict = errors.New("RevisionConflict")
var ErrOwnership = errors.New("OwnershipConflict")

// Resolution comes from an installation-approved registry, never arbitrary CR URLs.
// Versions includes ALL profile, price, endpoint, capability, plugin and Secret
// UID/resourceVersion metadata. It MUST NOT include Secret data or its hash.
type Resolution struct {
	Versions                                   map[string]string
	GatewayNamespace, IngressClass, HostSuffix string
	EndpointDNS                                string
	EndpointPort                               int64
	CredentialHandle                           string
	PluginDigest                               string
}
type Resolver interface {
	Resolve(context.Context, *api.ModelRelease) (Resolution, error)
}

type Binding struct {
	PublicationID string
	Revision      string
	Generation    int64
	Epoch         int64
}
type State struct {
	CRUID                      string
	Generation                 int64
	Fence                      int64
	Revision                   string
	Candidate                  *Binding
	Active                     *Binding
	AdmissionClosed, Tombstone bool
	// Backend checks authenticated per-instance receipts, freshness, complete
	// serving replica set, budget/slot kernel and immutable evidence bindings.
	RuntimeReady, GatewayApplied, AccountingReady, ValidationPassed bool
	EvidenceRefs                                                    []string
	Draining                                                        []Binding
}
type HistoryCapture struct {
	Spec            api.Spec
	Resolution      Resolution
	ResourceVersion string
}
type Desired struct {
	History                       *HistoryCapture `json:"-"`
	CRUID, Namespace, Name, Alias string
	Gateway                       api.Ref
	Generation                    int64
	Revision                      string
	Deleting, Paused              bool
}

// Command matches MAAS-2 v0.4 ControlCommand. No Key/usage/budget mutation fields.
type Command struct {
	ID             string   `json:"command_id"`
	Action         string   `json:"action"`
	CRUID          string   `json:"cr_uid"`
	Generation     int64    `json:"observed_generation"`
	Fence          int64    `json:"reconcile_epoch"`
	ExpectedActive *string  `json:"expected_active_publication_id"`
	Target         *string  `json:"target_publication_id"`
	Revision       string   `json:"revision"`
	EvidenceRefs   []string `json:"evidence_refs"`
}

// Control is an INTERNAL Go port; Observe/Read are not invented public endpoints.
// Adapter must use MySQL fences/CAS, unique validation intents and irreversible
// tombstones. Observe allocates once for UID+generation+resolved revision, including
// resume/rollback with fresh publication and monotonic epoch. Unknown commits are
// recovered by Read, never by issuing a new ID. Status is never authorization.
type Control interface {
	Observe(context.Context, Desired) (State, error)
	Read(context.Context, string) (State, error)
	Apply(context.Context, Command) error
	// Drain verifies no in_progress transport and no unsafe HELD/QUARANTINED slot.
	// Unknown financial holds are deliberately NOT a drain dependency.
	Drain(context.Context, string, string) (bool, error)
}
type Entry struct {
	Owner, Publication string
	Ref                api.ResourceRef
	Digest             string
	Retiring           bool
}

// Inventory writes intent BEFORE object creation, binds actual UID exactly once,
// and CASes retiring with reference count zero + transport/slot safety. It never
// writes budgets or finalizes requests. The mysqlstore adapter requires the
// existing core's transaction proofs and is not wired by the Operator binary.
type Inventory interface {
	Intent(context.Context, Entry) error
	Bind(context.Context, Entry) error
	List(context.Context, string, string) ([]Entry, error)
	Retire(context.Context, Entry) error
	Removed(context.Context, Entry) error
}
type ObjectPlan struct {
	Object *unstructured.Unstructured
	Digest string
}
type Plan struct {
	Objects    []ObjectPlan
	Registry   RegistryEntry
	Deployable bool
}
type RegistryEntry struct {
	Name   string `json:"name"`
	Domain string `json:"domain"`
	Port   int64  `json:"port"`
	Type   string `json:"type"`
}

// Bundle implementations are a SINGLE shared writer, merging all durable
// candidate/active/draining references, preserving unmanaged entries with RV CAS.
type Bundle interface {
	Ensure(context.Context, string, Binding, RegistryEntry) error
	Remove(context.Context, string, string) error
}

// PluginCompiler must implement the approved H1-H4 gateway extensions. There is
// no stock credential-handle field and no placeholder production implementation.
type PluginCompiler interface {
	Compile(context.Context, *api.ModelRelease, Resolution, Binding, string) (*unstructured.Unstructured, error)
}
type Dependencies struct {
	Resolver  Resolver
	Control   Control
	Inventory Inventory
	Bundle    Bundle
	Plugin    PluginCompiler
}

func (d Dependencies) Check() error {
	if d.Resolver == nil || d.Control == nil || d.Inventory == nil || d.Bundle == nil || d.Plugin == nil {
		return ErrDependencyMissing
	}
	return nil
}

const RetryAfter = 5 * time.Second
