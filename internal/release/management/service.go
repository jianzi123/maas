package management

import (
	"context"
	"crypto/hmac"
	"crypto/sha256"
	"encoding/base64"
	"encoding/json"
	"errors"
	"net/url"
	"regexp"
	"sort"
	"strconv"
	"strings"
	"time"

	api "github.com/jianzi123/maas/api/v1alpha1"
	"github.com/jianzi123/maas/internal/release"
	"github.com/jianzi123/maas/internal/release/history"
	apierrors "k8s.io/apimachinery/pkg/api/errors"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/types"
	"sigs.k8s.io/controller-runtime/pkg/client"
)

type Service struct {
	Client     client.Client
	Reader     client.Reader
	Operations *Operations
	History    *history.Reader
	Resolver   release.Resolver
	Access     history.NamespaceAccess
	CursorKey  []byte
}

var dns = regexp.MustCompile(`^[a-z0-9]([-a-z0-9]*[a-z0-9])?$`)

func validName(s string) bool { return len(s) <= 63 && dns.MatchString(s) }
func (s *Service) scope(ctx context.Context, ns, name, uid string) (string, error) {
	if s == nil || s.Operations == nil || s.Operations.DB == nil || s.Client == nil || s.Reader == nil {
		return "", history.ErrUnavailable
	}
	if !validName(ns) || !validName(name) {
		return "", history.ErrInvalid
	}
	scope, e := s.Access.Scope(ctx, ns, name, uid)
	if e != nil {
		return "", e
	}
	if len(scope) > 128 {
		return "", history.ErrUnavailable
	}
	return scope, nil
}
func (s *Service) current(ctx context.Context, ns, name string) (*api.ModelRelease, error) {
	if _, e := s.scope(ctx, ns, name, ""); e != nil {
		return nil, e
	}
	m := new(api.ModelRelease)
	e := s.Reader.Get(ctx, types.NamespacedName{Namespace: ns, Name: name}, m)
	if apierrors.IsNotFound(e) {
		return nil, history.ErrNotFound
	}
	if apierrors.IsForbidden(e) {
		return nil, history.ErrForbidden
	}
	if e != nil {
		return nil, history.ErrUnavailable
	}
	if !validID(string(m.UID)) || m.ResourceVersion == "" {
		return nil, history.ErrUnavailable
	}
	return m, nil
}
func (s *Service) Get(ctx context.Context, ns, name string) (map[string]any, string, error) {
	m, e := s.current(ctx, ns, name)
	if e != nil {
		return nil, "", e
	}
	return project(m), m.ResourceVersion, nil
}
func project(m *api.ModelRelease) map[string]any {
	metadata := map[string]any{"namespace": m.Namespace, "name": m.Name, "uid": string(m.UID), "resourceVersion": m.ResourceVersion, "generation": m.Generation, "finalizers": append([]string{}, m.Finalizers...)}
	if m.DeletionTimestamp != nil {
		metadata["deletionTimestamp"] = m.DeletionTimestamp.UTC().Format(time.RFC3339Nano)
	}
	out := map[string]any{"apiVersion": api.GroupVersion.String(), "kind": "ModelRelease", "metadata": metadata, "spec": m.Spec}
	// Do not fabricate observedGeneration=1 for a not-yet-observed CR. Status is
	// optional in the existing schema. Never echo arbitrary status messages.
	if m.Status.ObservedGeneration > 0 {
		status := m.DeepCopy().Status
		status.Operation = nil
		if status.Conditions == nil {
			status.Conditions = []metav1.Condition{}
		}
		if status.Resources == nil {
			status.Resources = []api.ResourceRef{}
		}
		for i := range status.Conditions {
			status.Conditions[i].Message = "Release reconciliation condition."
		}
		out["status"] = status
	}
	return out
}

type listCursor struct {
	Namespace, Scope, Continue, Approval string
	Size, Index                          int
}

