package release

import (
	"context"
	"errors"
	apierrors "k8s.io/apimachinery/pkg/api/errors"
	"k8s.io/apimachinery/pkg/apis/meta/v1/unstructured"
	"k8s.io/apimachinery/pkg/runtime"
	"k8s.io/apimachinery/pkg/runtime/schema"
	"sigs.k8s.io/controller-runtime/pkg/client"
	"sigs.k8s.io/controller-runtime/pkg/client/fake"
	"sigs.k8s.io/controller-runtime/pkg/client/interceptor"
	"testing"
)

type catalog struct {
	snapshot BundleSnapshot
	stale    bool
}

func (c *catalog) Snapshot(context.Context) (BundleSnapshot, error) { return c.snapshot, nil }
func (c *catalog) CheckCurrent(context.Context, string) error {
	if c.stale {
		return ErrConflict
	}
	return nil
}
func TestBundleResourceVersionConflictThenRetryPreservesManualFields(t *testing.T) {
	bridge := &unstructured.Unstructured{Object: map[string]any{"apiVersion": "networking.higress.io/v1", "kind": "McpBridge", "metadata": map[string]any{"name": "default", "namespace": "higress-test"}, "spec": map[string]any{"otherSetting": "preserve", "registries": []any{map[string]any{"name": "manual", "custom": "keep"}}}}}
	conflict := true
	c := fake.NewClientBuilder().WithScheme(runtime.NewScheme()).WithObjects(bridge).WithInterceptorFuncs(interceptor.Funcs{Update: func(ctx context.Context, c client.WithWatch, o client.Object, opts ...client.UpdateOption) error {
		if conflict {
			conflict = false
			return apierrors.NewConflict(schema.GroupResource{Group: "networking.higress.io", Resource: "mcpbridges"}, o.GetName(), errors.New("other writer"))
		}
		return c.Update(ctx, o, opts...)
	}}).Build()
	cat := &catalog{snapshot: BundleSnapshot{Token: "version-1", Namespace: "higress-test", Name: "default", OwnedNames: map[string]bool{"model-a": true, "model-b": true}, Entries: []RegistryEntry{{Name: "model-a", Domain: "a.test", Port: 443, Type: "dns"}, {Name: "model-b", Domain: "b.test", Port: 443, Type: "dns"}}}}
	w := BundleWriter{Client: c, Reader: c, Catalog: cat}
	ctx := context.Background()
	if err := w.Sync(ctx); !apierrors.IsConflict(err) {
		t.Fatal("CAS conflict ignored", err)
	}
	if err := w.Sync(ctx); err != nil {
		t.Fatal(err)
	}
	cat.snapshot.Entries = cat.snapshot.Entries[1:]
	cat.snapshot.Token = "version-2"
	if err := w.Sync(ctx); err != nil {
		t.Fatal(err)
	}
	if err := c.Get(ctx, client.ObjectKeyFromObject(bridge), bridge); err != nil {
		t.Fatal(err)
	}
	entries, _, _ := unstructured.NestedSlice(bridge.Object, "spec", "registries")
	if len(entries) != 2 || entries[0].(map[string]any)["custom"] != "keep" || bridge.Object["spec"].(map[string]any)["otherSetting"] != "preserve" {
		t.Fatal("lost shared config")
	}
	cat.stale = true
	if err := w.Sync(ctx); err != ErrConflict {
		t.Fatal("stale catalog accepted")
	}
}
