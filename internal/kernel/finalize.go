package kernel

import (
	"context"
	"database/sql"
	"encoding/json"
	"errors"
	"time"

	"github.com/google/uuid"
	"github.com/jianzi123/maas/internal/protocol"
)

type settlement struct {
	Reserved string `json:"reserved"`
	Known    string `json:"known_used"`
	Held     string `json:"unknown_held"`
	Released string `json:"released"`
	Overrun  string `json:"overrun"`
	State    string `json:"state"`
}

func settle(reserved string, actual *string, noSend bool) (settlement, error) {
	out := settlement{Reserved: reserved, Known: "0", Held: "0", Released: "0", Overrun: "0", State: "known"}
	if noSend {
		out.Released = reserved
		out.State = "released"
		return out, nil
	}
	if actual == nil {
		out.Held = reserved
		out.State = "held"
		return out, nil
	}
	out.Known = *actual
	x, e := number(*actual)
	if e != nil {
		return out, e
	}
	r, e := number(reserved)
	if e != nil {
		return out, e
	}
	if x.Cmp(r) > 0 {
		out.Overrun, _ = subtract(*actual, reserved)
		out.State = "anomalous"
	} else {
		out.Released, _ = subtract(reserved, *actual)
	}
	return out, nil
}
func actualUsage(u Usage, p *Price) (token, cost *string, basis string, err error) {
	basis = "unavailable"
	for _, v := range []*int64{u.Input, u.Output, u.Total, u.Cached, u.Reasoning} {
		if v != nil && (*v < 0 || *v > maxCounter) {
			return nil, nil, basis, ErrConflict
		}
	}
	if u.Input != nil && u.Output != nil {
		if *u.Input > maxCounter-*u.Output {
			return nil, nil, basis, ErrConflict
		}
		sum := *u.Input + *u.Output
		if u.Total != nil && *u.Total != sum {
			return nil, nil, basis, ErrConflict
		}
		token = ptr(decimal(sum))
		basis = "component_sum"
	}
	if u.Total != nil {
		token = ptr(decimal(*u.Total))
		basis = "upstream_total"
	}
	if u.Cached != nil && (u.Input == nil || *u.Cached > *u.Input) {
		return nil, nil, basis, ErrConflict
	}
	if u.Reasoning != nil && (u.Output == nil || *u.Reasoning > *u.Output) {
		return nil, nil, basis, ErrConflict
	}
	if p == nil || u.Input == nil || u.Output == nil {
		return token, nil, basis, nil
	}
	var cached, reason int64
	if u.Cached == nil {
		if p.Input != p.Cached {
			return token, nil, basis, nil
		}
	} else {
		cached = *u.Cached
	}
	if u.Reasoning == nil {
		if p.Output != p.Reasoning {
			return token, nil, basis, nil
		}
	} else {
		reason = *u.Reasoning
	}
	v, e := priceCost(p, [4]int64{*u.Input - cached, cached, *u.Output - reason, reason})
	if e != nil {
		return token, nil, basis, e
	}
	return token, &v, basis, nil
}
func (s *Store) closure(ctx context.Context, tx *sql.Tx, snap Snapshot, ref string) (Closure, bool, error) {
	if ref == "" {
		return Closure{}, false, nil
	}
	if s.proofs == nil {
		return Closure{}, false, ErrUnavailable
	}
	c, e := s.proofs.Closure(ctx, tx, snap, ref)
	if e != nil {
		return c, false, e
	}
	t, e := now(ctx, tx)
	if e != nil {
		return c, false, e
	}
	p := snap.Input.Profile
	if !validUUID(c.ID) || c.ID != ref || c.RequestID != snap.Input.RequestID || c.TicketHash != snap.Input.TicketHash || c.GatewayInstance != p.GatewayInstance || c.GatewayEpoch != p.GatewayEpoch || c.SlotID != snap.SlotID || c.AllocationFence != snap.AllocationFence || !c.Sealed || c.ActiveStreams != 0 || c.Observed.Before(snap.Input.Received) || c.Observed.After(t) {
		return c, false, ErrConflict
	}
	if c.Kind == "no_upstream_attempt" && c.Attempts == 0 {
		return c, true, nil
	}
	if c.Kind == "upstream_transport_closed" && c.Attempts == 1 {
		return c, true, nil
	}
	return c, false, ErrConflict
}
func (s *Store) lockRequest(ctx context.Context, tx *sql.Tx, id string) (Snapshot, string, string, error) {
	var snap Snapshot
	var b []byte
	var state, owner string
	var fence int64
	var event sql.NullString
	e := tx.QueryRowContext(ctx, `SELECT snapshot_json,result,owner_id,owner_fence,terminal_event_id FROM generation_requests WHERE request_id=? FOR UPDATE NOWAIT`, id).Scan(&b, &state, &owner, &fence, &event)
	if e != nil {
		return snap, state, event.String, e
	}
	if e = json.Unmarshal(b, &snap); e != nil {
		return snap, state, event.String, e
	}
	snap.Input.Owner = owner
	snap.OwnerFence = fence
	return snap, state, event.String, nil
}
func (s *Store) releaseSlot(ctx context.Context, tx *sql.Tx, snap Snapshot, actor string, c Closure) error {
	var request string
	var fence, version int64
	var state string
	e := tx.QueryRowContext(ctx, `SELECT COALESCE(request_id,''),allocation_fence,row_version,state FROM concurrency_slots WHERE slot_id=? FOR UPDATE NOWAIT`, snap.SlotID).Scan(&request, &fence, &version, &state)
	if e != nil {
		return e
	}
	var old string
	e = tx.QueryRowContext(ctx, "SELECT request_id FROM slot_release_log WHERE slot_id=? AND allocation_fence=?", snap.SlotID, snap.AllocationFence).Scan(&old)
	if e == nil {
		if old == snap.Input.RequestID {
			return nil
		}
		return ErrConflict
	}
	if !errors.Is(e, sql.ErrNoRows) {
		return e
	}
	if request != snap.Input.RequestID || fence != snap.AllocationFence || (state != "HELD" && state != "QUARANTINED") || version >= maxCounter {
		return ErrConflict
	}
	result, e := tx.ExecContext(ctx, `UPDATE concurrency_slots SET state='FREE',request_id=NULL,publication_id=NULL,hard_deadline=NULL,release_not_before=NULL,quarantine_reason=NULL,row_version=row_version+1 WHERE slot_id=? AND allocation_fence=? AND row_version=? AND request_id=? AND state IN ('HELD','QUARANTINED')`, snap.SlotID, fence, version, request)
	if e != nil {
		return e
	}
	n, e := result.RowsAffected()
	if e != nil || n != 1 {
		return ErrConflict
	}
	_, e = tx.ExecContext(ctx, `INSERT INTO slot_release_log(slot_id,allocation_fence,request_id,reason,evidence_ref,actor_id,hard_deadline) VALUES(?,?,?,'transport_closed',?,?,?)`, snap.SlotID, fence, request, c.ID, actor, snap.Input.Deadline)
	return e
}
func (s *Store) Finalize(ctx context.Context, f Final) error {
	if !validUUID(f.EventID) || !validUUID(f.RequestID) || !validUUID(f.Owner) {
		return ErrConflict
	}
	if f.Result != "succeeded" && f.Result != "failed" && f.Result != "cancelled" && f.Result != "timed_out" && f.Result != "interrupted" {
		return ErrConflict
	}
	before, _, e := s.ReadRequest(ctx, f.RequestID)
	if e != nil {
		return e
	}
	return s.tx(ctx, func(tx *sql.Tx) error {
		if _, e := s.guard(ctx, tx, "FOR UPDATE NOWAIT"); e != nil {
			return e
		}
		var key string
		if e := tx.QueryRowContext(ctx, "SELECT key_id FROM platform_keys WHERE key_id=? FOR UPDATE NOWAIT", before.Input.KeyID).Scan(&key); e != nil {
			return e
		}
		counters, e := s.counters(ctx, tx, key, before.WindowStart, before.WindowEnd)
		if e != nil {
			return e
		}
		snap, state, oldEvent, e := s.lockRequest(ctx, tx, f.RequestID)
		if e != nil {
			return e
		}
		var eventRequest, inputHash string
		e = tx.QueryRowContext(ctx, "SELECT request_id,input_sha256 FROM usage_events WHERE event_id=?", f.EventID).Scan(&eventRequest, &inputHash)
		if e == nil {
			if eventRequest == f.RequestID && inputHash == hash(f) {
				return nil
			}
			return ErrConflict
		}
		if !errors.Is(e, sql.ErrNoRows) {
			return e
		}
		if state != "in_progress" || oldEvent != "" || snap.Input.Owner != f.Owner || snap.OwnerFence != f.OwnerFence {
			return ErrConflict
		}
		observed, e := now(ctx, tx)
		if e != nil {
			return e
		}
		if f.FirstChunkMS != nil && (*f.FirstChunkMS < 0 || *f.FirstChunkMS > observed.Sub(snap.Input.Received).Milliseconds()) {
			return ErrConflict
		}
		closure, safe, e := s.closure(ctx, tx, snap, f.EvidenceRef)
		if e != nil {
			return e
		}
		noSend := safe && closure.Kind == "no_upstream_attempt"
		token, cost, basis, e := actualUsage(f.Usage, snap.Input.Profile.Price)
		if e != nil {
			return e
		}
		if noSend {
			if f.Submitted || f.Result == "succeeded" || token != nil {
				return ErrConflict
			}
			token = ptr("0")
			cost = ptr("0")
			basis = "not_submitted"
		}
		requestActual := "1"
		if noSend {
			requestActual = "0"
		}
		req, e := settle("1", &requestActual, noSend)
		if e != nil {
			return e
		}
		var tok, mon *settlement
		if snap.Policy.Limits.Tokens != nil {
			v, e := settle(reserved(snap.Input.Plan.Tokens), token, noSend)
			if e != nil {
				return e
			}
			tok = &v
		}
		if snap.Policy.Limits.Money != nil {
			v, e := settle(reserved(snap.Input.Plan.Money), cost, noSend)
			if e != nil {
				return e
			}
			mon = &v
		}
		breached := (tok != nil && tok.State == "anomalous") || (mon != nil && mon.State == "anomalous")
		deltas := map[string]*settlement{"requests": &req, "tokens": tok, "money": mon}
		for _, dim := range []string{"money", "requests", "tokens"} {
			v := deltas[dim]
			if v == nil {
				continue
			}
			c := counters[dim]
			c.Reserved, e = subtract(c.Reserved, v.Reserved)
			if e != nil {
				return e
			}
			c.Known, e = add(c.Known, v.Known)
			if e != nil {
				return e
			}
			c.Held, e = add(c.Held, v.Held)
			if e != nil {
				return e
			}
			if e = s.writeCounter(ctx, tx, key, snap.WindowStart, dim, c); e != nil {
				return e
			}
		}
		if breached {
			if _, e = tx.ExecContext(ctx, "UPDATE platform_keys SET blocked=TRUE WHERE key_id=?", key); e != nil {
				return e
			}
			if _, e = tx.ExecContext(ctx, `UPDATE invocation_profiles SET blocked=TRUE WHERE JSON_UNQUOTE(JSON_EXTRACT(snapshot_json,'$.CapabilityRevision'))=?`, snap.Input.Profile.CapabilityRevision); e != nil {
				return e
			}
		}
		event := buildEvent(snap, f, observed, noSend, token, cost, basis, req, tok, mon, breached)
		if e = protocol.Validate("Terminal", event); e != nil {
			return ErrConflict
		}
		data, _ := json.Marshal(event)
		if _, e = tx.ExecContext(ctx, `INSERT INTO usage_events(event_id,request_id,event_type,input_sha256,event_json) VALUES(?,?,'request.finalized',?,?)`, f.EventID, f.RequestID, hash(f), data); e != nil {
			return e
		}
		if snap.Input.Purpose == "validation" && event["result"] == "succeeded" {
			if _, e = tx.ExecContext(ctx, `INSERT INTO validation_receipts(intent_id,request_id,event_id,publication_id,profile_sha256,finished_at) SELECT intent_id,request_id,?,publication_id,profile_sha256,? FROM validation_intents WHERE intent_id=? AND request_id=? AND publication_id=? AND key_id=? AND profile_sha256=? AND revoked=FALSE AND expires_at>?`, f.EventID, observed, snap.Input.ValidationIntentID, f.RequestID, snap.Input.Profile.Binding.PublicationID, snap.Input.KeyID, hash(snap.Input.Profile), observed); e != nil {
				return e
			}
		}
		if _, e = tx.ExecContext(ctx, "UPDATE generation_requests SET result=?,terminal_event_id=? WHERE request_id=?", event["result"], f.EventID, f.RequestID); e != nil {
			return e
		}
		if _, e = tx.ExecContext(ctx, `INSERT INTO usage_daily(key_id,quota_date,result,finalized_total) VALUES(?,?,?,1) ON DUPLICATE KEY UPDATE finalized_total=finalized_total+1`, key, snap.Admitted.Format("2006-01-02"), event["result"]); e != nil {
			return e
		}
		if safe {
			return s.releaseSlot(ctx, tx, snap, f.Owner, closure)
		}
		result, e := tx.ExecContext(ctx, `UPDATE concurrency_slots SET state='QUARANTINED',row_version=row_version+1,quarantine_reason='transport_unproven' WHERE slot_id=? AND request_id=? AND allocation_fence=? AND state='HELD' AND row_version<9007199254740991`, snap.SlotID, f.RequestID, snap.AllocationFence)
		if e != nil {
			return e
		}
		n, _ := result.RowsAffected()
		if n != 1 {
			return ErrConflict
		}
		return nil
	})
}
func buildEvent(s Snapshot, f Final, t time.Time, noSend bool, token, cost *string, basis string, req settlement, tok, mon *settlement, breached bool) map[string]any {
	p := s.Input.Profile
	plan := s.Input.Plan
	submission := "unknown"
	if f.Submitted {
		submission = "submitted"
	}
	var evidence *string
	if noSend {
		submission = "not_submitted"
		evidence = ptr(f.EvidenceRef)
	}
	metering := "complete"
	var missing *string
	if token == nil {
		metering = "incomplete"
		missing = ptr("not_provided")
		if f.Usage.Source == "upstream" {
			missing = ptr("partial_usage")
		}
		if f.Result == "interrupted" {
			missing = ptr("owner_lost")
		}
	}
	costState := "known"
	if cost == nil {
		costState = "unavailable"
		if mon != nil {
			costState = "upper_bound"
		}
		if missing == nil {
			if p.Price == nil {
				missing = ptr("not_priced")
			} else {
				missing = ptr("partial_price_categories")
			}
		}
	}
	result := f.Result
	var code *string
	// Frozen 3.0 forbids incomplete succeeded events. Do not silently switch
	// consumers to the proposed 3.1 protocol.
	if result == "succeeded" && metering == "incomplete" {
		result = "failed"
		code = ptr("upstream_protocol_error")
	}
	switch result {
	case "failed":
		if code == nil {
			code = ptr("upstream_error")
		}
	case "cancelled":
		code = ptr("client_cancelled")
	case "timed_out":
		code = ptr("upstream_timeout")
	case "interrupted":
		code = ptr("owner_lost")
	}
	if breached {
		result = "failed"
		code = ptr("budget_bound_breached")
		missing = ptr("bound_breached")
		if mon != nil && mon.State == "anomalous" {
			costState = "anomalous"
		}
	}
	emittedUsage := f.Usage
	if emittedUsage.Source == "upstream" {
		if emittedUsage.Input == nil || emittedUsage.Output == nil || emittedUsage.Total == nil {
			emittedUsage.Missing = ptr("partial")
		} else {
			emittedUsage.Missing = nil
		}
	}
	return map[string]any{
		"schema_version": "3.0", "event_type": "request.finalized", "event_id": f.EventID, "request_id": f.RequestID, "key_id": s.Input.KeyID, "quota_date": s.Admitted.Format("2006-01-02"),
		"model_alias": p.Alias, "upstream_model": p.UpstreamModel, "source_id": p.SourceID, "source_type": p.SourceType, "config_revision": p.ConfigRevision,
		"received_at": s.Input.Received.Format(time.RFC3339Nano), "admitted_at": s.Admitted.Format(time.RFC3339Nano), "observed_at": t.Format(time.RFC3339Nano),
		"result": result, "submission_state": submission, "quota_consumed": map[bool]int{true: 0, false: 1}[noSend], "error_code": code, "duration_ms": t.Sub(s.Input.Received).Milliseconds(), "first_chunk_ms": f.FirstChunkMS,
		"usage": emittedUsage, "metering_state": metering, "owner_instance_id": f.Owner, "owner_fence": f.OwnerFence, "not_submitted_evidence_ref": evidence,
		"slot_binding": map[string]any{"slot_id": s.SlotID, "allocation_fence": s.AllocationFence}, "reservation_plan": plan,
		"budget_accounting":  map[string]any{"policy_revision": s.Policy.Revision, "window_kind": s.Policy.Window, "window_start": s.WindowStart.Format(time.RFC3339Nano), "window_end": s.WindowEnd.Format(time.RFC3339Nano), "request": req, "token": tok, "money": mon, "token_actual": token, "token_basis": basis, "cost_actual_atomic": cost, "cost_state": costState, "currency": plan.Currency, "price_snapshot_id": plan.PriceID, "price_version": plan.PriceVersion, "missing_reason": missing},
		"rate_witness":       map[string]any{"permit_id": s.Rate.ID, "rate_epoch": decimal(s.Rate.Epoch), "policy_id": s.Rate.PolicyID, "policy_revision": s.Rate.Revision, "windows": s.Rate.Windows},
		"invocation_binding": map[string]any{"model_release_uid": p.CRUID, "model_release_namespace": p.Namespace, "model_release_name": p.Name, "model_release_generation": p.Binding.Generation, "release_revision": p.Binding.Revision, "publication_id": p.Binding.PublicationID, "activation_epoch": p.Binding.Epoch, "route_binding_sha256": p.RouteDigest, "admission_purpose": purposeOf(s.Input), "price_snapshot_id": plan.PriceID, "price_version": plan.PriceVersion},
	}
}

