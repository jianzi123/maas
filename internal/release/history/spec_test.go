package history

import (
	"context"
	"errors"
	"strings"
	"testing"
)

func TestLoadSpecInputAndDependencyErrors(t *testing.T) {
	uid := "01234567-89ab-4cde-8f01-23456789abcd"
	revision := strings.Repeat("a", 64)
	access := NamespaceAccess{ScopeID: "test", Namespaces: map[string]bool{"models": true}}
	for _, tc := range []struct {
		name                        string
		reader                      *Reader
		ns, nameOfCR, uid, revision string
		want                        error
	}{
		{"missing_private_connection", &Reader{Cluster: "test", Access: access}, "models", "model", uid, revision, ErrUnavailable},
		{"missing_access_adapter", &Reader{Cluster: "test"}, "models", "model", uid, revision, ErrUnavailable},
		{"missing_reader", nil, "models", "model", uid, revision, ErrUnavailable},
		{"missing_cluster", &Reader{Access: access}, "models", "model", uid, revision, ErrUnavailable},
		{"invalid_uid", nil, "models", "model", "invalid", revision, ErrInvalid},
		{"short_revision", nil, "models", "model", uid, "a", ErrInvalid},
		{"non_hex_revision", nil, "models", "model", uid, strings.Repeat("z", 64), ErrInvalid},
		{"noncanonical_revision", nil, "models", "model", uid, strings.Repeat("A", 64), ErrInvalid},
		{"invalid_namespace", nil, "Models", "model", uid, revision, ErrInvalid},
		{"invalid_name", nil, "models", "../model", uid, revision, ErrInvalid},
		{"forbidden_scope", &Reader{Cluster: "test", Access: access}, "other", "model", uid, revision, ErrForbidden},
	} {
		t.Run(tc.name, func(t *testing.T) {
			_, err := tc.reader.LoadSpec(context.Background(), tc.ns, tc.nameOfCR, tc.uid, tc.revision)
			if !errors.Is(err, tc.want) {
				t.Fatalf("got %v, want %v", err, tc.want)
			}
		})
	}
}
