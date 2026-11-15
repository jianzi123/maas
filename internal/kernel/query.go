package kernel

import (
	"context"
	"database/sql"
	"encoding/base64"
	"encoding/json"
	"errors"
	"net/url"
	"strconv"
	"strings"
	"time"
)

type pageCursor struct {
	Filter string `json:"filter"`
	Time   string `json:"time"`
	ID     string `json:"id"`
}

func encodeCursor(c pageCursor) string {
	b, _ := json.Marshal(c)
	return base64.RawURLEncoding.EncodeToString(b)
}
func decodeCursor(v, filter string) (pageCursor, error) {
	var c pageCursor
	if v == "" {
		return c, nil
	}
	if len(v) > 2048 {
		return c, ErrPolicy
	}
	b, e := base64.RawURLEncoding.Strict().DecodeString(v)
	if e != nil || json.Unmarshal(b, &c) != nil || c.Filter != filter || !validUUID(c.ID) {
		return c, ErrPolicy
	}
	if _, e = time.Parse(time.RFC3339Nano, c.Time); e != nil {
		return c, ErrPolicy
	}
	return c, nil
}
func pageSize(q url.Values) (int, error) {
	n := 20
	if q.Get("page_size") != "" {
		var e error
		n, e = strconv.Atoi(q.Get("page_size"))
		if e != nil {
			return 0, ErrPolicy
		}
	}
	if n < 1 || n > 100 {
		return 0, ErrPolicy
	}
	return n, nil
}
func (s *Store) ListKeys(ctx context.Context, q url.Values) (map[string]any, error) {
	n, e := pageSize(q)
	if e != nil {
		return nil, e
	}
	c, e := decodeCursor(q.Get("cursor"), "keys")
	if e != nil {
		return nil, e
	}
	out := map[string]any{}
	e = s.readView(ctx, func(tx *sql.Tx, t time.Time) error {
		var legacy int
		if e := tx.QueryRowContext(ctx, "SELECT COUNT(*) FROM platform_keys k LEFT JOIN key_metadata m ON m.key_id=k.key_id WHERE m.key_id IS NULL").Scan(&legacy); e != nil {
			return e
		}
		if legacy > 0 {
			return ErrUnavailable
		}
		query := "SELECT key_id,created_at FROM key_metadata WHERE purpose='serving'"
		args := []any{}
		if c.ID != "" {
			stamp, _ := time.Parse(time.RFC3339Nano, c.Time)
			query += " AND (created_at<? OR (created_at=? AND key_id<?))"
			args = append(args, stamp, stamp, c.ID)
		}
		query += " ORDER BY created_at DESC,key_id DESC LIMIT ?"
		args = append(args, n+1)
		rows, e := tx.QueryContext(ctx, query, args...)
		if e != nil {
			return e
		}
		type entry struct {
			id string
			t  time.Time
		}
		ids := []entry{}
		for rows.Next() {
			var v entry
			if e = rows.Scan(&v.id, &v.t); e != nil {
				rows.Close()
				return e
			}
			ids = append(ids, v)
		}
		e = rows.Err()
		rows.Close()
		if e != nil {
			return e
		}
		var cursor any
		if len(ids) > n {
			ids = ids[:n]
			v := ids[len(ids)-1]
			cursor = encodeCursor(pageCursor{"keys", v.t.Format(time.RFC3339Nano), v.id})
		}
		data := []any{}
		for _, v := range ids {
			k, e := s.keyView(ctx, tx, v.id, t)
			if e != nil {
				return e
			}
			data = append(data, k)
		}
		out = map[string]any{"data": data, "next_cursor": cursor, "generated_at": t.Format(time.RFC3339Nano), "data_complete": true}
		return nil
	})
	return out, e
}
func requestProjection(snap Snapshot, state string, event map[string]any) map[string]any {
	p := snap.Input.Profile
	in := snap.Input
	purpose := in.Purpose
	if purpose == "" {
		purpose = "serving"
	}
	out := map[string]any{"request_id": in.RequestID, "key_id": in.KeyID, "model_alias": p.Alias, "upstream_model": p.UpstreamModel, "source_id": p.SourceID, "source_type": p.SourceType, "config_revision": p.ConfigRevision, "received_at": in.Received.Format(time.RFC3339Nano), "admitted_at": snap.Admitted.Format(time.RFC3339Nano), "finished_at": nil, "quota_date": snap.Admitted.Format("2006-01-02"), "status": state, "submission_state": "unknown", "quota_consumed": 1, "error_code": nil, "duration_ms": nil, "first_chunk_ms": nil, "usage": unavailableUsage("not_provided"), "metering_state": "incomplete", "reservation_plan": in.Plan, "budget_accounting": nil, "rate_witness": map[string]any{"permit_id": snap.Rate.ID, "rate_epoch": decimal(snap.Rate.Epoch), "policy_id": snap.Rate.PolicyID, "policy_revision": snap.Rate.Revision, "windows": snap.Rate.Windows}, "invocation_binding": map[string]any{"model_release_uid": p.CRUID, "model_release_namespace": p.Namespace, "model_release_name": p.Name, "model_release_generation": p.Binding.Generation, "release_revision": p.Binding.Revision, "publication_id": p.Binding.PublicationID, "activation_epoch": p.Binding.Epoch, "route_binding_sha256": p.RouteDigest, "admission_purpose": purpose, "price_snapshot_id": in.Plan.PriceID, "price_version": in.Plan.PriceVersion}}
	if event != nil {
		for _, k := range []string{"submission_state", "quota_consumed", "error_code", "duration_ms", "first_chunk_ms", "usage", "metering_state", "budget_accounting", "rate_witness", "invocation_binding"} {
			out[k] = event[k]
		}
		out["finished_at"] = event["observed_at"]
	}
	return out
}
func (s *Store) lookup(ctx context.Context, tx *sql.Tx, id string, t time.Time) (map[string]any, error) {
	if !validUUID(id) {
		return nil, ErrPolicy
	}
	capacity := map[string]any{"state": "unknown", "checked_at": t.Format(time.RFC3339Nano), "data_source": "none", "release_reason": nil}
	lookup := map[string]any{"request_id": id, "resolution": "unknown", "evidence_source": "none", "checked_at": t.Format(time.RFC3339Nano), "reason": "no_authoritative_record", "rejection_code": nil, "capacity": capacity}
	data := []any{}
	var b, eventBytes []byte
	var state string
	e := tx.QueryRowContext(ctx, `SELECT r.snapshot_json,r.result,e.event_json FROM generation_requests r LEFT JOIN usage_events e ON e.event_id=r.terminal_event_id WHERE r.request_id=?`, id).Scan(&b, &state, &eventBytes)
	if e != nil && !errors.Is(e, sql.ErrNoRows) {
		return nil, e
	}
	found := e == nil
	if found {
		if state != "in_progress" && len(eventBytes) == 0 {
			return nil, ErrUnavailable
		}
		var snap Snapshot
		if json.Unmarshal(b, &snap) != nil || snap.Input.RequestID != id {
			return nil, ErrUnavailable
		}
		var event map[string]any
		if len(eventBytes) > 0 {
			d := json.NewDecoder(strings.NewReader(string(eventBytes)))
			d.UseNumber()
			if d.Decode(&event) != nil {
				return nil, ErrUnavailable
			}
			if event["request_id"] != id {
				return nil, ErrUnavailable
			}
		}
		data = append(data, requestProjection(snap, state, event))
		lookup["resolution"] = "recorded"
		lookup["evidence_source"] = "generation_request"
		lookup["reason"] = nil
		var reason string
		e = tx.QueryRowContext(ctx, "SELECT reason FROM slot_release_log WHERE slot_id=? AND allocation_fence=? AND request_id=?", snap.SlotID, snap.AllocationFence, id).Scan(&reason)
		if e == nil {
			capacity["state"] = "released"
			capacity["data_source"] = "release_log"
			capacity["release_reason"] = reason
		} else if errors.Is(e, sql.ErrNoRows) {
			var slotState string
			e = tx.QueryRowContext(ctx, "SELECT state FROM concurrency_slots WHERE slot_id=? AND allocation_fence=? AND request_id=?", snap.SlotID, snap.AllocationFence, id).Scan(&slotState)
			if e == nil && (slotState == "HELD" || slotState == "QUARANTINED") {
				capacity["state"] = strings.ToLower(slotState)
				capacity["data_source"] = "current_allocation"
			} else if e != nil && !errors.Is(e, sql.ErrNoRows) {
				return nil, e
			}
		} else {
			return nil, e
		}
	}
	return map[string]any{"data": data, "next_cursor": nil, "generated_at": t.Format(time.RFC3339Nano), "data_complete": found, "lookup": lookup}, nil
}
func (s *Store) LookupRequest(ctx context.Context, id string) (map[string]any, error) {
	var out map[string]any
	e := s.readView(ctx, func(tx *sql.Tx, t time.Time) error { var e error; out, e = s.lookup(ctx, tx, id, t); return e })
	return out, e
}
func requestFilter(q url.Values, t time.Time) (string, []any, error) {
	start := time.Date(t.Year(), t.Month(), t.Day(), 0, 0, 0, 0, time.UTC)
	end := start
	var e error
	if q.Get("date_from") != "" {
		start, e = time.Parse("2006-01-02", q.Get("date_from"))
		if e != nil {
			return "", nil, ErrPolicy
		}
	}
	if q.Get("date_to") != "" {
		end, e = time.Parse("2006-01-02", q.Get("date_to"))
		if e != nil {
			return "", nil, ErrPolicy
		}
	}
	if end.Before(start) || end.Sub(start) > 30*24*time.Hour {
		return "", nil, ErrPolicy
	}
	query := admissionTimeSQL + ">=? AND " + admissionTimeSQL + "<?"
	args := []any{start, end.AddDate(0, 0, 1)}
	for _, f := range []struct {
		name, col string
		uuid      bool
	}{{"key_id", "r.key_id", true}, {"source_id", "JSON_UNQUOTE(JSON_EXTRACT(r.snapshot_json,'$.Input.Profile.SourceID'))", true}, {"model_alias", "JSON_UNQUOTE(JSON_EXTRACT(r.snapshot_json,'$.Input.Profile.Alias'))", false}, {"status", "r.result", false}} {
		if v := q.Get(f.name); v != "" {
			if f.uuid && !validUUID(v) {
				return "", nil, ErrPolicy
			}
			query += " AND " + f.col + "=?"
			args = append(args, v)
		}
	}
	return query, args, nil
}
func (s *Store) ListRequests(ctx context.Context, q url.Values) (map[string]any, error) {
	if id, ok := q["request_id"]; ok {
		if len(q) != 1 || len(id) != 1 || !validUUID(id[0]) {
			return nil, ErrPolicy
		}
		return s.LookupRequest(ctx, id[0])
	}
	n, e := pageSize(q)
	if e != nil {
		return nil, e
	}
	filter := q.Encode()
	copyQ := url.Values{}
	for k, v := range q {
		if k != "cursor" {
			copyQ[k] = v
		}
	}
	filter = hash(copyQ.Encode())
	c, e := decodeCursor(q.Get("cursor"), filter)
	if e != nil {
		return nil, e
	}
	out := map[string]any{}
	e = s.readView(ctx, func(tx *sql.Tx, t time.Time) error {
		where, args, e := requestFilter(q, t)
		if e != nil {
			return e
		}
		admitted := admissionTimeSQL
		if c.ID != "" {
			where += " AND (" + admitted + "<? OR (" + admitted + "=? AND r.request_id<?))"
			stamp, _ := time.Parse(time.RFC3339Nano, c.Time)
			args = append(args, stamp, stamp, c.ID)
		}
		args = append(args, n+1)
		rows, e := tx.QueryContext(ctx, "SELECT r.request_id,"+admitted+" FROM generation_requests r WHERE "+where+" ORDER BY "+admitted+" DESC,r.request_id DESC LIMIT ?", args...)
		if e != nil {
			return e
		}
		entries := []pageCursor{}
		for rows.Next() {
			v := pageCursor{Filter: filter}
			if e = rows.Scan(&v.ID, &v.Time); e != nil {
				rows.Close()
				return e
			}
			entries = append(entries, v)
		}
		e = rows.Err()
		rows.Close()
		if e != nil {
			return e
		}
		var cursor any
		if len(entries) > n {
			entries = entries[:n]
			cursor = encodeCursor(entries[len(entries)-1])
		}
		data := []any{}
		for _, v := range entries {
			page, e := s.lookup(ctx, tx, v.ID, t)
			if e != nil {
				return e
			}
			data = append(data, page["data"].([]any)[0])
		}
		out = map[string]any{"data": data, "next_cursor": cursor, "generated_at": t.Format(time.RFC3339Nano), "data_complete": true}
		return nil
	})
	return out, e
}

const admissionTimeSQL = "CAST(REPLACE(REPLACE(JSON_UNQUOTE(JSON_EXTRACT(r.snapshot_json,'$.Admitted')),'T',' '),'Z','') AS DATETIME(6))"
