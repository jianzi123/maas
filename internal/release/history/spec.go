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
	if r.DB == nil || r.Access == nil || !validUID(uid) || len(revision) != 64 {
		return spec, ErrInvalid
	}
	scope, e := r.Access.Scope(ctx, ns, name, uid)
	if e != nil || scope == "" {
		return spec, ErrForbidden
	}
	var b []byte
	var hash, state string
	e = r.DB.QueryRowContext(ctx, "SELECT spec_bytes,spec_sha256,snapshot_state FROM retained_release_snapshots WHERE cluster_id=? AND cr_uid=? AND namespace=? AND name=? AND revision=?", r.Cluster, uid, ns, name, revision).Scan(&b, &hash, &state)
	if errors.Is(e, sql.ErrNoRows) {
		var legacy int
		if r.DB.QueryRowContext(ctx, "SELECT COUNT(*) FROM release_revisions WHERE cluster_id=? AND cr_uid=? AND revision=?", r.Cluster, uid, revision).Scan(&legacy) != nil {
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
	if state != "retained" || digest(b) != hash || json.Unmarshal(b, &spec) != nil || api.Validate(spec, nil) != nil {
		return spec, ErrUnavailable
	}
	return spec, nil
}
