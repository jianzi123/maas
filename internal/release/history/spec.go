package history

import (
	"context"
	"database/sql"
	"encoding/json"
	"errors"
	api "github.com/jianzi123/maas/api/v1alpha1"
	"k8s.io/apimachinery/pkg/util/validation"
	"regexp"
)

var revisionPattern = regexp.MustCompile(`^[0-9a-f]{64}$`)

func (r *Reader) LoadSpec(ctx context.Context, ns, name, uid, revision string) (api.Spec, error) {
	var spec api.Spec
	// Malformed identifiers remain input errors even when dependencies are absent.
	// Configuration/connection failures must never be reported as bad user input.
	if !validUID(uid) || !revisionPattern.MatchString(revision) || len(validation.IsDNS1123Label(ns)) != 0 || len(validation.IsDNS1123Label(name)) != 0 {
		return spec, ErrInvalid
	}
	if r == nil || r.Access == nil || r.Cluster == "" {
		return spec, ErrUnavailable
	}
	scope, e := r.Access.Scope(ctx, ns, name, uid)
	if e != nil {
		if errors.Is(e, ErrForbidden) {
			return spec, ErrForbidden
		}
		if errors.Is(e, ErrNotFound) {
			return spec, ErrNotFound
		}
		return spec, ErrUnavailable
	}
	if scope == "" {
		return spec, ErrForbidden
	}
	if r.PayloadDB == nil {
		return spec, ErrUnavailable
	}
	var domain sql.NullString
	e = r.PayloadDB.QueryRowContext(ctx, "SELECT authorization_domain FROM release_history_directory WHERE cluster_id=? AND cr_uid=? AND namespace=? AND name=?", r.Cluster, uid, ns, name).Scan(&domain)
	if errors.Is(e, sql.ErrNoRows) {
		return spec, ErrNotFound
	}
	if e != nil || !domain.Valid {
		return spec, ErrUnavailable
	}
	if !r.Access.Domain(ctx, domain.String) {
		return spec, ErrNotFound
	}
	var b []byte
	var hash, algorithm string
	var state sql.NullString
	var payload []byte
	e = r.PayloadDB.QueryRowContext(ctx, "SELECT h.spec_bytes,h.spec_sha256,r.snapshot_state,h.revision_input_bytes,h.algorithm FROM retained_release_snapshots h LEFT JOIN release_history_retention r ON r.cluster_id=h.cluster_id AND r.cr_uid=h.cr_uid AND r.revision=h.revision WHERE h.cluster_id=? AND h.cr_uid=? AND h.namespace=? AND h.name=? AND h.revision=?", r.Cluster, uid, ns, name, revision).Scan(&b, &hash, &state, &payload, &algorithm)
	if errors.Is(e, sql.ErrNoRows) {
		var legacy int
		if r.PayloadDB.QueryRowContext(ctx, "SELECT COUNT(*) FROM release_revisions WHERE cluster_id=? AND cr_uid=? AND revision=?", r.Cluster, uid, revision).Scan(&legacy) != nil {
			return spec, ErrUnavailable
		}
		if legacy > 0 {
			// The original domain is visible and this revision is known, but no
			// private snapshot exists. Waiting for a dependency cannot restore it.
			return spec, ErrConflict
		}
		return spec, ErrNotFound
	}
	if e != nil {
		return spec, ErrUnavailable
	}
	// A missing retention row is an integrity failure, not evidence of pruning.
	if !state.Valid {
		return spec, ErrUnavailable
	}
	switch state.String {
	case "pruning", "unavailable":
		return spec, ErrConflict
	case "retained":
	default:
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
	if digest(b) != hash || json.Unmarshal(b, &spec) != nil || api.Validate(spec, nil) != nil {
		return spec, ErrUnavailable
	}
	return spec, nil
}
