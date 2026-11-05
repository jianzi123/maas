// Package history reads retained release facts. It never authorizes inference.
package history

import (
	"context"
	"crypto/sha256"
	"database/sql"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"errors"
	"github.com/google/uuid"
	api "github.com/jianzi123/maas/api/v1alpha1"
	"net/url"
	"strconv"
	"time"
)

var ErrUnavailable = errors.New("release_dependency_unavailable")
var ErrNotFound = errors.New("not_found")
var ErrForbidden = errors.New("forbidden")
var ErrInvalid = errors.New("invalid_request")
var ErrConflict = errors.New("resource_version_conflict")

// Access must enforce original durable namespace/name/UID ownership, even if
// the live object is deleted or replaced. Scope is part of every cursor.
type Access interface {
	Scope(context.Context, string, string, string) (string, error)
}
type LiveState struct {
	UID, Version, SourceType, Namespace, Name string
	State                                     string
}
type Live interface {
	Current(context.Context, string, string) (LiveState, error)
}
type Evaluation struct {
	State   string
	Reasons []string
}
type Evaluator interface {
	Evaluate(context.Context, api.Spec, LiveState) (Evaluation, error)
}
type Reader struct {
	DB        *sql.DB
	Cluster   string
	Access    Access
	Live      Live
	Evaluator Evaluator
}
type row struct {
	Revision, UID, Namespace, Name, Alias, Source, State string
	Generation                                           int64
	Created                                              time.Time
	Spec                                                 api.Spec
}
type cursor struct{ Scope, Namespace, Name, UID, Revision, Time string }

