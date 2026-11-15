package kernel

import (
	"context"
	"database/sql"
	"encoding/json"
	"github.com/jianzi123/maas/internal/protocol"
)

// AdminModels uses the same immutable profiles and publication gate as Admit.
// Missing capability metadata is unavailable, never an invented verified bound.
// Reading a catalogue reserves no Key budget or slot and performs no model call.
func (s *Store) AdminModels(ctx context.Context, gate ActiveGate, namespaces map[string]bool) (map[string]any, error) {
	out := map[string]any{"object": "list", "data": []any{}}
	e := s.tx(ctx, func(tx *sql.Tx) error {
		if _, e := s.guard(ctx, tx, "FOR UPDATE NOWAIT"); e != nil {
			return e
		}
		rows, e := tx.QueryContext(ctx, `SELECT i.snapshot_json,i.snapshot_sha256,i.blocked FROM invocation_profiles i JOIN publications p ON p.publication_id=i.publication_id JOIN release_links l ON l.cluster_id=p.cluster_id AND l.cr_uid=p.cr_uid AND (l.active_id=p.publication_id OR (l.active_id IS NULL AND l.candidate_id=p.publication_id)) WHERE p.cluster_id=? ORDER BY l.namespace,l.name`, s.cluster)
		if e != nil {
			return e
		}
		type item struct {
			p       Profile
			blocked bool
		}
		items := []item{}
		for rows.Next() {
			var b []byte
			var want string
			var it item
			if e = rows.Scan(&b, &want, &it.blocked); e != nil {
				rows.Close()
				return e
			}
			if json.Unmarshal(b, &it.p) != nil || hash(it.p) != want {
				rows.Close()
				return ErrUnavailable
			}
			if namespaces[it.p.Namespace] {
				items = append(items, it)
			}
		}
		e = rows.Err()
		rows.Close()
		if e != nil {
			return e
		}
		data := []any{}
		for _, it := range items {
			p := it.p
			if p.Catalog == nil {
				return ErrUnavailable
			}
			callable := false
			if gate != nil && !it.blocked {
				b, e := gate.LockActive(ctx, tx, p.CRUID)
				callable = e == nil && b == p.Binding
			}
			source := "external"
			if p.SourceType == "internal" {
				source = "internal"
			}
			var priceID, priceVersion any
			if p.Price != nil {
				priceID = p.Price.ID
				priceVersion = p.Price.Version
			}
			data = append(data, map[string]any{"id": p.Alias, "object": "model", "owned_by": "maas", "source_type": source, "source_id": p.SourceID, "display_name": p.Catalog.DisplayName, "capabilities": p.Catalog.Capabilities, "check_state": "unknown", "checked_at": nil, "config_revision": p.ConfigRevision, "release_binding": map[string]any{"model_release_uid": p.CRUID, "model_release_namespace": p.Namespace, "model_release_name": p.Name, "model_release_generation": p.Binding.Generation, "publication_id": p.Binding.PublicationID, "release_revision": p.Binding.Revision, "activation_epoch": p.Binding.Epoch, "route_binding_sha256": p.RouteDigest, "admission_purpose": "serving", "price_snapshot_id": priceID, "price_version": priceVersion}, "callable": callable})
		}
		out["data"] = data
		if protocol.Validate("AdminModelList", out) != nil {
			return ErrUnavailable
		}
		return nil
	})
	if e != nil {
		return nil, e
	}
	return out, nil
}