func (s *Service) List(ctx context.Context, q url.Values) (map[string]any, error) {
	if s == nil || s.Reader == nil || s.Operations == nil || len(s.CursorKey) < 32 || s.Access.ScopeID == "" {
		return nil, history.ErrUnavailable
	}
	for k := range q {
		if k != "namespace" && k != "page_size" && k != "cursor" {
			return nil, history.ErrInvalid
		}
	}
	ns := q.Get("namespace")
	if _, present := q["namespace"]; present && ns == "" {
		return nil, history.ErrInvalid
	}
	if ns != "" && !validName(ns) {
		return nil, history.ErrInvalid
	}
	size := 20
	var e error
	if v := q.Get("page_size"); v != "" {
		size, e = strconv.Atoi(v)
		if e != nil || size < 1 || size > 100 {
			return nil, history.ErrInvalid
		}
	}
	if ns != "" && !s.Access.Namespaces[ns] {
		return nil, history.ErrForbidden
	}
	names := []string{}
	for n, ok := range s.Access.Namespaces {
		if ok && (ns == "" || ns == n) {
			if !validName(n) {
				return nil, history.ErrUnavailable
			}
			names = append(names, n)
		}
	}
	sort.Strings(names)
	approval := release.Hash(struct {
		Cluster    string
		Namespaces []string
	}{s.Operations.Cluster, names})
	c := listCursor{Namespace: ns, Scope: s.Access.ScopeID, Size: size, Approval: approval}
	if raw := q.Get("cursor"); raw != "" {
		p := strings.Split(raw, ".")
		if len(p) != 2 || len(raw) > 2048 {
			return nil, history.ErrInvalid
		}
		b, err := base64.RawURLEncoding.Strict().DecodeString(p[0])
		sig, x := base64.RawURLEncoding.Strict().DecodeString(p[1])
		mac := hmac.New(sha256.New, s.CursorKey)
		mac.Write(b)
		if err != nil || x != nil || !hmac.Equal(mac.Sum(nil), sig) || json.Unmarshal(b, &c) != nil || c.Namespace != ns || c.Scope != s.Access.ScopeID || c.Size != size || c.Approval != approval || c.Index < 0 || c.Index >= len(names) {
			return nil, history.ErrInvalid
		}
	}
	// Query only explicitly approved namespaces, never a broad cluster LIST.
	data := []any{}
	for c.Index < len(names) && len(data) < size {
		list := new(api.ModelReleaseList)
		e = s.Reader.List(ctx, list, &client.ListOptions{Namespace: names[c.Index], Limit: int64(size - len(data)), Continue: c.Continue})
		if apierrors.IsResourceExpired(e) {
			return nil, history.ErrConflict
		}
		if e != nil {
			return nil, history.ErrUnavailable
		}
		if len(list.Items) > size-len(data) {
			return nil, history.ErrUnavailable
		}
		for i := range list.Items {
			m := &list.Items[i]
			if m.Namespace != names[c.Index] {
				return nil, history.ErrUnavailable
			}
			if _, e = s.scope(ctx, m.Namespace, m.Name, string(m.UID)); e != nil {
				return nil, e
			}
			data = append(data, project(m))
		}
		c.Continue = list.Continue
		if c.Continue != "" {
			break
		}
		c.Index++
	}
	var next any
	if c.Index < len(names) {
		b, _ := json.Marshal(c)
		mac := hmac.New(sha256.New, s.CursorKey)
		mac.Write(b)
		next = base64.RawURLEncoding.EncodeToString(b) + "." + base64.RawURLEncoding.EncodeToString(mac.Sum(nil))
	}
	return map[string]any{"data": data, "next_cursor": next, "generated_at": time.Now().UTC().Format(time.RFC3339Nano)}, nil
}

