package kernel

import (
	"context"
	"database/sql"
	"encoding/json"
	"errors"
	"sort"
	"time"

	"github.com/jianzi123/maas/internal/protocol"
	"github.com/jianzi123/maas/internal/release"
)

func (s *Store) counters(ctx context.Context, tx *sql.Tx, key string, start, end time.Time) (map[string]Counter, error) {
	out := map[string]Counter{}
	for _, dim := range []string{"money", "requests", "tokens"} {
		if _, e := tx.ExecContext(ctx, `INSERT IGNORE INTO budget_windows(key_id,window_start,window_end,dimension) VALUES(?,?,?,?)`, key, start, end, dim); e != nil {
			return nil, e
		}
		var c Counter
		if e := tx.QueryRowContext(ctx, `SELECT known_used,inflight_reserved,uncertainty_held FROM budget_windows WHERE key_id=? AND window_start=? AND dimension=? FOR UPDATE NOWAIT`, key, start, dim).Scan(&c.Known, &c.Reserved, &c.Held); e != nil {
			return nil, e
		}
		out[dim] = c
	}
	return out, nil
}
func (s *Store) writeCounter(ctx context.Context, tx *sql.Tx, key string, start time.Time, dim string, c Counter) error {
	_, e := tx.ExecContext(ctx, `UPDATE budget_windows SET known_used=?,inflight_reserved=?,uncertainty_held=? WHERE key_id=? AND window_start=? AND dimension=?`, c.Known, c.Reserved, c.Held, key, start, dim)
	return e
}
func checkTime(in Input, t time.Time) error {
	if in.Received.After(in.Issued) || in.Issued.After(t) || !t.Before(in.Expires) || !in.Expires.Before(in.Deadline) || in.Deadline.Sub(in.Received) > 24*time.Hour {
		return ErrBusy
	}
	return nil
}
func (s *Store) reserveRate(ctx context.Context, tx *sql.Tx, in Input, p RatePolicy, permit Permit, t time.Time) error {
	if !p.Ready || permit.Epoch != p.Epoch || permit.Revision != p.Revision || permit.PolicyID != p.Revision || !validUUID(permit.ID) || len(permit.Windows) != 2 {
		return ErrUnavailable
	}
	expected := map[string]int64{"global": p.GlobalLimit, "key/" + in.KeyID: p.KeyLimit}
	windows := append([]RateWindow(nil), permit.Windows...)
	sort.Slice(windows, func(i, j int) bool { return windows[i].Scope < windows[j].Scope })
	for _, w := range windows {
		limit, ok := expected[w.Scope]
		if !ok || decimal(limit) != w.Limit {
			return ErrPolicy
		}
		delete(expected, w.Scope)
		start, e := time.Parse(time.RFC3339Nano, w.Start)
		if e != nil {
			return ErrPolicy
		}
		end, e := time.Parse(time.RFC3339Nano, w.End)
		if e != nil {
			return ErrPolicy
		}
		expectedStart := t.UnixMilli() / p.WindowMS * p.WindowMS
		if start.UnixMilli() != expectedStart || end.UnixMilli() != expectedStart+p.WindowMS || !t.Before(end) {
			return ErrBusy
		}
		if _, e = tx.ExecContext(ctx, `INSERT IGNORE INTO rate_window_grants(scope_id,window_start,policy_id,window_end,grants) VALUES(?,?,?,?,0)`, w.Scope, start, permit.PolicyID, end); e != nil {
			return e
		}
		var n int64
		if e = tx.QueryRowContext(ctx, `SELECT grants FROM rate_window_grants WHERE scope_id=? AND window_start=? AND policy_id=? FOR UPDATE NOWAIT`, w.Scope, start, permit.PolicyID).Scan(&n); e != nil {
			return e
		}
		if n >= limit {
			return ErrBusy
		}
		if _, e = tx.ExecContext(ctx, `UPDATE rate_window_grants SET grants=grants+1 WHERE scope_id=? AND window_start=? AND policy_id=?`, w.Scope, start, permit.PolicyID); e != nil {
			return e
		}
	}
	return nil
}

