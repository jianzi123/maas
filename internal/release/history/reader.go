// Package history reads retained release facts. It never authorizes inference.
package history

import (
	"context"
	"crypto/hmac"
	"crypto/sha256"
	"database/sql"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"errors"
	"github.com/google/uuid"
	"strings"

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
	Domain(context.Context, string) bool
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
	Evaluate(context.Context, string, string, LiveState) (Evaluation, error)
}
type Reader struct {
	DB        *sql.DB
	PayloadDB *sql.DB
	CursorKey []byte
	Cluster   string
	Access    Access
	Live      Live
	Evaluator Evaluator
}
type row struct {
	Revision, UID, Namespace, Name, Alias, Source, State string
	Generation                                           int64
	Created                                              time.Time
	Summary                                              map[string]any
}
type cursor struct {
	Scope, Namespace, Name, UID, Revision, Time string
	PageSize                                    int
	Catalog, Watermark                          int64
}

func digest(b []byte) string { s := sha256.Sum256(b); return hex.EncodeToString(s[:]) }
func (r *Reader) ReadRevisions(ctx context.Context, ns, name string, q url.Values) (map[string]any, error) {
	if r.DB == nil || r.Access == nil || r.Cluster == "" || len(r.CursorKey) < 32 {
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
		parts := strings.Split(raw, ".")
		if len(parts) != 2 {
			return nil, ErrInvalid
		}
		b, e := base64.RawURLEncoding.Strict().DecodeString(parts[0])
		signature, signatureErr := base64.RawURLEncoding.Strict().DecodeString(parts[1])
		mac := hmac.New(sha256.New, r.CursorKey)
		mac.Write(b)
		if signatureErr != nil || !hmac.Equal(mac.Sum(nil), signature) {
			return nil, ErrInvalid
		}
		if e != nil || json.Unmarshal(b, &c) != nil || c.Scope != scope || c.UID != uid || c.Namespace != ns || c.Name != name || len(c.Revision) != 64 || c.PageSize != size {
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
	var domain sql.NullString
	var watermark, catalog sql.NullInt64
	var active sql.NullString
	e = tx.QueryRowContext(ctx, `SELECT d.namespace,d.name,d.authorization_domain,d.history_seq,d.catalog_version,p.revision FROM release_history_directory d LEFT JOIN release_links l ON l.cluster_id=d.cluster_id AND l.cr_uid=d.cr_uid LEFT JOIN publications p ON p.cluster_id=l.cluster_id AND p.publication_id=l.active_id WHERE d.cluster_id=? AND d.cr_uid=?`, r.Cluster, uid).Scan(&actualNS, &actualName, &domain, &watermark, &catalog, &active)
	if errors.Is(e, sql.ErrNoRows) {
		return nil, ErrNotFound
	}
	if e != nil {
		return nil, ErrUnavailable
	}
	if actualNS != ns || actualName != name {
		return nil, ErrNotFound
	}
	if !domain.Valid || !watermark.Valid || !catalog.Valid {
		return nil, ErrUnavailable
	}
	if !r.Access.Domain(ctx, domain.String) {
		return nil, ErrNotFound
	}
	if c.Revision != "" {
		if c.Catalog != catalog.Int64 || c.Watermark > watermark.Int64 {
			return nil, ErrInvalid
		}
	} else {
		c.Catalog = catalog.Int64
		c.Watermark = watermark.Int64
	}
	var missing int
	if e = tx.QueryRowContext(ctx, `SELECT COUNT(*) FROM release_history_completeness WHERE cluster_id=? AND cr_uid=?`, r.Cluster, uid).Scan(&missing); e != nil {
		return nil, ErrUnavailable
	}
	if missing > 0 {
		return nil, ErrUnavailable
	}
	query := `SELECT revision,cr_uid,namespace,name,generation,model_alias,source_type,summary_bytes,summary_sha256,created_at,snapshot_state FROM release_history_projection WHERE cluster_id=? AND cr_uid=? AND history_seq<=?`
	args := []any{r.Cluster, uid, c.Watermark}
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
		if v.Namespace != ns || v.Name != name || digest(b) != hash || json.Unmarshal(b, &v.Summary) != nil {
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
		b, _ := json.Marshal(cursor{Scope: scope, Namespace: ns, Name: name, UID: uid, Revision: last.Revision, Time: last.Created.Format(time.RFC3339Nano), PageSize: size, Catalog: c.Catalog, Watermark: c.Watermark})
		mac := hmac.New(sha256.New, r.CursorKey)
		mac.Write(b)
		next = base64.RawURLEncoding.EncodeToString(b) + "." + base64.RawURLEncoding.EncodeToString(mac.Sum(nil))
	}
	// A bounded authoritative reread prevents mixing another UID/RV's eligibility.
	if r.Live != nil && (live.State == "present" || live.State == "deleting") {
		latest, err := r.Live.Current(ctx, ns, name)
		if err != nil {
			live = LiveState{State: "unknown"}
		} else if latest.UID != live.UID || latest.Version != live.Version || latest.State != live.State {
			again, secondErr := r.Live.Current(ctx, ns, name)
			if secondErr != nil || again.UID != latest.UID || again.Version != latest.Version || again.State != latest.State {
				live = LiveState{State: "unknown"}
			} else {
				live = again
				if live.UID != uid && (live.State == "present" || live.State == "deleting") {
					live.State = "replaced"
				}
			}
		}
		live.Namespace = ns
		live.Name = name
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
			if value, err := r.Evaluator.Evaluate(ctx, uid, v.Revision, live); err == nil {
				evaluation = value
			}
		}
		if !validEvaluation(evaluation, live) {
			return nil, ErrUnavailable
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
		data = append(data, map[string]any{"revision": v.Revision, "cr_uid": uid, "created_at": v.Created.Format(time.RFC3339Nano), "generation": v.Generation, "source_type": v.Source, "model_alias": v.Alias, "is_active": isActive, "snapshot_state": v.State, "summary": v.Summary, "rollback_eligibility": map[string]any{"state": evaluation.State, "reason_codes": evaluation.Reasons, "checked_at": time.Now().UTC().Format(time.RFC3339Nano), "evaluated_resource_version": rv}})
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