// Submit dispatches at most one Kubernetes mutation in the original request.
// Operation lookup is always a read, including after a crash or unknown ACK.
func (s *Service) Submit(ctx context.Context, method, ns, name, rv, expectedUID, revision string, input *api.ModelRelease) (map[string]any, error) {
	scope, e := s.scope(ctx, ns, name, expectedUID)
	if e != nil {
		return nil, e
	}
	action := "Create"
	var current *api.ModelRelease
	var desired api.Spec
	if method != "POST" || revision != "" {
		current, e = s.current(ctx, ns, name)
		if e != nil {
			return nil, e
		}
		if rv == "" || rv != current.ResourceVersion || current.DeletionTimestamp != nil || (expectedUID != "" && expectedUID != string(current.UID)) {
			return nil, history.ErrConflict
		}
		desired = current.Spec
		action = "Update"
	}
	if revision != "" {
		if s.History == nil {
			return nil, history.ErrUnavailable
		}
		desired, e = s.History.LoadSpec(ctx, ns, name, string(current.UID), revision)
		if e != nil {
			return nil, e
		}
		action = "Rollback"
	} else if method == "DELETE" {
		action = "Delete"
	} else {
		if input == nil || input.Namespace != ns || input.Name != name {
			return nil, history.ErrInvalid
		}
		desired = input.Spec
	}
	var old *api.Spec
	if current != nil {
		old = &current.Spec
	}
	if api.Validate(desired, old) != nil {
		return nil, history.ErrInvalid
	}
	if action == "Update" && desired.Lifecycle.DesiredState != current.Spec.Lifecycle.DesiredState {
		if desired.Lifecycle.DesiredState == "Paused" {
			action = "Pause"
		} else {
			action = "Resume"
		}
	}
	// Pausing and deletion remain possible during registry/credential outages.
	// Published intents require an approved metadata resolver, not a model call.
	if action != "Delete" && desired.Lifecycle.DesiredState != "Paused" {
		if s.Resolver == nil {
			return nil, history.ErrUnavailable
		}
		probe := &api.ModelRelease{ObjectMeta: metav1.ObjectMeta{Namespace: ns, Name: name}, Spec: desired}
		if current != nil {
			probe.UID = current.UID
			probe.ResourceVersion = current.ResourceVersion
		}
		if _, e = s.Resolver.Resolve(ctx, probe); e != nil {
			return nil, history.ErrUnavailable
		}
	}
	uid := ""
	if current != nil {
		uid = string(current.UID)
	}
	op, dispatch, e := s.Operations.begin(ctx, action, scope, ns, name, uid, rv, desired)
	if e != nil {
		return nil, e
	}
	if !dispatch {
		return map[string]any{"operation": object(op), "resource": nil}, nil
	}
	var result *api.ModelRelease
	if action == "Rollback" {
		result, e = (history.RollbackService{History: s.History, Client: s.Client, Reader: s.Reader}).RollbackObject(ctx, ns, name, uid, revision, rv)
	} else if action == "Delete" {
		// Keep the acknowledged original UID/generation; deletion has explicit UID/RV
		// preconditions, and completion is reported after finalizer cleanup.
		result = current.DeepCopy()
		e = s.Client.Delete(ctx, result, &client.DeleteOptions{Preconditions: &metav1.Preconditions{UID: &current.UID, ResourceVersion: &rv}})
	} else {
		if current == nil {
			result = &api.ModelRelease{ObjectMeta: metav1.ObjectMeta{Namespace: ns, Name: name, Finalizers: []string{release.Finalizer}}, Spec: desired}
		} else {
			result = current.DeepCopy()
			result.Spec = desired
		}
		if current == nil {
			e = s.Client.Create(ctx, result)
		} else {
			e = s.Client.Update(ctx, result)
		}
	}
	writeErr := mapWriteError(e)
	finishCtx, cancel := context.WithTimeout(context.WithoutCancel(ctx), 5*time.Second)
	defer cancel()
	if e = s.Operations.finishWrite(finishCtx, op.ID, result, writeErr); e != nil {
		op.State = "Unknown"
		reason := "WriteOutcomeUnknown"
		op.Reason = &reason
		return map[string]any{"operation": object(op), "resource": nil}, nil
	}
	if writeErr != nil && !errors.Is(writeErr, history.ErrWriteOutcomeUnknown) {
		return nil, writeErr
	}
	stored, e := s.Operations.load(finishCtx, op.ID)
	if e != nil {
		op.State = "Unknown"
		return map[string]any{"operation": object(op), "resource": nil}, nil
	}
	var resource any
	if writeErr == nil && result != nil && action != "Delete" && action != "Rollback" {
		resource = project(result)
	}
	return map[string]any{"operation": object(stored.Operation), "resource": resource}, nil
}
func mapWriteError(e error) error {
	if e == nil {
		return nil
	}
	if apierrors.IsConflict(e) || apierrors.IsAlreadyExists(e) || errors.Is(e, history.ErrConflict) {
		return history.ErrConflict
	}
	if apierrors.IsForbidden(e) || errors.Is(e, history.ErrForbidden) {
		return history.ErrForbidden
	}
	if apierrors.IsInvalid(e) || errors.Is(e, history.ErrInvalid) {
		return history.ErrInvalid
	}
	return history.ErrWriteOutcomeUnknown
}
