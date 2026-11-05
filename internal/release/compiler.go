package release

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"sort"
	"strings"

	api "github.com/jianzi123/maas/api/v1alpha1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/apis/meta/v1/unstructured"
	"k8s.io/apimachinery/pkg/util/validation"
)

const OwnerAnnotation = api.Group + "/cr-uid"
const PublicationAnnotation = api.Group + "/publication"
const DigestAnnotation = api.Group + "/plan-sha256"

func Hash(v any) string {
	b, _ := json.Marshal(v)
	h := sha256.Sum256(b)
	return hex.EncodeToString(h[:])
}
func Revision(s api.Spec, r Resolution) string {
	// Lifecycle is part of desired spec; dependency metadata rotation also changes
	// this digest without needing a new generation. Secret bytes are never accepted.
	return Hash(struct {
		Spec       api.Spec
		Resolution Resolution
	}{s, r})
}
func nameFor(uid, pub string) string { return "mr-" + Hash(uid)[:12] + "-" + Hash(pub)[:20] }

// Compile is pure and deterministic. SelfHosted is a nondeployable resource
// plan: approved runtime/placement templates and GPU evidence are still missing.
func Compile(m *api.ModelRelease, r Resolution, b Binding) (Plan, error) {
	if err := api.Validate(m.Spec, nil); err != nil {
		return Plan{}, err
	}
	if b.PublicationID == "" || b.Revision != Revision(m.Spec, r) || b.Generation != m.Generation {
		return Plan{}, ErrConflict
	}
	if len(validation.IsDNS1123Label(r.GatewayNamespace)) != 0 || len(validation.IsDNS1123Subdomain(r.IngressClass)) != 0 || len(validation.IsDNS1123Subdomain(r.HostSuffix)) != 0 {
		return Plan{}, ErrDependencyMissing
	}
	name := nameFor(string(m.UID), b.PublicationID)
	reg := RegistryEntry{Name: name, Domain: r.EndpointDNS, Port: r.EndpointPort, Type: "dns"}
	p := Plan{Deployable: m.Spec.Source.Type == "ExternalAPI"}
	if !p.Deployable {
		reg.Domain = name + "-leaders." + m.Namespace + ".svc.cluster.local"
		reg.Port = 30000
		h := m.Spec.Source.SelfHosted
		// This is intentionally a plan, not an executable LWS with an invented
		// startup command, rank, readiness, GPU or placement configuration.
		obj := &unstructured.Unstructured{Object: map[string]any{
			"apiVersion": "v1", "kind": "ConfigMap", "metadata": map[string]any{"name": name + "-runtime-plan", "namespace": m.Namespace},
			"immutable": true, "data": map[string]any{"engine": h.Engine, "workload": h.Workload, "image": h.Image, "pvc": h.Weights.PVCName, "weightsPath": h.Weights.Path,
				"apiVersion": "leaderworkerset.x-k8s.io/v1", "groups": fmt.Sprint(h.Groups), "podsPerGroup": fmt.Sprint(h.PodsPerGroup), "gpusPerPod": fmt.Sprint(h.GPUsPerPod), "totalGPUs": fmt.Sprint(h.Groups * h.PodsPerGroup * h.GPUsPerPod),
				"leaderWorkerTemplate.size": fmt.Sprint(h.PodsPerGroup), "tensorParallelSize": fmt.Sprint(h.TensorParallelSize), "pipelineParallelSize": fmt.Sprint(h.PipelineParallelSize), "gpuResourceName": h.GPUResourceName,
				"cpuPerPod": h.CPUPerPod, "memoryPerPod": h.MemoryPerPod, "weightsSHA256": h.Weights.SHA256, "modelRevision": h.Weights.ModelRevision, "runtimeProfile": h.RuntimeProfileRef.Name + "@" + h.RuntimeProfileRef.Revision, "placementProfile": h.PlacementProfileRef.Name + "@" + h.PlacementProfileRef.Revision,
				"status": "NONDEPLOYABLE: approved runtime and placement compiler required"}}}
		p.Objects = append(p.Objects, Seal(obj, m, b))
	} else {
		if len(validation.IsDNS1123Subdomain(r.EndpointDNS)) != 0 || r.EndpointPort < 1 || r.EndpointPort > 65535 || r.CredentialHandle == "" {
			return Plan{}, ErrDependencyMissing
		}
	}
	protocol := "HTTPS"
	if !p.Deployable {
		protocol = "HTTP"
	}
	ingress := &unstructured.Unstructured{Object: map[string]any{
		"apiVersion": "networking.k8s.io/v1", "kind": "Ingress",
		"metadata": map[string]any{"name": name, "namespace": r.GatewayNamespace, "annotations": map[string]any{"higress.io/destination": name + ".dns", "higress.io/backend-protocol": protocol}},
		"spec":     map[string]any{"ingressClassName": r.IngressClass, "rules": []any{map[string]any{"host": name + "." + r.HostSuffix, "http": map[string]any{"paths": []any{map[string]any{"path": "/v1/chat/completions", "pathType": "Exact", "backend": map[string]any{"resource": map[string]any{"apiGroup": "networking.higress.io", "kind": "McpBridge", "name": "default"}}}}}}}},
	}}
	p.Objects = append(p.Objects, Seal(ingress, m, b))
	p.Registry = reg
	return p, nil
}
func Seal(o *unstructured.Unstructured, m *api.ModelRelease, b Binding) ObjectPlan {
	a := o.GetAnnotations()
	if a == nil {
		a = map[string]string{}
	}
	a[OwnerAnnotation] = string(m.UID)
	a[PublicationAnnotation] = b.PublicationID
	delete(a, DigestAnnotation)
	o.SetAnnotations(a)
	digest := ObjectDigest(o)
	a[DigestAnnotation] = digest
	o.SetAnnotations(a)
	return ObjectPlan{Object: o, Digest: digest}
}
func ObjectDigest(o *unstructured.Unstructured) string {
	v := o.DeepCopy()
	v.SetResourceVersion("")
	v.SetUID("")
	v.SetCreationTimestamp(metav1.Time{})
	v.SetManagedFields(nil)
	v.SetGeneration(0)
	delete(v.Object, "status")
	a := v.GetAnnotations()
	delete(a, DigestAnnotation)
	v.SetAnnotations(a)
	return Hash(v.Object)
}

// MergeRegistry preserves every unmanaged entry, including its unknown fields.
// owned comes from durable inventory, never from a user-controlled name prefix.
// The single bundle writer must read-modify-write using resourceVersion CAS.
func MergeRegistry(current []any, owned map[string]bool, desired []RegistryEntry) ([]any, error) {
	out := []any{}
	seen := map[string]bool{}
	for _, item := range current {
		v, ok := item.(map[string]any)
		if !ok {
			return nil, ErrOwnership
		}
		name, ok := v["name"].(string)
		if !ok || name == "" || seen[name] {
			return nil, ErrOwnership
		}
		seen[name] = true
		if !owned[name] {
			out = append(out, item)
		}
	}
	desired = append([]RegistryEntry(nil), desired...)
	sort.Slice(desired, func(i, j int) bool { return desired[i].Name < desired[j].Name })
	added := map[string]bool{}
	for _, e := range desired {
		if e.Name == "" || added[e.Name] || (seen[e.Name] && !owned[e.Name]) {
			return nil, ErrOwnership
		}
		added[e.Name] = true
		out = append(out, map[string]any{"name": e.Name, "domain": e.Domain, "port": e.Port, "type": e.Type})
	}
	return out, nil
}
func isUUID(s string) bool { return len(s) == 36 && strings.Count(s, "-") == 4 }
