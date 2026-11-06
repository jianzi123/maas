package release

import (
	"context"
	api "github.com/jianzi123/maas/api/v1alpha1"
	apierrors "k8s.io/apimachinery/pkg/api/errors"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/apis/meta/v1/unstructured"
	"k8s.io/apimachinery/pkg/types"
	"sigs.k8s.io/controller-runtime/pkg/client"
)

type Resources struct {
	Client    client.Client
	Reader    client.Reader
	Inventory Inventory
}

func ref(o *unstructured.Unstructured, pub string) api.ResourceRef {
	return api.ResourceRef{APIVersion: o.GetAPIVersion(), Kind: o.GetKind(), Namespace: o.GetNamespace(), Name: o.GetName(), UID: string(o.GetUID()), Ownership: "exclusive", PublicationID: &pub}
}
func (r Resources) Ensure(ctx context.Context, uid, pub string, p ObjectPlan) error {
	if r.Client == nil || r.Reader == nil || r.Inventory == nil {
		return ErrDependencyMissing
	}
	e := Entry{Owner: uid, Publication: pub, Ref: ref(p.Object, pub), Digest: p.Digest}
	if len(p.Object.GetOwnerReferences()) != 0 {
		return ErrOwnership
	}
	if err := r.Inventory.Intent(ctx, e); err != nil {
		return err
	}
	got := &unstructured.Unstructured{}
	got.SetGroupVersionKind(p.Object.GroupVersionKind())
	err := r.Reader.Get(ctx, client.ObjectKeyFromObject(p.Object), got)
	if apierrors.IsNotFound(err) {
		got = p.Object.DeepCopy()
		if err = r.Client.Create(ctx, got); err != nil {
			return err
		}
	} else if err != nil {
		return err
	}
	if got.GetAnnotations()[OwnerAnnotation] != uid || got.GetAnnotations()[PublicationAnnotation] != pub || got.GetAnnotations()[DigestAnnotation] != p.Digest || ObjectDigest(got) != p.Digest || len(got.GetOwnerReferences()) != 0 {
		return ErrOwnership
	}
	if got.GetUID() == "" {
		return ErrOwnership
	}
	e.Ref = ref(got, pub)
	// Bind rejects a different previously recorded UID; labels alone never adopt.
	return r.Inventory.Bind(ctx, e)
}
func (r Resources) Delete(ctx context.Context, e Entry) error {
	if r.Client == nil || r.Reader == nil || r.Inventory == nil {
		return ErrDependencyMissing
	}
	if e.Ref.Ownership != "exclusive" {
		return ErrOwnership
	}
	// User data and installation/shared resources are never deletion targets,
	// even if inventory was populated incorrectly by an adapter.
	allowed := map[string]bool{"networking.k8s.io/v1/Ingress": true, "extensions.higress.io/v1alpha1/WasmPlugin": true, "leaderworkerset.x-k8s.io/v1/LeaderWorkerSet": true, "v1/Service": true, "v1/ConfigMap": true, "networking.k8s.io/v1/NetworkPolicy": true}
	if !allowed[e.Ref.APIVersion+"/"+e.Ref.Kind] {
		return ErrOwnership
	}
	// Inventory.Retire must CAS reference count zero and safe transport/slot
	// evidence before any K8s delete, including on retries after a crash.
	got := &unstructured.Unstructured{}
	got.SetAPIVersion(e.Ref.APIVersion)
	got.SetKind(e.Ref.Kind)
	err := r.Reader.Get(ctx, client.ObjectKey{Namespace: e.Ref.Namespace, Name: e.Ref.Name}, got)
	if apierrors.IsNotFound(err) {
		if err = r.Inventory.Retire(ctx, e); err != nil {
			return err
		}
		return r.Inventory.Removed(ctx, e)
	}
	if err != nil {
		return err
	}
	if got.GetAnnotations()[OwnerAnnotation] != e.Owner || got.GetAnnotations()[PublicationAnnotation] != e.Publication {
		return ErrOwnership
	}
	if e.Ref.UID == "" {
		// Recovery of a durable intent whose create succeeded but UID bind ACK was
		// lost. Bind rejects any different UID already recorded by another worker.
		if got.GetAnnotations()[DigestAnnotation] != e.Digest || ObjectDigest(got) != e.Digest || len(got.GetOwnerReferences()) != 0 || got.GetUID() == "" {
			return ErrOwnership
		}
		e.Ref = ref(got, e.Publication)
		if err = r.Inventory.Bind(ctx, e); err != nil {
			return err
		}
	} else if string(got.GetUID()) != e.Ref.UID {
		return ErrOwnership
	}
	if err = r.Inventory.Retire(ctx, e); err != nil {
		return err
	}
	uid := types.UID(e.Ref.UID)
	rv := got.GetResourceVersion()
	if err = r.Client.Delete(ctx, got, &client.DeleteOptions{Preconditions: &metav1.Preconditions{UID: &uid, ResourceVersion: &rv}}); err != nil && !apierrors.IsNotFound(err) {
		return err
	}
	// Finalizers or asynchronous deletion may still retain the object. Only a
	// later authoritative NotFound completes inventory cleanup.
	check := &unstructured.Unstructured{}
	check.SetGroupVersionKind(got.GroupVersionKind())
	if err = r.Reader.Get(ctx, client.ObjectKeyFromObject(got), check); !apierrors.IsNotFound(err) {
		if err != nil {
			return err
		}
		return ErrConflict
	}
	return r.Inventory.Removed(ctx, e)
}
