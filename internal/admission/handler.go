// Package admission validates both raw CR spec and approved dependency metadata.
package admission

import (
	"context"
	"encoding/json"
	"reflect"

	api "github.com/jianzi123/maas/api/v1alpha1"
	"github.com/jianzi123/maas/internal/release"
	admissionv1 "k8s.io/api/admission/v1"
	"sigs.k8s.io/controller-runtime/pkg/webhook/admission"
)

type Handler struct{ Resolver release.Resolver }

func (h Handler) Handle(ctx context.Context, req admission.Request) admission.Response {
	// Deletion must remain possible when dependencies disappeared. Finalizer gates
	// actual cleanup, without relying on GC ownerReferences.
	if req.Operation == admissionv1.Delete {
		return admission.Allowed("cleanup gated by finalizer")
	}
	if req.Operation != admissionv1.Create && req.Operation != admissionv1.Update {
		return admission.Denied("unsupported operation")
	}
	var raw struct {
		Spec json.RawMessage `json:"spec"`
	}
	if json.Unmarshal(req.Object.Raw, &raw) != nil || api.ValidateJSON(raw.Spec) != nil {
		return admission.Denied("InvalidSpec")
	}
	m := new(api.ModelRelease)
	if json.Unmarshal(req.Object.Raw, m) != nil {
		return admission.Denied("InvalidSpec")
	}
	if req.Operation == admissionv1.Update {
		old := new(api.ModelRelease)
		if json.Unmarshal(req.OldObject.Raw, old) != nil {
			return admission.Denied("InvalidSpec")
		}
		if api.Validate(m.Spec, &old.Spec) != nil {
			return admission.Denied("ImmutableField")
		}
		// Finalizer/status-only updates remain possible during dependency failures.
		if reflect.DeepEqual(old.Spec, m.Spec) {
			return admission.Allowed("spec unchanged")
		}
	}
	if m.Spec.Lifecycle.DesiredState == "Paused" {
		return admission.Allowed("admission closure requested")
	}
	if h.Resolver == nil {
		return admission.Denied("DependencyMissing")
	}
	if _, err := h.Resolver.Resolve(ctx, m); err != nil {
		return admission.Denied("ProfileUnapproved")
	}
	return admission.Allowed("validated against approved dependencies")
}
