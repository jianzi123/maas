package protocol

import "testing"

func TestToolJSONSignedDomainKeepsFinancialDomainStrict(t *testing.T) {
	for _, raw := range []string{`{"minimum":-1000000000,"maximum":1000000000}`, `{"a":-6,"b":7,"op":"multiply"}`} {
		if _, e := CanonicalToolJSON([]byte(raw)); e != nil {
			t.Fatal("valid signed tool JSON rejected", e)
		}
		if _, e := Canonical([]byte(raw)); e == nil {
			t.Fatal("financial canonical was relaxed")
		}
	}
	for _, raw := range []string{`{"a":-0}`, `{"a":-9007199254740992}`, `{"a":-1.5}`, `{"a":-1e3}`, `{"a":-1,"a":2}`, `{"nested":{"a":1,"a":2}}`} {
		if _, e := CanonicalToolJSON([]byte(raw)); e == nil {
			t.Fatal("ambiguous/unsafe tool JSON accepted", raw)
		}
	}
}
