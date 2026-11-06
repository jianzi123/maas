package release

import (
	"context"
	api "github.com/jianzi123/maas/api/v1alpha1"
	"k8s.io/apimachinery/pkg/apis/meta/v1/unstructured"
	"reflect"
	"testing"
)

func TestCompileSourcesAndDeterminism(t *testing.T) {
	for _, source := range []string{"externalapi", "selfhosted"} {
		t.Run(source, func(t *testing.T) {
			m := fixture(t, source)
			res, _ := (&resolver{version: "1"}).Resolve(context.Background(), m)
			rev := Revision(m.Spec, res)
			b := Binding{PublicationID: "11111111-1111-4111-8111-111111111111", Revision: rev, Generation: m.Generation, Epoch: 1}
			p, err := Compile(m, res, b)
			if err != nil {
				t.Fatal(err)
			}
			again, err := Compile(m, res, b)
			if err != nil || !reflect.DeepEqual(p, again) {
				t.Fatal("nondeterministic compile")
			}
			if p.Deployable != (source == "externalapi") {
				t.Fatal("wrong deployment capability")
			}
			for _, obj := range p.Objects {
				if len(obj.Object.GetOwnerReferences()) != 0 {
					t.Fatal("unsafe CR GC owner")
				}
				if source == "externalapi" && obj.Object.GetKind() != "Ingress" {
					t.Fatal("external runtime resources")
				}
			}
			if source == "selfhosted" {
				data, _, _ := unstructured.NestedStringMap(p.Objects[0].Object.Object, "data")
				if data["totalGPUs"] != "1" || data["status"] == "" {
					t.Fatal("invalid runtime plan")
				}
			}
		})
	}
}
func TestRegistryUnionPreservesOtherModelsAndUnmanagedFields(t *testing.T) {
	manual := map[string]any{"name": "manual", "domain": "manual.test", "custom": "preserve"}
	current := []any{manual, map[string]any{"name": "model-a"}, map[string]any{"name": "model-b"}}
	desired := []RegistryEntry{{Name: "model-b", Domain: "b.test", Port: 443, Type: "dns"}}
	merged, err := MergeRegistry(current, map[string]bool{"model-a": true, "model-b": true}, desired)
	if err != nil || len(merged) != 2 || !reflect.DeepEqual(merged[0], manual) {
		t.Fatal("shared entries lost", merged, err)
	}
	if _, err = MergeRegistry(current, map[string]bool{}, []RegistryEntry{{Name: "manual"}}); err != ErrOwnership {
		t.Fatal("adopted unmanaged registry")
	}
	if _, err = MergeRegistry(current, map[string]bool{}, []RegistryEntry{{Name: "x"}, {Name: "x"}}); err == nil {
		t.Fatal("duplicate names accepted")
	}
}
func TestTwoModelsSharedGatewayCleanupIsolation(t *testing.T) {
	h := newHarness(t)
	h.run()
	h.run()
	second := fixture(t, "externalapi")
	second.Name = "second"
	second.Spec.ModelAlias = "second"
	second.Spec.Source.ExternalAPI.UpstreamModel = "other-provider-model"
	// Create test CR without resource-intent interceptor (CRs are user-owned).
	h.inventory.beforeCreate++
	if err := h.c.Create(context.Background(), second); err != nil {
		t.Fatal(err)
	}
	r := h.r
	original := h.m
	h.m = second
	h.run()
	h.run()
	if len(h.bundle.entries) != 2 {
		t.Fatal("shared gateway overwritten")
	}
	h.m = original
	h.change(func(m *api.ModelRelease) { m.Spec.Lifecycle.DesiredState = "Paused" })
	h.run()
	if len(h.bundle.entries) != 1 {
		t.Fatal("other model registration removed")
	}
	entries, _ := h.inventory.List(context.Background(), string(second.UID), "")
	if len(entries) != 2 {
		t.Fatal("other model resources removed")
	}
	h.m = second
	h.r = r
	h.run()
	ready(t, h.current(), true)
}
