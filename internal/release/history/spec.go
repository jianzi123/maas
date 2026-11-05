package history

import (
	"context"
	"database/sql"
	"encoding/json"
	"errors"
	api "github.com/jianzi123/maas/api/v1alpha1"
)

func (r *Reader) LoadSpec(ctx context.Context, ns, name, uid, revision string) (api.Spec, error) {
	var spec api.Spec
	if r.PayloadDB == nil || r.Access == nil || !validUID(uid) || len(revision) != 64 {
		return spec, ErrInvalid
	}
	scope, e := r.Access.Scope(ctx, ns, name, uid)
	if e != nil || scope == "" {
		return spec, ErrForbidden
	}
	var domain sql.NullString
	if e = r.PayloadDB.QueryRowContext(ctx, "SELECT authorization_domain FROM release_history_directory WHERE cluster_id=? AND cr_uid=? AND namespace=? AND name=?", r.Cluster, uid, ns, name).Scan(&domain); e != nil || !domain.Valid {
		return spec, ErrUnavailable
	}
	if !r.Access.Domain(ctx, domain.String) {
		return spec, ErrNotFound
	}
	var b []byte
	var hash, state, algorithm string
	var payload []byte
	e = r.PayloadDB.QueryRowContext(ctx, "SELECT h.spec_bytes,h.spec_sha256,r.snapshot_state,h.revision_input_bytes,h.algorithm FROM retained_release_snapshots h JOIN release_history_retention r ON r.cluster_id=h.cluster_id AND r.cr_uid=h.cr_uid AND r.revision=h.revision WHERE h.cluster_id=? AND h.cr_uid=? AND h.namespace=? AND h.name=? AND h.revision=?", r.Cluster, uid, ns, name, revision).Scan(&b, &hash, &state, &payload, &algorithm)
	if errors.Is(e, sql.ErrNoRows) {
		var legacy int
		if r.PayloadDB.QueryRowContext(ctx, "SELECT COUNT(*) FROM release_revisions WHERE cluster_id=? AND cr_uid=? AND revision=?", r.Cluster, uid, revision).Scan(&legacy) != nil {
			return spec, ErrUnavailable
		}
		if legacy > 0 {
			return spec, ErrUnavailable
		}
		return spec, ErrNotFound
	}
	if e != nil {
		return spec, ErrUnavailable
	}
	if digest(payload) != revision || algorithm != "go-json-spec-resolution-sha256-v1" {
		return spec, ErrUnavailable
	}
	var original struct{ Spec api.Spec }
	if json.Unmarshal(payload, &original) != nil {
		return spec, ErrUnavailable
	}
	originalSpec, _ := json.Marshal(original.Spec)
	if string(originalSpec) != string(b) {
		return spec, ErrUnavailable
	}
	if state != "retained" || digest(b) != hash || json.Unmarshal(b, &spec) != nil || api.Validate(spec, nil) != nil {
		return spec, ErrUnavailable
	}
	return spec, nil
}
