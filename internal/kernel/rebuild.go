package kernel

import (
	"context"
	"database/sql"
	"errors"
	"github.com/google/uuid"
	"strings"
	"time"
)

func rateMarker(p RatePolicy) string {
	v := decimal(p.Epoch) + "/" + p.Revision
	if p.RedisIdentity != "" {
		v += "/" + p.RedisIdentity + "/" + p.RebuildNonce
	}
	return v
}
func (s *Store) rateMetadata(ctx context.Context, tx *sql.Tx, p RatePolicy) (RatePolicy, error) {
	e := tx.QueryRowContext(ctx, "SELECT redis_identity,nonce FROM rate_rebuilds WHERE epoch=?", p.Epoch).Scan(&p.RedisIdentity, &p.RebuildNonce)
	if errors.Is(e, sql.ErrNoRows) {
		return p, nil
	}
	return p, e
}
func (s *Store) readRate(ctx context.Context) (RatePolicy, error) {
	var p RatePolicy
	e := s.readView(ctx, func(tx *sql.Tx, _ time.Time) error {
		var e error
		p, e = s.guard(ctx, tx, "")
		if e != nil {
			return e
		}
		p, e = s.rateMetadata(ctx, tx, p)
		return e
	})
	return p, e
}
func redisIdentity(c redisConnection) (string, error) {
	reply, e := command(c, "INFO", "server")
	if e != nil {
		return "", e
	}
	for _, line := range strings.Split(reply.text, "\n") {
		if strings.HasPrefix(line, "run_id:") {
			id := strings.TrimSpace(strings.TrimPrefix(line, "run_id:"))
			if len(id) == 40 {
				return id, nil
			}
		}
	}
	return "", ErrUnavailable
}

// RebuildRate resumes an explicitly BLOCKED epoch. Redis I/O is outside MySQL
// transactions. Durable same-window grants are lower bounds; policy/window,
// instance identity and nonce must all match before ready is committed.
func (s *Store) RebuildRate(ctx context.Context, r *RedisGate, epoch int64) error {
	if r == nil {
		return ErrUnavailable
	}
	p, e := s.readRate(ctx)
	if e != nil {
		return e
	}
	if p.Ready || p.Epoch != epoch || p.WindowMS < 1 {
		return ErrConflict
	}
	var start time.Time
	grants := map[string]int64{}
	e = s.readView(ctx, func(tx *sql.Tx, t time.Time) error {
		start = time.UnixMilli(t.UnixMilli() / p.WindowMS * p.WindowMS).UTC()
		rows, e := tx.QueryContext(ctx, "SELECT scope_id,grants FROM rate_window_grants WHERE window_start=? AND policy_id=?", start, p.Revision)
		if e != nil {
			return e
		}
		defer rows.Close()
		for rows.Next() {
			var scope string
			var count int64
			if e = rows.Scan(&scope, &count); e != nil {
				return e
			}
			if count < 0 || count > maxCounter {
				return ErrUnavailable
			}
			grants[scope] = count
		}
		return rows.Err()
	})
	if e != nil {
		return e
	}
	c, e := r.connect(ctx)
	if e != nil {
		return e
	}
	defer c.Close()
	identity, e := redisIdentity(c)
	if e != nil {
		return e
	}
	p.RedisIdentity = identity
	p.RebuildNonce = uuid.NewString()
	prefix := r.Prefix + "{maas-rate}:"
	bucket := prefix + decimal(epoch) + ":" + p.Revision + ":" + decimal(start.UnixMilli()) + ":"
	keys := []string{prefix + "epoch"}
	values := []string{}
	for scope, n := range grants {
		suffix := scope
		if strings.HasPrefix(scope, "key/") {
			suffix = strings.TrimPrefix(scope, "key/")
			if !validUUID(suffix) {
				return ErrUnavailable
			}
		} else if scope != "global" {
			return ErrUnavailable
		}
		keys = append(keys, bucket+suffix)
		values = append(values, decimal(n))
	}
	script := `local tm=redis.call('TIME');local now=tm[1]*1000+math.floor(tm[2]/1000);local start=tonumber(ARGV[2]);local width=tonumber(ARGV[3]);if math.floor(now/width)*width~=start then return 0 end;for i=2,#KEYS do local old=tonumber(redis.call('GET',KEYS[i]) or '0');local value=tonumber(ARGV[i+2]);if old<value then redis.call('SET',KEYS[i],value) end;redis.call('PEXPIREAT',KEYS[i],start+width) end;redis.call('SET',KEYS[1],ARGV[1]);return 1`
	args := []string{"EVAL", script, decimal(int64(len(keys)))}
	args = append(args, keys...)
	args = append(args, rateMarker(p), decimal(start.UnixMilli()), decimal(p.WindowMS))
	args = append(args, values...)
	reply, e := command(c, args...)
	if e != nil || reply.integer != 1 {
		return ErrUnavailable
	}
	after, e := redisIdentity(c)
	if e != nil || after != identity {
		return ErrUnavailable
	}
	marker, e := command(c, "GET", keys[0])
	if e != nil || marker.text != rateMarker(p) {
		return ErrUnavailable
	}
	return s.tx(ctx, func(tx *sql.Tx) error {
		current, e := s.guard(ctx, tx, "FOR UPDATE NOWAIT")
		if e != nil {
			return e
		}
		if current.Ready || current.Epoch != epoch || current.Revision != p.Revision || current.WindowMS != p.WindowMS || current.GlobalLimit != p.GlobalLimit || current.KeyLimit != p.KeyLimit {
			return ErrConflict
		}
		t, e := now(ctx, tx)
		if e != nil {
			return e
		}
		if t.UnixMilli()/p.WindowMS*p.WindowMS != start.UnixMilli() {
			return ErrBusy
		}
		if _, e = tx.ExecContext(ctx, "INSERT INTO rate_rebuilds(epoch,redis_identity,nonce,window_start,completed_at) VALUES(?,?,?,?,?)", epoch, identity, p.RebuildNonce, start, t); e != nil {
			return e
		}
		_, e = tx.ExecContext(ctx, "UPDATE kernel_guard SET rate_ready=TRUE WHERE id=1")
		return e
	})
}
