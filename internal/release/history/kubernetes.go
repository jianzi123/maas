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
	ScopeID    string
}

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

// ResolverEvaluator reuses the approved reference resolver, never a model call.
// An installation must supply the actual registry-backed implementation.
type ResolverEvaluator struct{ Resolver release.Resolver }

func (e ResolverEvaluator) Evaluate(ctx context.Context, spec api.Spec, live LiveState) (Evaluation, error) {
	if e.Resolver == nil {
		return Evaluation{}, ErrUnavailable
	}
	m := &api.ModelRelease{ObjectMeta: metav1.ObjectMeta{Namespace: live.Namespace, Name: live.Name, UID: types.UID(live.UID), ResourceVersion: live.Version}, Spec: spec}
	_, err := e.Resolver.Resolve(ctx, m)
	if err == nil {
		return Evaluation{"eligible", []string{}}, nil
	}
	var denied ReferenceFailure
	if errors.As(err, &denied) {
		v := Evaluation{"blocked", []string{denied.Reason}}
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
	if r.History == nil || r.Client == nil || r.Reader == nil || resourceVersion == "" {
		return "", ErrUnavailable
	}
	current := new(api.ModelRelease)
	if e := r.Reader.Get(ctx, types.NamespacedName{Namespace: ns, Name: name}, current); e != nil {
		return "", ErrUnavailable
	}
	uid := string(current.UID)
	if (expectedUID != "" && expectedUID != uid) || current.ResourceVersion != resourceVersion || current.DeletionTimestamp != nil {
		return "", ErrConflict
	}
	spec, e := r.History.LoadSpec(ctx, ns, name, uid, revision)
	if e != nil {
		return "", e
	}
	if api.Validate(spec, &current.Spec) != nil {
		return "", ErrConflict
	}
	live := LiveState{UID: uid, Version: resourceVersion, SourceType: current.Spec.Source.Type, Namespace: ns, Name: name, State: "present"}
	if r.History.Evaluator == nil {
		return "", ErrUnavailable
	}
	evaluation, e := r.History.Evaluator.Evaluate(ctx, spec, live)
	if e != nil || !validEvaluation(evaluation, live) || evaluation.State != "eligible" {
		return "", ErrUnavailable
	}
	fresh := new(api.ModelRelease)
	if r.Reader.Get(ctx, client.ObjectKeyFromObject(current), fresh) != nil {
		return "", ErrUnavailable
	}
	if fresh.UID != current.UID || fresh.ResourceVersion != resourceVersion || fresh.DeletionTimestamp != nil {
		return "", ErrConflict
	}
	fresh.Spec = spec
	if e = r.Client.Update(ctx, fresh); e != nil {
		if apierrors.IsConflict(e) || apierrors.IsInvalid(e) {
			return "", ErrConflict
		}
		if apierrors.IsForbidden(e) {
			return "", ErrForbidden
		}
		return "", ErrWriteOutcomeUnknown
	}
	return fresh.ResourceVersion, nil
}
