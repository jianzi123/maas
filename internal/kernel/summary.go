package kernel

import (
	"context"
	"database/sql"
	"encoding/base64"
	"encoding/json"
	"math/big"
	"net/url"
	"sort"
	"strings"
	"time"
)

func (s *Store) Summary(ctx context.Context, q url.Values) (map[string]any, error) {
	for k := range q {
		switch k {
		case "date_from", "date_to", "key_id", "model_alias", "source_id", "page_size", "cursor", "currency", "price_version":
		default:
			return nil, ErrPolicy
		}
	}
	n, e := pageSize(q)
	if e != nil {
		return nil, e
	}
	copyQ := url.Values{}
	for k, v := range q {
		if k != "cursor" {
			copyQ[k] = v
		}
	}
	filter := hash(copyQ.Encode())
	last := ""
	if q.Get("cursor") != "" {
		b, e := base64.RawURLEncoding.Strict().DecodeString(q.Get("cursor"))
		var c []string
		if e != nil || json.Unmarshal(b, &c) != nil || len(c) != 2 || c[0] != filter {
			return nil, ErrPolicy
		}
		last = c[1]
	}
	out := map[string]any{}
	e = s.readView(ctx, func(tx *sql.Tx, t time.Time) error {
		where, args, e := requestFilter(q, t)
		if e != nil {
			return e
		}
		rows, e := tx.QueryContext(ctx, "SELECT r.snapshot_json,r.result,e.event_json FROM generation_requests r LEFT JOIN usage_events e ON e.event_id=r.terminal_event_id WHERE "+where+" LIMIT 10001", args...)
		if e != nil {
			return e
		}
		type item struct {
			snap  Snapshot
			state string
			event map[string]any
		}
		items := []item{}
		for rows.Next() {
			var b, eb []byte
			var v item
			if e = rows.Scan(&b, &v.state, &eb); e != nil {
				rows.Close()
				return e
			}
			if json.Unmarshal(b, &v.snap) != nil {
				rows.Close()
				return ErrUnavailable
			}
			if len(eb) > 0 {
				d := json.NewDecoder(strings.NewReader(string(eb)))
				d.UseNumber()
				if d.Decode(&v.event) != nil {
					rows.Close()
					return ErrUnavailable
				}
			}
			items = append(items, v)
		}
		e = rows.Err()
		rows.Close()
		if e != nil {
			return e
		}
		if len(items) > 10000 {
			return ErrUnavailable
		}
		groups := map[string]map[string]any{}
		fields := strings.Fields("admitted_total in_progress succeeded failed cancelled timed_out interrupted quota_used submitted_known submission_unknown not_submitted input_tokens_known output_tokens_known total_tokens_known missing_input_requests missing_output_requests missing_total_requests missing_token_requests missing_cost_requests")
		inc := func(g map[string]any, k string, n int64) error {
			x := big.NewInt(g[k].(int64))
			x.Add(x, big.NewInt(n))
			if !x.IsInt64() || x.Int64() > maxCounter {
				return ErrUnavailable
			}
			g[k] = x.Int64()
			return nil
		}
		for _, v := range items {
			p := v.snap.Input.Profile
			var currency, version any
			if p.Price != nil {
				currency = p.Price.Currency
				version = p.Price.Version
			}
			if q.Get("currency") != "" && currency != q.Get("currency") {
				continue
			}
			if q.Get("price_version") != "" && version != q.Get("price_version") {
				continue
			}
			group := hash([]any{v.snap.Admitted.Format("2006-01-02"), v.snap.Input.KeyID, p.Alias, p.SourceID, currency, version})
			g := groups[group]
			if g == nil {
				g = map[string]any{"quota_date": v.snap.Admitted.Format("2006-01-02"), "key_id": v.snap.Input.KeyID, "model_alias": p.Alias, "source_id": p.SourceID, "source_type": p.SourceType, "currency": currency, "price_version": version, "cost_known_atomic": nil, "money_uncertainty_held_atomic": nil, "token_uncertainty_held": "0"}
				for _, f := range fields {
					g[f] = int64(0)
				}
				if currency != nil {
					g["cost_known_atomic"] = "0"
					g["money_uncertainty_held_atomic"] = "0"
				}
				groups[group] = g
			}
			if inc(g, "admitted_total", 1) != nil || inc(g, v.state, 1) != nil {
				return ErrUnavailable
			}
			if v.event == nil {
				continue
			}
			quota := v.event["quota_consumed"].(json.Number)
			nn, _ := quota.Int64()
			if inc(g, "quota_used", nn) != nil {
				return ErrUnavailable
			}
			submission := v.event["submission_state"].(string)
			f := map[string]string{"unknown": "submission_unknown", "submitted": "submitted_known", "not_submitted": "not_submitted"}[submission]
			if inc(g, f, 1) != nil {
				return ErrUnavailable
			}
			usage := v.event["usage"].(map[string]any)
			missing := false
			for _, d := range []string{"input", "output", "total"} {
				if value, ok := usage[d+"_tokens"].(json.Number); ok {
					valueN, _ := value.Int64()
					if inc(g, d+"_tokens_known", valueN) != nil {
						return ErrUnavailable
					}
				} else {
					missing = true
					if inc(g, "missing_"+d+"_requests", 1) != nil {
						return ErrUnavailable
					}
				}
			}
			if missing {
				_ = inc(g, "missing_token_requests", 1)
			}
			a := v.event["budget_accounting"].(map[string]any)
			if cost, ok := a["cost_actual_atomic"].(string); ok && currency != nil {
				x, e := add(g["cost_known_atomic"].(string), cost)
				if e != nil {
					return e
				}
				g["cost_known_atomic"] = x
			} else {
				_ = inc(g, "missing_cost_requests", 1)
			}
			if tok, ok := a["token"].(map[string]any); ok {
				x, e := add(g["token_uncertainty_held"].(string), tok["unknown_held"].(string))
				if e != nil {
					return e
				}
				g["token_uncertainty_held"] = x
			}
			if money, ok := a["money"].(map[string]any); ok && currency != nil {
				x, e := add(g["money_uncertainty_held_atomic"].(string), money["unknown_held"].(string))
				if e != nil {
					return e
				}
				g["money_uncertainty_held_atomic"] = x
			}
		}
		keys := []string{}
		for k := range groups {
			if k > last {
				keys = append(keys, k)
			}
		}
		sort.Strings(keys)
		var cursor any
		if len(keys) > n {
			keys = keys[:n]
			b, _ := json.Marshal([]string{filter, keys[len(keys)-1]})
			cursor = base64.RawURLEncoding.EncodeToString(b)
		}
		data := []any{}
		for _, k := range keys {
			data = append(data, groups[k])
		}
		out = map[string]any{"data": data, "next_cursor": cursor, "generated_at": t.Format(time.RFC3339Nano), "data_complete": true}
		return nil
	})
	return out, e
}
