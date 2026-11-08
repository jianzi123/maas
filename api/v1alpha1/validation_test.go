package v1alpha1

import (
	"bytes"
	"encoding/json"
	"github.com/santhosh-tekuri/jsonschema/v5"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"os"
	"sigs.k8s.io/yaml"
	"strings"
	"testing"
)

func sample(t *testing.T, source string) Spec {
	t.Helper()
	b, err := os.ReadFile("../../config/samples/MAAS-2-modelrelease-" + source + "-v0.4.example.yaml")
	if err != nil {
		t.Fatal(err)
	}
	var m ModelRelease
	if err = yaml.UnmarshalStrict(b, &m); err != nil {
		t.Fatal(err)
	}
	return m.Spec
}
func TestUnpublishedStatusMatchesArchitectureSchema(t *testing.T) {
	c := jsonschema.NewCompiler()
	normalized := bytes.ReplaceAll(schemaData, []byte(`^(?!/)(?!.*(?:^|/)\\.\\.(?:/|$))[A-Za-z0-9_./-]+$`), []byte(`^[A-Za-z0-9_./-]+$`))
	if err := c.AddResource("status.json", bytes.NewReader(normalized)); err != nil {
		t.Fatal(err)
	}
	s, err := c.Compile("status.json#/$defs/Status")
	if err != nil {
		t.Fatal(err)
	}
	status := Status{ObservedGeneration: 1, Phase: "Degraded", Conditions: []metav1.Condition{}, Resources: []ResourceRef{}}
	b, _ := json.Marshal(status)
	var v any
	_ = json.Unmarshal(b, &v)
	if err = s.Validate(v); err != nil {
		t.Fatal(err)
	}
}
func TestStrictSpecValidation(t *testing.T) {
	external := sample(t, "externalapi")
	private := sample(t, "selfhosted")
	for _, s := range []Spec{external, private} {
		if err := Validate(s, nil); err != nil {
			t.Fatal(err)
		}
	}
	cases := map[string]func(*Spec){
		"mixed":                  func(s *Spec) { s.Source.SelfHosted = private.Source.SelfHosted },
		"missing":                func(s *Spec) { s.Source.ExternalAPI = nil },
		"unknown source":         func(s *Spec) { s.Source.Type = "Other" },
		"cross namespace secret": func(s *Spec) { s.Source.ExternalAPI.CredentialSecretRef.Name = "other/secret" },
		"url as ref":             func(s *Spec) { s.Source.ExternalAPI.EndpointRef.Name = "https://arbitrary.test" },
		"missing revision":       func(s *Spec) { s.GatewayRef.Revision = "" },
		"retain data":            func(s *Spec) { s.Lifecycle.RetainUserData = false },
		"timeout relation":       func(s *Spec) { s.Lifecycle.ProgressDeadlineSeconds = 60 },
	}
	for name, mutate := range cases {
		t.Run(name, func(t *testing.T) {
			data, _ := json.Marshal(external)
			var s Spec
			_ = json.Unmarshal(data, &s)
			mutate(&s)
			if Validate(s, nil) == nil {
				t.Fatal("accepted invalid spec")
			}
		})
	}
	for _, path := range []string{"/absolute", "a/../weights", "../weights", "a/.."} {
		t.Run(path, func(t *testing.T) {
			s := sample(t, "selfhosted")
			s.Source.SelfHosted.Weights.Path = path
			if Validate(s, nil) == nil {
				t.Fatal("accepted path traversal")
			}
		})
	}
	private.Source.SelfHosted.TensorParallelSize = 2
	if Validate(private, nil) == nil {
		t.Fatal("invalid GPU topology accepted")
	}
	b, _ := json.Marshal(external)
	raw := strings.Replace(string(b), `"provider":`, `"apiKey":"MUST_NOT_ECHO","provider":`, 1)
	err := ValidateJSON([]byte(raw))
	if err == nil || strings.Contains(err.Error(), "MUST_NOT_ECHO") {
		t.Fatal("unknown/secret field was accepted or echoed")
	}
	raw = strings.Replace(string(b), `"modelAlias":`, `"command":"anything","modelAlias":`, 1)
	if ValidateJSON([]byte(raw)) == nil {
		t.Fatal("unknown top-level field accepted")
	}
	if ValidateJSON(append(b, []byte(" {}")...)) == nil {
		t.Fatal("trailing document accepted")
	}
}
func TestImmutableAliasAndSource(t *testing.T) {
	old := sample(t, "externalapi")
	changed := old
	changed.ModelAlias = "changed"
	if Validate(changed, &old) == nil {
		t.Fatal("alias mutable")
	}
	changed = sample(t, "selfhosted")
	changed.ModelAlias = old.ModelAlias
	if Validate(changed, &old) == nil {
		t.Fatal("source type mutable")
	}
}
