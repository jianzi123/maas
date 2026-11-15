// Package protocol preserves MAAS-2 ticket v3 and terminal 3.0 contracts.
package protocol

import (
	"bytes"
	"crypto/hmac"
	"crypto/sha256"
	_ "embed"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"errors"
	"io"
	"strconv"
	"strings"

	"github.com/santhosh-tekuri/jsonschema/v5"
)

//go:embed contracts/terminal.schema.json
var terminalBytes []byte

//go:embed contracts/private.schema.json
var privateBytes []byte
var ErrInvalid = errors.New("invalid private protocol")

//go:embed contracts/management.schema.json
var managementBytes []byte

//go:embed contracts/diagnostic.schema.json
var diagnosticBytes []byte
var schemas = compile()

func compile() map[string]*jsonschema.Schema {
	c := jsonschema.NewCompiler()
	c.AssertFormat = true
	if e := c.AddResource("https://maas.local/private.json", bytes.NewReader(privateBytes)); e != nil {
		panic(e)
	}
	if e := c.AddResource("https://maas.local/terminal.json", bytes.NewReader(terminalBytes)); e != nil {
		panic(e)
	}
	// Same RE2-compatible path normalization as api.ValidateJSON; the embedded
	// architect-authored schema stays unchanged. Spec semantic checks run before IO.
	normalized := bytes.ReplaceAll(managementBytes, []byte(`^(?!/)(?!.*(?:^|/)\\.\\.(?:/|$))[A-Za-z0-9_./-]+$`), []byte(`^[A-Za-z0-9_./-]+$`))
	if e := c.AddResource("https://maas.local/management.json", bytes.NewReader(normalized)); e != nil {
		panic(e)
	}
	if e := c.AddResource("https://maas.local/diagnostic.json", bytes.NewReader(diagnosticBytes)); e != nil {
		panic(e)
	}
	out := map[string]*jsonschema.Schema{}
	out["Diagnostic"] = c.MustCompile("https://maas.local/diagnostic.json")
	for _, n := range []string{"KeyCreate", "KeyPatch", "Key", "KeyCreated", "KeyPage", "RequestPage", "RequestLookupPage", "SummaryPage", "ReleaseRevisionPage", "ChatChunk", "ChatResponse", "Error", "AdminModelList", "ReleaseReleaseInput", "ReleaseModelRelease", "ReleaseList", "ReleaseAccepted", "ReleaseOperation", "ReleaseRollbackInput"} {
		out[n] = c.MustCompile("https://maas.local/management.json#/$defs/" + n)
	}
	for _, name := range []string{"AdmissionHeader", "AdmissionClaims", "ReservationPlan"} {
		out[name] = c.MustCompile("https://maas.local/private.json#/$defs/" + name)
	}
	out["Terminal"] = c.MustCompile("https://maas.local/terminal.json")
	return out
}
func Validate(name string, v any) error {
	b, e := json.Marshal(v)
	if e != nil {
		return ErrInvalid
	}
	d := json.NewDecoder(bytes.NewReader(b))
	d.UseNumber()
	var x any
	if e = d.Decode(&x); e != nil {
		return ErrInvalid
	}
	schema, ok := schemas[name]
	if !ok {
		return ErrInvalid
	}
	if e = schema.Validate(x); e != nil {
		return ErrInvalid
	}
	return nil
}

// Canonical rejects duplicate object keys at EVERY level, trailing values,
// fractional/exponent/unsafe numeric spellings and unknown fields via Schema.
func Canonical(b []byte) ([]byte, error) {
	if !json.Valid(b) {
		return nil, ErrInvalid
	}
	d := json.NewDecoder(bytes.NewReader(b))
	d.UseNumber()
	v, e := read(d)
	if e != nil {
		return nil, e
	}
	if _, e = d.Token(); e != io.EOF {
		return nil, ErrInvalid
	}
	return json.Marshal(v)
}
func read(d *json.Decoder) (any, error) {
	t, e := d.Token()
	if e != nil {
		return nil, ErrInvalid
	}
	switch v := t.(type) {
	case json.Delim:
		if v == '{' {
			m := map[string]any{}
			for d.More() {
				k, e := d.Token()
				if e != nil {
					return nil, ErrInvalid
				}
				key, ok := k.(string)
				if !ok {
					return nil, ErrInvalid
				}
				if _, ok = m[key]; ok {
					return nil, ErrInvalid
				}
				x, e := read(d)
				if e != nil {
					return nil, e
				}
				m[key] = x
			}
			_, e = d.Token()
			return m, e
		}
		if v == '[' {
			a := []any{}
			for d.More() {
				x, e := read(d)
				if e != nil {
					return nil, e
				}
				a = append(a, x)
			}
			_, e = d.Token()
			return a, e
		}
		return nil, ErrInvalid
	case json.Number:
		n, e := strconv.ParseInt(v.String(), 10, 64)
		if e != nil || n < 0 || n > 9007199254740991 || strconv.FormatInt(n, 10) != v.String() {
			return nil, ErrInvalid
		}
		return v, nil
	default:
		return t, nil
	}
}
func Digest(b []byte) string { sum := sha256.Sum256(b); return hex.EncodeToString(sum[:]) }

type Ticket struct {
	Header, Claims map[string]any
	Plan           []byte
	Digest         string
}

// VerifyTicket accepts only the frozen v3, HS256 and exact canonical encoding.
// key comes from the admission-purpose registry; transport keys are separate.
func VerifyTicket(compact, planHeader string, key []byte) (Ticket, error) {
	out := Ticket{}
	if len(compact) > 4096 || len(planHeader) > 4096 || len(key) < 32 {
		return out, ErrInvalid
	}
	parts := strings.Split(compact, ".")
	if len(parts) != 3 {
		return out, ErrInvalid
	}
	decoded := make([][]byte, 3)
	for i, part := range parts {
		b, e := base64.RawURLEncoding.Strict().DecodeString(part)
		if e != nil || base64.RawURLEncoding.EncodeToString(b) != part {
			return out, ErrInvalid
		}
		decoded[i] = b
	}
	mac := hmac.New(sha256.New, key)
	mac.Write([]byte(parts[0] + "." + parts[1]))
	if !hmac.Equal(mac.Sum(nil), decoded[2]) {
		return out, ErrInvalid
	}
	for i, name := range []string{"AdmissionHeader", "AdmissionClaims"} {
		canonical, e := Canonical(decoded[i])
		if e != nil || !bytes.Equal(canonical, decoded[i]) {
			return out, ErrInvalid
		}
		var v map[string]any
		decoder := json.NewDecoder(bytes.NewReader(canonical))
		decoder.UseNumber()
		if e = decoder.Decode(&v); e != nil || Validate(name, v) != nil {
			return out, ErrInvalid
		}
		if i == 0 {
			out.Header = v
		} else {
			out.Claims = v
		}
	}
	plan, e := base64.RawURLEncoding.Strict().DecodeString(planHeader)
	if e != nil {
		return out, ErrInvalid
	}
	canonical, e := Canonical(plan)
	if e != nil || !bytes.Equal(canonical, plan) || Digest(plan) != out.Claims["budget_plan_sha256"] {
		return out, ErrInvalid
	}
	var p any
	d := json.NewDecoder(bytes.NewReader(plan))
	d.UseNumber()
	if e = d.Decode(&p); e != nil || Validate("ReservationPlan", p) != nil {
		return out, ErrInvalid
	}
	out.Plan = plan
	out.Digest = Digest([]byte(compact))
	return out, nil
}