func digest(b []byte) string { s := sha256.Sum256(b); return hex.EncodeToString(s[:]) }
func (r *Reader) ReadRevisions(ctx context.Context, ns, name string, q url.Values) (map[string]any, error) {
	if r.DB == nil || r.Access == nil || r.Cluster == "" {
		return nil, ErrUnavailable
	}
	for k, v := range q {
		if len(v) != 1 || (k != "cr_uid" && k != "page_size" && k != "cursor") {
			return nil, ErrInvalid
		}
	}
	uid := q.Get("cr_uid")
	if !validUID(uid) {
		return nil, ErrInvalid
	}
	scope, e := r.Access.Scope(ctx, ns, name, uid)
	if e != nil {
		if errors.Is(e, ErrForbidden) {
			return nil, ErrForbidden
		}
		if errors.Is(e, ErrNotFound) {
			return nil, ErrNotFound
		}
		return nil, ErrUnavailable
	}
	if scope == "" {
		return nil, ErrForbidden
	}
	scope = digest([]byte(r.Cluster + "/" + scope))
	size := 20
	if q.Get("page_size") != "" {
		size, e = strconv.Atoi(q.Get("page_size"))
		if e != nil || size < 1 || size > 100 {
			return nil, ErrInvalid
		}
	}
	c := cursor{}
	if raw := q.Get("cursor"); raw != "" {
		if len(raw) > 2048 {
			return nil, ErrInvalid
		}
		b, e := base64.RawURLEncoding.Strict().DecodeString(raw)
		if e != nil || json.Unmarshal(b, &c) != nil || c.Scope != scope || c.UID != uid || c.Namespace != ns || c.Name != name || len(c.Revision) != 64 {
			return nil, ErrInvalid
		}
		if _, e = time.Parse(time.RFC3339Nano, c.Time); e != nil {
			return nil, ErrInvalid
		}
	}
	live := LiveState{State: "unknown"}
	if r.Live != nil {
		if observed, err := r.Live.Current(ctx, ns, name); err == nil {
			live = observed
		}
	}
	live.Namespace = ns
	live.Name = name
	if (live.State == "present" || live.State == "deleting") && live.Version == "" {
		live.State = "unknown"
	}
	if live.State == "present" || live.State == "deleting" {
		if live.UID != uid {
			live.State = "replaced"
			live.Version = ""
		}
	}
	switch live.State {
	case "present", "deleting", "deleted", "replaced", "unknown":
	default:
		return nil, ErrUnavailable
	}
	tx, e := r.DB.BeginTx(ctx, &sql.TxOptions{Isolation: sql.LevelRepeatableRead, ReadOnly: true})
	if e != nil {
		return nil, ErrUnavailable
	}
	defer tx.Rollback()
	var t time.Time
	if e = tx.QueryRowContext(ctx, "SELECT UTC_TIMESTAMP(6)").Scan(&t); e != nil {
		return nil, ErrUnavailable
	}
	var actualNS, actualName string
	var active sql.NullString
	e = tx.QueryRowContext(ctx, `SELECT l.namespace,l.name,p.revision FROM release_links l LEFT JOIN publications p ON p.cluster_id=l.cluster_id AND p.publication_id=l.active_id WHERE l.cluster_id=? AND l.cr_uid=?`, r.Cluster, uid).Scan(&actualNS, &actualName, &active)
	if errors.Is(e, sql.ErrNoRows) {
		return nil, ErrNotFound
	}
	if e != nil {
		return nil, ErrUnavailable
	}
	if actualNS != ns || actualName != name {
		return nil, ErrNotFound
	}
	var missing int
	if e = tx.QueryRowContext(ctx, `SELECT COUNT(*) FROM release_revisions v LEFT JOIN retained_release_snapshots h ON h.cluster_id=v.cluster_id AND h.cr_uid=v.cr_uid AND h.revision=v.revision WHERE v.cluster_id=? AND v.cr_uid=? AND h.revision IS NULL`, r.Cluster, uid).Scan(&missing); e != nil {
		return nil, ErrUnavailable
	}
	if missing > 0 {
		return nil, ErrUnavailable
	}
	query := `SELECT revision,cr_uid,namespace,name,generation,model_alias,source_type,spec_bytes,spec_sha256,created_at,snapshot_state FROM retained_release_snapshots WHERE cluster_id=? AND cr_uid=?`
	args := []any{r.Cluster, uid}
	if c.Revision != "" {
		stamp, _ := time.Parse(time.RFC3339Nano, c.Time)
		query += " AND (created_at<? OR (created_at=? AND revision<?))"
		args = append(args, stamp, stamp, c.Revision)
	}
	query += " ORDER BY created_at DESC,revision DESC LIMIT ?"
	args = append(args, size+1)
	records, e := tx.QueryContext(ctx, query, args...)
	if e != nil {
		return nil, ErrUnavailable
	}
	rows := []row{}
	for records.Next() {
		var v row
		var b []byte
		var hash string
		if e = records.Scan(&v.Revision, &v.UID, &v.Namespace, &v.Name, &v.Generation, &v.Alias, &v.Source, &b, &hash, &v.Created, &v.State); e != nil {
			records.Close()
			return nil, ErrUnavailable
		}
		if v.Namespace != ns || v.Name != name || digest(b) != hash || json.Unmarshal(b, &v.Spec) != nil || v.Spec.Source.Type != v.Source || v.Spec.ModelAlias != v.Alias {
			records.Close()
			return nil, ErrUnavailable
		}
		rows = append(rows, v)
	}
	e = records.Err()
	records.Close()
	if e != nil {
		return nil, ErrUnavailable
	}
	_ = tx.Rollback() // no K8s/registry RPC while a database transaction is open.
	if len(rows) == 0 && c.Revision == "" {
		return nil, ErrNotFound
	}
	var next any
	if len(rows) > size {
		rows = rows[:size]
		last := rows[len(rows)-1]
		b, _ := json.Marshal(cursor{scope, ns, name, uid, last.Revision, last.Created.Format(time.RFC3339Nano)})
		next = base64.RawURLEncoding.EncodeToString(b)
	}
	data := []any{}
	for _, v := range rows {
		evaluation := Evaluation{State: "unknown", Reasons: []string{"state_unavailable"}}
		switch {
		case v.State == "pruning":
			evaluation = Evaluation{"blocked", []string{"snapshot_pruning"}}
		case v.State != "retained":
			evaluation = Evaluation{"blocked", []string{"snapshot_missing"}}
		case live.State == "deleted":
			evaluation = Evaluation{"blocked", []string{"cr_deleted"}}
		case live.State == "replaced":
			evaluation = Evaluation{"blocked", []string{"cr_replaced"}}
		case live.State == "deleting":
			evaluation = Evaluation{"blocked", []string{"cr_deleting"}}
		case live.State == "present" && live.SourceType != v.Source:
			evaluation = Evaluation{"blocked", []string{"source_incompatible"}}
		case live.State == "present" && r.Evaluator != nil:
			if value, err := r.Evaluator.Evaluate(ctx, v.Spec, live); err == nil {
				evaluation = value
			}
		}
		if !validEvaluation(evaluation, live) {
			return nil, ErrUnavailable
		}
		var upstream, runtime any
		if x := v.Spec.Source.ExternalAPI; x != nil {
			upstream = x.UpstreamModel
		}
		if x := v.Spec.Source.SelfHosted; x != nil {
			runtime = x.RuntimeProfileRef
		}
		var rv any
		live.Namespace = ns
		live.Name = name
		if (live.State == "present" || live.State == "deleting") && live.Version == "" {
			live.State = "unknown"
		}
		if live.State == "present" || live.State == "deleting" {
			rv = live.Version
		}
		isActive := active.Valid && active.String == v.Revision
		if live.State == "deleted" || live.State == "replaced" {
			isActive = false
		}
		data = append(data, map[string]any{"revision": v.Revision, "cr_uid": uid, "created_at": v.Created.Format(time.RFC3339Nano), "generation": v.Generation, "source_type": v.Source, "model_alias": v.Alias, "is_active": isActive, "snapshot_state": v.State, "summary": map[string]any{"upstream_model": upstream, "runtime_profile_ref": runtime, "capability_ref": v.Spec.BusinessRefs.CapabilityProfileRef, "price_ref": v.Spec.BusinessRefs.PricePolicyRef}, "rollback_eligibility": map[string]any{"state": evaluation.State, "reason_codes": evaluation.Reasons, "checked_at": time.Now().UTC().Format(time.RFC3339Nano), "evaluated_resource_version": rv}})
	}
	var rv any
	live.Namespace = ns
	live.Name = name
	if (live.State == "present" || live.State == "deleting") && live.Version == "" {
		live.State = "unknown"
	}
	if live.State == "present" || live.State == "deleting" {
		rv = live.Version
	}
	return map[string]any{"requested_cr_uid": uid, "resource_state": live.State, "resource_version": rv, "data": data, "next_cursor": next, "generated_at": t.Format(time.RFC3339Nano)}, nil
}
func validEvaluation(v Evaluation, live LiveState) bool {
	allowed := map[string]bool{}
	for _, s := range []string{"snapshot_missing", "snapshot_pruning", "reference_unapproved", "reference_expired", "pricing_unavailable", "source_incompatible", "cr_deleting", "cr_deleted", "cr_replaced", "state_unavailable", "lifecycle_blocked"} {
		allowed[s] = true
	}
	seen := map[string]bool{}
	for _, s := range v.Reasons {
		if !allowed[s] || seen[s] {
			return false
		}
		seen[s] = true
	}
	switch v.State {
	case "eligible":
		return len(v.Reasons) == 0 && live.State == "present" && live.Version != ""
	case "blocked":
		return len(v.Reasons) > 0
	case "unknown":
		return seen["state_unavailable"]
	}
	return false
}
func validUID(v string) bool { u, e := uuid.Parse(v); return e == nil && u.String() == v }