// Admit is internal to the authenticated ext-auth consumer. It neither sends a
// model request nor treats an uncertain commit as permission to send.
func (s *Store) Admit(ctx context.Context, gate ActiveGate, in Input) (Snapshot, error) {
	var out Snapshot
	if gate == nil || s.rate == nil || !validUUID(in.RequestID) || !validUUID(in.KeyID) || !validUUID(in.Owner) || len(in.TicketHash) != 64 {
		return out, ErrUnavailable
	}
	p, e := s.readRate(ctx)
	if e != nil || !p.Ready {
		return out, ErrUnavailable
	}
	permit, e := s.rate.Acquire(ctx, in.RequestID, in.KeyID, p)
	if e != nil {
		return out, sanitize(e)
	}
	e = s.tx(ctx, func(tx *sql.Tx) error {
		current, e := s.guard(ctx, tx, "FOR UPDATE NOWAIT")
		if e != nil {
			return e
		}
		current, e = s.rateMetadata(ctx, tx, current)
		if e != nil {
			return e
		}
		if current != p {
			return ErrPolicy
		}
		binding, e := s.gate(ctx, tx, gate, in)
		if e != nil {
			return e
		}
		if binding != in.Profile.Binding {
			return release.ErrConflict
		}
		profile, e := s.profile(ctx, tx, binding.PublicationID)
		if e != nil {
			return e
		}
		if hash(profile) != hash(in.Profile) {
			return ErrPolicy
		}
		policy, epoch, e := s.key(ctx, tx, in.KeyID)
		if e != nil {
			return e
		}
		if epoch != in.KeyEpoch {
			return ErrKey
		}
		// Sample after lock acquisition using a separate statement, never NOW in a
		// potentially waiting locking SELECT.
		t, e := now(ctx, tx)
		if e != nil {
			return e
		}
		if e = checkTime(in, t); e != nil {
			return e
		}
		if profile.Price != nil {
			effective, _ := time.Parse(time.RFC3339Nano, profile.Price.Effective)
			if t.Before(effective) {
				return ErrPrice
			}
		}
		plan, e := BuildPlan(profile, policy, p.Revision)
		if e != nil {
			return e
		}
		if protocol.Validate("ReservationPlan", plan) != nil {
			return ErrPolicy
		}
		if hash(plan) != hash(in.Plan) {
			return ErrPolicy
		}
		start, end := window(t, policy.Window)
		receivedStart, _ := window(in.Received, policy.Window)
		if !receivedStart.Equal(start) {
			return ErrBusy
		}
		counters, e := s.counters(ctx, tx, in.KeyID, start, end)
		if e != nil {
			return e
		}
		if e = s.reserveRate(ctx, tx, in, p, permit, t); e != nil {
			return e
		}
		var existing string
		e = tx.QueryRowContext(ctx, "SELECT request_id FROM generation_requests WHERE request_id=? FOR UPDATE NOWAIT", in.RequestID).Scan(&existing)
		if e == nil {
			return ErrConflict
		}
		if !errors.Is(e, sql.ErrNoRows) {
			return e
		}
		var slot, fence, version int64
		e = tx.QueryRowContext(ctx, `SELECT slot_id,allocation_fence,row_version FROM concurrency_slots WHERE state='FREE' AND allocation_fence<9007199254740991 AND row_version<9007199254740990 ORDER BY slot_id LIMIT 1 FOR UPDATE NOWAIT`).Scan(&slot, &fence, &version)
		if errors.Is(e, sql.ErrNoRows) {
			return ErrCapacity
		}
		if e != nil {
			return e
		}
		limits := map[string]*string{"requests": policy.Limits.Requests, "tokens": policy.Limits.Tokens, "money": nil}
		if policy.Limits.Money != nil {
			limits["money"] = &policy.Limits.Money.Limit
		}
		reservation := map[string]string{"requests": "1", "tokens": reserved(plan.Tokens), "money": reserved(plan.Money)}
		for _, dim := range []string{"money", "requests", "tokens"} {
			c := counters[dim]
			sum, e := add(c.Known, c.Reserved)
			if e != nil {
				return e
			}
			sum, e = add(sum, c.Held)
			if e != nil {
				return e
			}
			sum, e = add(sum, reservation[dim])
			if e != nil {
				return e
			}
			if lim := limits[dim]; lim != nil {
				n, _ := number(sum)
				l, _ := number(*lim)
				if l.Sign() == 0 || n.Cmp(l) > 0 {
					switch dim {
					case "requests":
						return ErrBudget
					case "tokens":
						return ErrTokens
					default:
						return ErrMoney
					}
				}
			}
			c.Reserved, e = add(c.Reserved, reservation[dim])
			if e != nil {
				return e
			}
			if e = s.writeCounter(ctx, tx, in.KeyID, start, dim, c); e != nil {
				return e
			}
		}
		out = Snapshot{Input: in, Policy: policy, Rate: permit, WindowStart: start, WindowEnd: end, Admitted: t, SlotID: slot, AllocationFence: fence + 1, OwnerFence: 1}
		b, _ := json.Marshal(out)
		if _, e = tx.ExecContext(ctx, "INSERT INTO request_snapshot_digests(request_id,snapshot_sha256) VALUES(?,?)", in.RequestID, protocol.Digest(b)); e != nil {
			return e
		}
		if _, e = tx.ExecContext(ctx, `INSERT INTO generation_requests(request_id,key_id,publication_id,owner_id,owner_fence,hard_deadline,snapshot_json,result) VALUES(?,?,?,?,1,?,?,'in_progress')`, in.RequestID, in.KeyID, binding.PublicationID, in.Owner, in.Deadline, b); e != nil {
			return e
		}
		if _, e = tx.ExecContext(ctx, `UPDATE concurrency_slots SET state='HELD',allocation_fence=?,row_version=row_version+1,request_id=?,publication_id=?,hard_deadline=?,release_not_before=? WHERE slot_id=? AND state='FREE' AND allocation_fence=? AND row_version=?`, fence+1, in.RequestID, binding.PublicationID, in.Deadline, in.Deadline.Add(5*time.Second), slot, fence, version); e != nil {
			return e
		}
		// Final independent clock and publication freshness check immediately before
		// commit. Redis is not contacted again while holding MySQL locks.
		t, e = now(ctx, tx)
		if e != nil {
			return e
		}
		if e = checkTime(in, t); e != nil {
			return e
		}
		checkStart, _ := window(t, policy.Window)
		if !checkStart.Equal(start) {
			return ErrBusy
		}
		for _, w := range permit.Windows {
			end, _ := time.Parse(time.RFC3339Nano, w.End)
			if !t.Before(end) {
				return ErrBusy
			}
		}
		binding2, e := s.gate(ctx, tx, gate, in)
		if e != nil {
			return e
		}
		if binding2 != binding {
			return ErrPolicy
		}
		// The final gate/evidence SELECT can itself take time. Sample the DB clock
		// AFTER it as well, so a post-write expiry cannot use the earlier sample.
		t, e = now(ctx, tx)
		if e != nil {
			return e
		}
		if e = checkTime(in, t); e != nil {
			return e
		}
		lastWindow, _ := window(t, policy.Window)
		if !lastWindow.Equal(start) {
			return ErrBusy
		}
		for _, w := range permit.Windows {
			until, _ := time.Parse(time.RFC3339Nano, w.End)
			if !t.Before(until) {
				return ErrBusy
			}
		}
		return nil
	})
	if e != nil {
		return Snapshot{}, e
	}
	return out, nil
}
