package agentruntime

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"math/big"
	"sort"

	"github.com/jianzi123/maas/internal/protocol"
	"github.com/santhosh-tekuri/jsonschema/v5"
)

type Registry struct{ tools map[string]Tool }

func NewRegistry(tools ...Tool) (*Registry, error) {
	r := &Registry{tools: map[string]Tool{}}
	for _, t := range tools {
		if t == nil {
			return nil, ErrInvalid
		}
		s := t.Spec()
		if s.Name == "" || s.Version == "" || s.Permission == "" || (s.Effect != "pure" && s.Effect != "read" && s.Effect != "write") || (s.Effect == "write" && !s.Approval) {
			return nil, ErrInvalid
		}
		if _, ok := r.tools[s.Name]; ok {
			return nil, ErrConflict
		}
		if _, e := compile(s.Schema); e != nil {
			return nil, e
		}
		r.tools[s.Name] = t
	}
	return r, nil
}
func (r *Registry) Lookup(n string) (Tool, bool) { t, ok := r.tools[n]; return t, ok }
func (r *Registry) Specs(p Principal) []ToolSpec {
	out := []ToolSpec{}
	for _, t := range r.tools {
		if p.Permissions[t.Spec().Permission] {
			out = append(out, t.Spec())
		}
	}
	sort.Slice(out, func(i, j int) bool { return out[i].Name < out[j].Name })
	return out
}
func compile(raw []byte) (*jsonschema.Schema, error) {
	c := jsonschema.NewCompiler()
	if e := c.AddResource("inmemory://tool.json", bytes.NewReader(raw)); e != nil {
		return nil, e
	}
	return c.Compile("inmemory://tool.json")
}
func validate(t Tool, b []byte) error {
	if _, e := protocol.CanonicalToolJSON(b); e != nil {
		return ErrInvalid
	}
	s, e := compile(t.Spec().Schema)
	if e != nil {
		return ErrInvalid
	}
	var v any
	dec := json.NewDecoder(bytes.NewReader(b))
	dec.UseNumber()
	if dec.Decode(&v) != nil {
		return ErrInvalid
	}
	if dec.Decode(new(any)) != io.EOF {
		return ErrInvalid
	}
	if s.Validate(v) != nil {
		return ErrInvalid
	}
	return nil
}

func validateOutput(t Tool, output string) error {
	raw := t.Spec().OutputSchema
	if len(raw) == 0 {
		raw = json.RawMessage(`{"type":"string"}`)
	}
	s, e := compile(raw)
	if e != nil {
		return e
	}
	return s.Validate(output)
}

// Calculator deliberately accepts only bounded integer arithmetic, never code.
type Calculator struct{}

func (Calculator) Spec() ToolSpec {
	return ToolSpec{Name: "bounded_arithmetic", Version: "1", Permission: "tools.calculate", Effect: "pure", Schema: json.RawMessage(`{"type":"object","properties":{"a":{"type":"integer","minimum":-1000000000,"maximum":1000000000},"b":{"type":"integer","minimum":-1000000000,"maximum":1000000000},"op":{"enum":["add","subtract","multiply"]}},"required":["a","b","op"],"additionalProperties":false}`)}
}
func (Calculator) Execute(ctx context.Context, _ Principal, _ string, b json.RawMessage) (string, error) {
	if ctx.Err() != nil {
		return "", ctx.Err()
	}
	var v struct {
		A, B int64
		Op   string
	}
	if json.Unmarshal(b, &v) != nil {
		return "", ErrInvalid
	}
	a, c := big.NewInt(v.A), big.NewInt(v.B)
	switch v.Op {
	case "add":
		a.Add(a, c)
	case "subtract":
		a.Sub(a, c)
	case "multiply":
		a.Mul(a, c)
	default:
		return "", ErrInvalid
	}
	return a.String(), nil
}

// ModelDirectory must enforce the current principal's visibility in Read.
type ModelDirectory struct {
	Read func(context.Context, Principal) ([]string, error)
}

func (ModelDirectory) Spec() ToolSpec {
	return ToolSpec{Name: "list_visible_models", Version: "1", Permission: "models.read", Effect: "read", Schema: json.RawMessage(`{"type":"object","properties":{},"additionalProperties":false}`)}
}
func (t ModelDirectory) Execute(ctx context.Context, p Principal, _ string, _ json.RawMessage) (string, error) {
	if t.Read == nil {
		return "", ErrUnavailable
	}
	v, e := t.Read(ctx, p)
	if e != nil {
		return "", e
	}
	b, e := json.Marshal(v)
	return fmt.Sprint(string(b)), e
}
