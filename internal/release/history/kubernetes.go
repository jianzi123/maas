package history

import (
	"context"
	"errors"
	api "github.com/jianzi123/maas/api/v1alpha1"
	"github.com/jianzi123/maas/internal/release"
	apierrors "k8s.io/apimachinery/pkg/api/errors"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/types"
	"sigs.k8s.io/controller-runtime/pkg/client"
)

type NamespaceAccess struct {
	Namespaces map[string]bool
	Domains    map[string]bool
	ScopeID    string
}

func (a NamespaceAccess) Domain(_ context.Context, d string) bool { return a.Domains[d] }
func (a NamespaceAccess) Scope(_ context.Context, ns, name, uid string) (string, error) {
	if a.ScopeID == "" || !a.Namespaces[ns] {
		return "", ErrForbidden
	}
	return a.ScopeID, nil
}

// KubeLive must use an uncached, installation-approved API reader. It never
// provisions a cluster, expands RBAC, or interprets CR Ready as Callable.
type KubeLive struct{ Reader client.Reader }

func (k KubeLive) Current(ctx context.Context, ns, name string) (LiveState, error) {
	if k.Reader == nil {
		return LiveState{}, ErrUnavailable
	}
	m := new(api.ModelRelease)
	e := k.Reader.Get(ctx, types.NamespacedName{Namespace: ns, Name: name}, m)
	if apierrors.IsNotFound(e) {
		return LiveState{State: "deleted", Namespace: ns, Name: name}, nil
	}
	if e != nil {
		return LiveState{}, ErrUnavailable
	}
	state := "present"
	if m.DeletionTimestamp != nil {
		state = "deleting"
	}
	return LiveState{UID: string(m.UID), Version: m.ResourceVersion, SourceType: m.Spec.Source.Type, Namespace: ns, Name: name, State: state}, nil
}

type ReferenceFailure struct{ Reason string }

func (e ReferenceFailure) Error() string { return e.Reason }

// Typed, whitelisted causes preserve the existing 403/409/503 contract. Unknown
// resolver failures remain unavailable; arbitrary error strings are not public.
func (e ReferenceFailure) Unwrap() error {
	switch e.Reason {
	case "reference_unapproved", "profile_unapproved", "reference_expired":
		return ErrForbidden
	case "policy_changed":
		return release.ErrPolicyChanged
	default:
		return ErrUnavailable
	}
}

// ResolverEvaluator reuses the approved reference resolver, never a model call.
// An installation must supply the actual registry-backed implementation.
type ResolverEvaluator struct {
	Resolver release.Resolver
	Loader   *Reader
}

func (e ResolverEvaluator) Evaluate(ctx context.Context, uid, revision string, live LiveState) (Evaluation, error) {
	if e.Resolver == nil || e.Loader == nil {
		return Evaluation{}, ErrUnavailable
	}
	spec, loadErr := e.Loader.LoadSpec(ctx, live.Namespace, live.Name, uid, revision)
	if loadErr != nil {
		return Evaluation{}, loadErr
	}
	m := &api.ModelRelease{ObjectMeta: metav1.ObjectMeta{Namespace: live.Namespace, Name: live.Name, UID: types.UID(live.UID), ResourceVersion: live.Version}, Spec: spec}
	_, err := e.Resolver.Resolve(ctx, m)
	if err == nil {
		return Evaluation{"eligible", []string{}}, nil
	}
	var denied ReferenceFailure
	if errors.As(err, &denied) {
		reason := denied.Reason
		if reason == "profile_unapproved" {
			reason = "reference_unapproved"
		}
		v := Evaluation{"blocked", []string{reason}}
		if validEvaluation(v, live) {
			return v, nil
		}
	}
	return Evaluation{}, ErrUnavailable
}

var ErrWriteOutcomeUnknown = errors.New("release write outcome unknown; read original operation, never replay")

type RollbackService struct {
	History *Reader
	Client  client.Client
	Reader  client.Reader
}

// Rollback performs ONE resourceVersion/UID-guarded update. The caller owns the
// existing durable operation workflow; this method never retries or infers the
// result of a lost K8s ACK from a later GET of the current CR.
func (r RollbackService) Rollback(ctx context.Context, ns, name, expectedUID, revision, resourceVersion string) (string, error) {
	m, e := r.RollbackObject(ctx, ns, name, expectedUID, revision, resourceVersion)
	if e != nil {
		return "", e
	}
	return m.ResourceVersion, nil
}

// RollbackObject returns only the API-server's original mutation ACK. It never
// estimates the resulting generation or issues a second write for bookkeeping.
func (r RollbackService) RollbackObject(ctx context.Context, ns, name, expectedUID, revision, resourceVersion string) (*api.ModelRelease, error) {
	fresh, e := r.Prepare(ctx, ns, name, expectedUID, revision, resourceVersion)
	if e != nil {
		return nil, e
	}
	if e = r.Client.Update(ctx, fresh); e != nil {
		if apierrors.IsConflict(e) || apierrors.IsInvalid(e) {
			return nil, ErrConflict
		}
		if apierrors.IsForbidden(e) {
			return nil, ErrForbidden
		}
		return nil, ErrWriteOutcomeUnknown
	}
	return fresh, nil
}

// Prepare performs only reads. Management must finish these checks before
// creating an operation. The returned UID/resourceVersion still guard the one
// subsequent API-server update; no later GET is used to infer a lost write ACK.
func (r RollbackService) Prepare(ctx context.Context, ns, name, expectedUID, revision, resourceVersion string) (*api.ModelRelease, error) {
	if r.History == nil || r.Client == nil || r.Reader == nil || resourceVersion == "" {
		return nil, ErrUnavailable
	}
	current := new(api.ModelRelease)
	if e := r.Reader.Get(ctx, types.NamespacedName{Namespace: ns, Name: name}, current); e != nil {
		if apierrors.IsNotFound(e) {
			return nil, ErrNotFound
		}
		return nil, ErrUnavailable
	}
	uid := string(current.UID)
	if (expectedUID != "" && expectedUID != uid) || current.ResourceVersion != resourceVersion || current.DeletionTimestamp != nil {
		return nil, ErrConflict
	}
	spec, e := r.History.LoadSpec(ctx, ns, name, uid, revision)
	if e != nil {
		return nil, e
	}
	if api.Validate(spec, &current.Spec) != nil {
		return nil, ErrConflict
	}
	live := LiveState{UID: uid, Version: resourceVersion, SourceType: current.Spec.Source.Type, Namespace: ns, Name: name, State: "present"}
	if r.History.Evaluator == nil {
		return nil, ErrUnavailable
	}
	evaluation, e := r.History.Evaluator.Evaluate(ctx, uid, revision, live)
	if e != nil {
		return nil, e
	}
	if !validEvaluation(evaluation, live) || evaluation.State == "unknown" {
		return nil, ErrUnavailable
	}
	if evaluation.State == "blocked" {
		for _, reason := range evaluation.Reasons {
			if reason == "state_unavailable" || reason == "pricing_unavailable" {
				return nil, ErrUnavailable
			}
		}
		return nil, ErrConflict
	}
	fresh := new(api.ModelRelease)
	if r.Reader.Get(ctx, client.ObjectKeyFromObject(current), fresh) != nil {
		return nil, ErrUnavailable
	}
	if fresh.UID != current.UID || fresh.ResourceVersion != resourceVersion || fresh.DeletionTimestamp != nil {
		return nil, ErrConflict
	}
	fresh.Spec = spec
	return fresh, nil
}
