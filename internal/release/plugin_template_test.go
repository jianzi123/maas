package release

import (
	"context"
	"encoding/json"
	"k8s.io/apimachinery/pkg/apis/meta/v1/unstructured"
	"os"
	"strings"
	"testing"
)

func TestPinnedPluginTemplate(t *testing.T) {
	m := fixture(t, "externalapi")
	r, _ := (&resolver{version: "1"}).Resolve(context.Background(), m)
	r.GatewayNamespace = "higress-system"
	r.PluginDigest = strings.Repeat("a", 64)
	template := map[string]any{"url": "oci://registry.invalid/maas-plugin@sha256:" + r.PluginDigest, "sha256": r.PluginDigest, "phase": "AUTHN", "pluginConfig": map[string]any{"credentialHandle": "opaque-reference-only"}}
	r.Versions["wasm_template_sha256"] = Hash(template)
	b := Binding{PublicationID: "11111111-1111-4111-8111-111111111111", Generation: m.Generation, Epoch: 1, Revision: Revision(m.Spec, r)}
	c := TemplatePluginCompiler{Templates: map[string]map[string]any{r.PluginDigest: template}}
	name := nameFor(string(m.UID), b.PublicationID)
	o, e := c.Compile(context.Background(), m, r, b, name)
	if e != nil {
		t.Fatal(e)
	}
	if o.GetName() != name || o.GetNamespace() != r.GatewayNamespace {
		t.Fatal("wrong scope")
	}
	fail, _, _ := unstructured.NestedString(o.Object, "spec", "failStrategy")
	disabled, _, _ := unstructured.NestedBool(o.Object, "spec", "defaultConfigDisable")
	if fail != "FAIL_CLOSE" || !disabled {
		t.Fatal("unsafe default")
	}
	rules, _, _ := unstructured.NestedSlice(o.Object, "spec", "matchRules")
	if len(rules) != 1 {
		t.Fatal("not ingress-scoped")
	}
	if path := os.Getenv("MAAS_PLUGIN_EVIDENCE"); path != "" {
		plan, e := Compile(m, r, b)
		if e != nil {
			t.Fatal(e)
		}
		items := []any{o.Object}
		for _, object := range plan.Objects {
			items = append(items, object.Object.Object)
		}
		data, _ := json.Marshal(map[string]any{"apiVersion": "v1", "kind": "List", "items": items})
		if e = os.WriteFile(path, data, 0600); e != nil {
			t.Fatal(e)
		}
		data, _ = json.Marshal(plan.Registry)
		if e = os.WriteFile(path+".registry.json", data, 0600); e != nil {
			t.Fatal(e)
		}
	}
	// Output mutation must not mutate installation template.
	unstructured.SetNestedField(o.Object, "bad", "spec", "url")
	if template["url"] == "bad" {
		t.Fatal("template alias")
	}
	for _, mode := range []string{"missing", "drift", "inline-secret", "typed-secret", "override-selector", "wrong-name"} {
		t.Run(mode, func(t *testing.T) {
			tmp := map[string]any{}
			for k, v := range template {
				tmp[k] = v
			}
			rr := r
			rr.Versions = map[string]string{}
			for k, v := range r.Versions {
				rr.Versions[k] = v
			}
			cc := TemplatePluginCompiler{Templates: map[string]map[string]any{r.PluginDigest: tmp}}
			n := name
			switch mode {
			case "missing":
				cc.Templates = nil
			case "drift":
				tmp["priority"] = int64(1)
			case "inline-secret":
				tmp["pluginConfig"] = map[string]any{"api_key": "forbidden-test-only"}
				rr.Versions["wasm_template_sha256"] = Hash(tmp)
			case "typed-secret":
				tmp["pluginConfig"] = map[string]string{"token": "forbidden-test-only"}
				rr.Versions["wasm_template_sha256"] = Hash(tmp)
			case "override-selector":
				tmp["matchRules"] = []any{}
				rr.Versions["wasm_template_sha256"] = Hash(tmp)
			case "wrong-name":
				n = "other"
			}
			bb := b
			bb.Revision = Revision(m.Spec, rr)
			if _, e := cc.Compile(context.Background(), m, rr, bb, n); e == nil {
				t.Fatal("unsafe input accepted")
			}
		})
	}
}
