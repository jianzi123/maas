package v1alpha1

import (
	"bytes"
	_ "embed"
	"encoding/json"
	"errors"
	"io"
	"strings"
	"sync"

	"github.com/santhosh-tekuri/jsonschema/v5"
)

//go:embed modelrelease.schema.json
var schemaData []byte
var compiled *jsonschema.Schema
var compileErr error
var once sync.Once

// ValidateJSON validates the exact spec before typed decoding can discard fields.
// Diagnostics deliberately do not echo user input or schema error values.
func ValidateJSON(data []byte) error {
	once.Do(func() {
		c := jsonschema.NewCompiler()
		// RE2 has no JSON-Schema lookahead. Match the CRD's character pattern here
		// and enforce the equivalent absolute/traversal exclusions below. The embedded
		// architect-authored source stays byte-for-byte unchanged.
		normalized := bytes.ReplaceAll(schemaData, []byte(`^(?!/)(?!.*(?:^|/)\\.\\.(?:/|$))[A-Za-z0-9_./-]+$`), []byte(`^[A-Za-z0-9_./-]+$`))
		compileErr = c.AddResource("modelrelease.json", bytes.NewReader(normalized))
		if compileErr == nil {
			compiled, compileErr = c.Compile("modelrelease.json#/$defs/Spec")
		}
	})
	if compileErr != nil {
		return errors.New("schema initialization failed")
	}
	var value any
	d := json.NewDecoder(bytes.NewReader(data))
	d.UseNumber()
	if d.Decode(&value) != nil {
		return errors.New("InvalidSpec")
	}
	var trailing any
	if d.Decode(&trailing) != io.EOF {
		return errors.New("InvalidSpec")
	}
	if compiled.Validate(value) != nil {
		return errors.New("InvalidSpec")
	}
	var s Spec
	if json.Unmarshal(data, &s) != nil {
		return errors.New("InvalidSpec")
	}
	if s.Lifecycle.ProgressDeadlineSeconds < s.Lifecycle.DrainTimeoutSeconds {
		return errors.New("InvalidSpec")
	}
	if h := s.Source.SelfHosted; h != nil {
		if h.TensorParallelSize*h.PipelineParallelSize != h.PodsPerGroup*h.GPUsPerPod {
			return errors.New("InvalidSpec")
		}
		if h.StartupTimeoutSeconds > s.Lifecycle.ProgressDeadlineSeconds {
			return errors.New("InvalidSpec")
		}
		// JSON Schema uses lookahead; the CRD uses CEL. Recheck traversal here.
		if strings.HasPrefix(h.Weights.Path, "/") {
			return errors.New("InvalidSpec")
		}
		for _, p := range strings.Split(h.Weights.Path, "/") {
			if p == ".." {
				return errors.New("InvalidSpec")
			}
		}
	}
	return nil
}
func Validate(s Spec, old *Spec) error {
	data, err := json.Marshal(s)
	if err != nil {
		return errors.New("InvalidSpec")
	}
	if err = ValidateJSON(data); err != nil {
		return err
	}
	if old != nil && (old.ModelAlias != s.ModelAlias || old.Source.Type != s.Source.Type) {
		return errors.New("ImmutableField")
	}
	return nil
}
