package admission

import (
	"context"
	"encoding/json"
	api "github.com/jianzi123/maas/api/v1alpha1"
	admissionv1 "k8s.io/api/admission/v1"
	"k8s.io/apimachinery/pkg/runtime"
	"os"
	"sigs.k8s.io/controller-runtime/pkg/webhook/admission"
	"sigs.k8s.io/yaml"
	"strings"
	"testing"
)

func TestWebhookFailClosedAndCleanupAllowed(t *testing.T) {
	data, err := os.ReadFile("../../config/samples/MAAS-2-modelrelease-externalapi-v0.4.example.yaml")
	if err != nil {
		t.Fatal(err)
	}
	data, err = yaml.YAMLToJSON(data)
	if err != nil {
		t.Fatal(err)
	}
	req := admission.Request{AdmissionRequest: admissionv1.AdmissionRequest{Operation: admissionv1.Create, Object: runtime.RawExtension{Raw: data}}}
	h := Handler{}
	ctx := context.Background()
	if h.Handle(ctx, req).Allowed {
		t.Fatal("missing resolver allowed create")
	}
	req.Operation = admissionv1.Update
	req.OldObject = req.Object
	if !h.Handle(ctx, req).Allowed {
		t.Fatal("finalizer update blocked by missing resolver")
	}
	var m api.ModelRelease
	_ = json.Unmarshal(data, &m)
	m.Spec.Lifecycle.DesiredState = "Paused"
	b, _ := json.Marshal(m)
	req.Object.Raw = b
	if !h.Handle(ctx, req).Allowed {
		t.Fatal("pause blocked by missing resolver")
	}
	req.Operation = admissionv1.Delete
	req.Object.Raw = nil
	if !h.Handle(ctx, req).Allowed {
		t.Fatal("delete denied")
	}
	req.Operation = admissionv1.Create
	req.Object.Raw = []byte(strings.Replace(string(data), `"provider":`, `"apiKey":"SENSITIVE","provider":`, 1))
	res := h.Handle(ctx, req)
	if res.Allowed || strings.Contains(res.Result.Message, "SENSITIVE") {
		t.Fatal("invalid spec was accepted/echoed")
	}
}
