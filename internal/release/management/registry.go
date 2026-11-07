package management

import (
	"context"
	"encoding/json"
	"reflect"

	api "github.com/jianzi123/maas/api/v1alpha1"
	"github.com/jianzi123/maas/internal/release"
	"github.com/jianzi123/maas/internal/release/history"
)

// Registry is an explicit installation-approved metadata input. It contains no
// Secret data, performs no model call, and does not assert gateway readiness.
// Loading new approval data requires an explicit process/configuration change.
type RegistryEntry struct {
	Namespace  string             `json:"namespace"`
	Spec       api.Spec           `json:"spec"`
	Resolution release.Resolution `json:"resolution"`
}
type Registry struct {
	Entries []RegistryEntry         `json:"entries"`
	Access  history.NamespaceAccess `json:"-"`
}

func (r Registry) Resolve(_ context.Context, m *api.ModelRelease) (release.Resolution, error) {
	if len(r.Entries) == 0 {
		return release.Resolution{}, history.ErrUnavailable
	}
	for _, entry := range r.Entries {
		want, got := entry.Spec, m.Spec
		want.Lifecycle = api.Lifecycle{}
		got.Lifecycle = api.Lifecycle{}
		if entry.Namespace == m.Namespace && r.Access.Namespaces[m.Namespace] && r.Access.Domains[entry.Resolution.Versions["authorization_domain"]] && reflect.DeepEqual(want, got) {
			// Return a copy so a consumer cannot mutate the approved snapshot.
			b, _ := json.Marshal(entry.Resolution)
			var result release.Resolution
			_ = json.Unmarshal(b, &result)
			return result, nil
		}
	}
	return release.Resolution{}, history.ReferenceFailure{Reason: "reference_unapproved"}
}
