package release

import (
	"context"
	"k8s.io/apimachinery/pkg/apis/meta/v1/unstructured"
	"reflect"
	"sigs.k8s.io/controller-runtime/pkg/client"
)

type BundleSnapshot struct {
	Token           string
	Namespace, Name string
	// Includes candidate, active and draining publications across ALL models.
	Entries []RegistryEntry
	// Exact names with durable installation ownership, not a maas-* prefix test.
	OwnedNames map[string]bool
}
type BundleCatalog interface {
	Snapshot(context.Context) (BundleSnapshot, error)
	CheckCurrent(context.Context, string) error
}

// BundleWriter runs under the dedicated shared-writer role. It never creates or
// deletes the shared McpBridge and never force-updates a resourceVersion conflict.
// A stale writer can still race across K8s/MySQL; durable activation must verify
// the matching compiled bundle receipt/freshness before allowing any traffic.
type BundleWriter struct {
	Client  client.Client
	Reader  client.Reader
	Catalog BundleCatalog
}

func (w BundleWriter) Sync(ctx context.Context) error {
	if w.Catalog == nil || w.Client == nil || w.Reader == nil {
		return ErrDependencyMissing
	}
	s, err := w.Catalog.Snapshot(ctx)
	if err != nil {
		return err
	}
	if s.Token == "" || s.Name == "" || s.Namespace == "" {
		return ErrDependencyMissing
	}
	bridge := &unstructured.Unstructured{}
	bridge.SetAPIVersion("networking.higress.io/v1")
	bridge.SetKind("McpBridge")
	if err = w.Reader.Get(ctx, client.ObjectKey{Namespace: s.Namespace, Name: s.Name}, bridge); err != nil {
		return err
	}
	current, _, err := unstructured.NestedSlice(bridge.Object, "spec", "registries")
	if err != nil {
		return err
	}
	merged, err := MergeRegistry(current, s.OwnedNames, s.Entries)
	if err != nil {
		return err
	}
	if err = w.Catalog.CheckCurrent(ctx, s.Token); err != nil {
		return err
	}
	if reflect.DeepEqual(current, merged) {
		return nil
	}
	if err = unstructured.SetNestedSlice(bridge.Object, merged, "spec", "registries"); err != nil {
		return err
	}
	return w.Client.Update(ctx, bridge)
}