// Recover fences the old owner after its original deadline. It never interprets
// owner loss as transport closure or restarts a deadline from recovery time.
func (s *Store) Recover(ctx context.Context, id, newOwner string) error {
	if !validUUID(newOwner) {
		return ErrConflict
	}
	var fence int64
	e := s.tx(ctx, func(tx *sql.Tx) error {
		if _, e := s.guard(ctx, tx, "FOR UPDATE NOWAIT"); e != nil {
			return e
		}
		snap, state, _, e := s.lockRequest(ctx, tx, id)
		if e != nil {
			return e
		}
		if state != "in_progress" {
			return nil
		}
		t, e := now(ctx, tx)
		if e != nil {
			return e
		}
		if t.Before(snap.Input.Deadline) || snap.OwnerFence >= maxCounter {
			return ErrBusy
		}
		fence = snap.OwnerFence + 1
		if snap.Input.Owner == newOwner {
			fence = snap.OwnerFence
		}
		_, e = tx.ExecContext(ctx, "UPDATE generation_requests SET owner_id=?,owner_fence=? WHERE request_id=?", newOwner, fence, id)
		return e
	})
	if e != nil || fence == 0 {
		return e
	}
	missing := "interrupted_before_usage"
	records, readErr := s.ReadDiagnostics(ctx, id)
	if readErr != nil {
		missing = "not_provided"
	}
	for _, d := range records {
		if d.Type == "receipt" {
			missing = "not_provided"
		}
	}
	return s.Finalize(ctx, Final{EventID: uuid.NewSHA1(uuid.NameSpaceOID, []byte(id+"/recovery")).String(), RequestID: id, Owner: newOwner, OwnerFence: fence, Result: "interrupted", Usage: Usage{Source: "unavailable", Missing: ptr(missing)}})
}

// Release performs no request, usage, Key, budget or summary UPDATE. Late proof
// can release physical capacity but cannot change the unique terminal event.
func (s *Store) Release(ctx context.Context, id, actor, evidence string) error {
	if !validUUID(actor) {
		return ErrConflict
	}
	return s.tx(ctx, func(tx *sql.Tx) error {
		if _, e := s.guard(ctx, tx, "FOR UPDATE NOWAIT"); e != nil {
			return e
		}
		snap, state, event, e := s.lockRequest(ctx, tx, id)
		if e != nil {
			return e
		}
		if state == "in_progress" || event == "" {
			return ErrConflict
		}
		c, safe, e := s.closure(ctx, tx, snap, evidence)
		if e != nil {
			return e
		}
		if !safe {
			return ErrConflict
		}
		return s.releaseSlot(ctx, tx, snap, actor, c)
	})
}
