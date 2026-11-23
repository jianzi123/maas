package release

import (
	"context"
	"encoding/hex"
	"encoding/json"
	api "github.com/jianzi123/maas/api/v1alpha1"
	"k8s.io/apimachinery/pkg/apis/meta/v1/unstructured"
	"net/url"
	"strings"
)

// TemplatePluginCompiler accepts installation-reviewed PUBLIC plugin metadata.
// Templates are keyed by the approved artifact digest; CRs cannot supply config.
// No template/artifact approval is manufactured by this compiler.
type TemplatePluginCompiler struct{ Templates map[string]map[string]any }

func publicPluginConfig(v any) bool {
	switch x := v.(type) {
	case map[string]any:
		for k, v := range x {
			switch strings.ToLower(strings.ReplaceAll(strings.ReplaceAll(k, "_", ""), "-", "")) {
			case "apikey", "apikeys", "token", "tokens", "authorization", "password", "secretvalue", "accesstoken":
				return false
			}
			if !publicPluginConfig(v) {
				return false
			}
		}
	case []any:
		for _, v := range x {
			if !publicPluginConfig(v) {
				return false
			}
		}
	}
	return true
}
func (c TemplatePluginCompiler) Compile(_ context.Context, m *api.ModelRelease, r Resolution, b Binding, name string) (*unstructured.Unstructured, error) {
	if m == nil || b.PublicationID == "" || b.Generation != m.Generation || b.Revision != Revision(m.Spec, r) || name != nameFor(string(m.UID), b.PublicationID) {
		return nil, ErrConflict
	}
	digest, digestErr := hex.DecodeString(r.PluginDigest)
	if digestErr != nil || len(digest) != 32 || strings.ToLower(r.PluginDigest) != r.PluginDigest {
		return nil, ErrDependencyMissing
	}
	template, ok := c.Templates[r.PluginDigest]
	if !ok || len(r.PluginDigest) != 64 || r.Versions["wasm_template_sha256"] == "" || Hash(template) != r.Versions["wasm_template_sha256"] {
		return nil, ErrDependencyMissing
	}
	for k := range template {
		switch k {
		case "url", "sha256", "phase", "priority", "pluginConfig":
		default:
			return nil, ErrDependencyMissing
		}
	}
	raw, err := json.Marshal(template)
	if err != nil || len(raw) > 65536 {
		return nil, ErrDependencyMissing
	}
	spec := map[string]any{}
	if json.Unmarshal(raw, &spec) != nil || !publicPluginConfig(spec["pluginConfig"]) {
		return nil, ErrDependencyMissing
	}
	location, _ := spec["url"].(string)
	u, err := url.Parse(location)
	if err != nil || u.Host == "" || u.User != nil || u.RawQuery != "" || u.Fragment != "" || (u.Scheme != "oci" && u.Scheme != "https") || spec["sha256"] != r.PluginDigest {
		return nil, ErrDependencyMissing
	}
	if u.Scheme == "oci" && !strings.HasSuffix(location, "@sha256:"+r.PluginDigest) {
		return nil, ErrDependencyMissing
	}
	spec["failStrategy"] = "FAIL_CLOSE"
	spec["defaultConfigDisable"] = true
	spec["matchRules"] = []any{map[string]any{"ingress": []any{name}, "configDisable": false}}
	o := &unstructured.Unstructured{Object: map[string]any{"apiVersion": "extensions.higress.io/v1alpha1", "kind": "WasmPlugin", "metadata": map[string]any{"name": name, "namespace": r.GatewayNamespace}, "spec": spec}}
	return o, nil
}
