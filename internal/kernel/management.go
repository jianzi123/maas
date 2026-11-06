package kernel

import (
	"context"
	"database/sql"
	"encoding/json"
	"errors"
	"github.com/google/uuid"
	"time"
	"unicode/utf8"
)

var ErrNotFound = errors.New("not_found")

func (s *Store) CreateManagedKey(ctx context.Context, name string, policy Policy) (string, string, error) {
	if utf8.RuneCountInString(name) < 1 || utf8.RuneCountInString(name) > 64 {
		return "", "", ErrPolicy
	}
	policy.Revision = uuid.NewString()
	return s.createKey(ctx, name, policy, "serving")
}
func (s *Store) CreateValidationKey(ctx context.Context, name string, p Policy) (string, string, error) {
	if len(name) == 0 || len(name) > 64 {
		return "", "", ErrPolicy
	}
	return s.createKey(ctx, name, p, "validation")
}
func (s *Store) PatchKey(ctx context.Context, id, expected string, limits Limits) error {
	if !validUUID(id) || expected == "" {
		return ErrPolicy
	}
	return s.tx(ctx, func(tx *sql.Tx) error {
		if _, e := s.guard(ctx, tx, "FOR UPDATE NOWAIT"); e != nil {
			return e
		}
		old, _, e := s.key(ctx, tx, id)
		if e != nil {
			return e
		}
		if old.Revision != expected {
			return ErrConflict
		}
		var currency sql.NullString
		if e = tx.QueryRowContext(ctx, "SELECT retained_currency FROM platform_keys WHERE key_id=?", id).Scan(&currency); e != nil {
			return e
		}
		if limits.Money != nil && currency.Valid && currency.String != limits.Money.Currency {
			return ErrPolicy
		}
		old.Limits = limits
		old.Revision = uuid.NewString()
		if e = validatePolicy(old); e != nil {
			return e
		}
		b, _ := json.Marshal(old)
		var cur *string
		if limits.Money != nil {
			cur = &limits.Money.Currency
		}
		_, e = tx.ExecContext(ctx, "UPDATE platform_keys SET policy_json=?,retained_currency=COALESCE(retained_currency,?) WHERE key_id=?", b, cur, id)
		return e
	})
}
func (s *Store) readView(ctx context.Context, fn func(*sql.Tx, time.Time) error) error {
	tx, e := s.db.BeginTx(ctx, &sql.TxOptions{ReadOnly: true, Isolation: sql.LevelRepeatableRead})
	if e != nil {
		return ErrUnavailable
	}
	defer tx.Rollback()
	t, e := now(ctx, tx)
	if e != nil {
		return ErrUnavailable
	}
	e = fn(tx, t)
	if errors.Is(e, sql.ErrNoRows) {
		return ErrNotFound
	}
	return sanitizeView(e)
}
func sanitizeView(e error) error {
	if errors.Is(e, ErrNotFound) {
		return ErrNotFound
	}
	return sanitize(e)
}
func (s *Store) keyView(ctx context.Context, tx *sql.Tx, id string, t time.Time) (map[string]any, error) {
	var name, prefix string
	var created time.Time
	var revokedAt sql.NullTime
	var revoked, blocked bool
	var b []byte
	var currency sql.NullString
	e := tx.QueryRowContext(ctx, `SELECT m.name,m.key_prefix,m.created_at,m.revoked_at,k.revoked,k.blocked,k.policy_json,k.retained_currency FROM platform_keys k JOIN key_metadata m ON m.key_id=k.key_id WHERE k.key_id=?`, id).Scan(&name, &prefix, &created, &revokedAt, &revoked, &blocked, &b, &currency)
	if errors.Is(e, sql.ErrNoRows) {
		var present int
		if err := tx.QueryRowContext(ctx, "SELECT COUNT(*) FROM platform_keys WHERE key_id=?", id).Scan(&present); err != nil {
			return nil, err
		}
		if present > 0 {
			return nil, ErrUnavailable
		}
	}
	if e != nil {
		return nil, e
	}
	var p Policy
	if json.Unmarshal(b, &p) != nil {
		return nil, ErrUnavailable
	}
	start, end := window(t, p.Window)
	counters := map[string]Counter{"requests": {"0", "0", "0"}, "tokens": {"0", "0", "0"}, "money": {"0", "0", "0"}}
	rows, e := tx.QueryContext(ctx, `SELECT dimension,known_used,inflight_reserved,uncertainty_held FROM budget_windows WHERE key_id=? AND window_start=?`, id, start)
	if e != nil {
		return nil, e
	}
	for rows.Next() {
		var dim string
		var c Counter
		if e = rows.Scan(&dim, &c.Known, &c.Reserved, &c.Held); e != nil {
			rows.Close()
			return nil, e
		}
		counters[dim] = c
	}
	e = rows.Err()
	rows.Close()
	if e != nil {
		return nil, e
	}
	known, inflight, held, available := map[string]any{}, map[string]any{}, map[string]any{}, map[string]any{}
	for _, d := range []string{"requests", "tokens", "money"} {
		field := d
		if d == "money" {
			field = "money_atomic"
		}
		c := counters[d]
		known[field] = c.Known
		inflight[field] = c.Reserved
		held[field] = c.Held
		var limit *string
		switch d {
		case "requests":
			limit = p.Limits.Requests
		case "tokens":
			limit = p.Limits.Tokens
		case "money":
			if p.Limits.Money != nil {
				limit = &p.Limits.Money.Limit
			}
		}
		available[field] = nil
		if limit != nil {
			used, e := add(c.Known, c.Reserved)
			if e != nil {
				return nil, e
			}
			used, e = add(used, c.Held)
			if e != nil {
				return nil, e
			}
			rest, e := subtract(*limit, used)
			if e != nil {
				rest = "0"
			}
			available[field] = rest
		}
		if d == "money" && !currency.Valid {
			known[field] = nil
			inflight[field] = nil
			held[field] = nil
		}
	}
	state := "active"
	if revoked {
		state = "revoked"
	}
	var revTime any
	if revokedAt.Valid {
		revTime = revokedAt.Time.Format(time.RFC3339Nano)
	}
	var cur, reason any
	if currency.Valid {
		cur = currency.String
	}
	if blocked {
		reason = "budget_bound_breached"
	}
	return map[string]any{"id": id, "name": name, "key_prefix": prefix, "state": state, "created_at": created.Format(time.RFC3339Nano), "revoked_at": revTime, "budget_policy": p, "budget_state": map[string]any{"window_kind": p.Window, "window_start": start.Format(time.RFC3339Nano), "window_end": end.Format(time.RFC3339Nano), "admission_blocked": blocked, "block_reason": reason, "currency": cur, "known_used": known, "inflight_reserved": inflight, "uncertainty_held": held, "available": available}}, nil
}
func (s *Store) KeyView(ctx context.Context, id string) (map[string]any, error) {
	var out map[string]any
	e := s.readView(ctx, func(tx *sql.Tx, t time.Time) error { var e error; out, e = s.keyView(ctx, tx, id, t); return e })
	return out, e
}
