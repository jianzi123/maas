package kernel

// This deliberately small RESP2 client issues only AUTH, TIME and EVAL. It has
// no retry, sentinel failover, background goroutine, or business-budget counter.
import (
	"bufio"
	"context"
	"crypto/tls"
	"fmt"
	"github.com/google/uuid"
	"io"
	"net"
	"strconv"
	"strings"
	"time"
)

type redisConnection = net.Conn
type RedisGate struct {
	Network, Address, Prefix string
	TLS                      *tls.Config
	Username, Password       string
	Timeout                  time.Duration
}
type redisReply struct {
	text    string
	integer int64
	array   []redisReply
	kind    byte
}

func readReply(r *bufio.Reader, depth int) (redisReply, error) {
	var out redisReply
	if depth > 3 {
		return out, ErrUnavailable
	}
	line, e := r.ReadString('\n')
	if e != nil || len(line) < 3 || len(line) > 16384 || !strings.HasSuffix(line, "\r\n") {
		return out, ErrUnavailable
	}
	out.kind = line[0]
	value := line[1 : len(line)-2]
	switch out.kind {
	case '+':
		out.text = value
	case '-':
		return out, ErrUnavailable
	case ':':
		out.integer, e = strconv.ParseInt(value, 10, 64)
	case '$':
		var n int
		n, e = strconv.Atoi(value)
		if e != nil || n < 0 || n > 16384 {
			return out, ErrUnavailable
		}
		b := make([]byte, n+2)
		_, e = io.ReadFull(r, b)
		if e != nil || string(b[n:]) != "\r\n" {
			return out, ErrUnavailable
		}
		out.text = string(b[:n])
	case '*':
		var n int
		n, e = strconv.Atoi(value)
		if e != nil || n < 0 || n > 16 {
			return out, ErrUnavailable
		}
		for i := 0; i < n; i++ {
			v, err := readReply(r, depth+1)
			if err != nil {
				return out, err
			}
			out.array = append(out.array, v)
		}
	default:
		return out, ErrUnavailable
	}
	return out, e
}
func command(c net.Conn, args ...string) (redisReply, error) {
	var b strings.Builder
	fmt.Fprintf(&b, "*%d\r\n", len(args))
	for _, v := range args {
		fmt.Fprintf(&b, "$%d\r\n%s\r\n", len(v), v)
	}
	if _, e := io.WriteString(c, b.String()); e != nil {
		return redisReply{}, ErrUnavailable
	}
	return readReply(bufio.NewReader(io.LimitReader(c, 32768)), 0)
}
func (r *RedisGate) connect(ctx context.Context) (net.Conn, error) {
	if r.Prefix == "" || r.Address == "" || r.Timeout <= 0 || r.Timeout > 30*time.Second {
		return nil, ErrUnavailable
	}
	d := net.Dialer{Timeout: r.Timeout}
	var c net.Conn
	var e error
	if r.Network == "unix" {
		c, e = d.DialContext(ctx, "unix", r.Address)
	} else if r.Network == "tcp" && r.TLS != nil {
		c, e = (&tls.Dialer{NetDialer: &d, Config: r.TLS}).DialContext(ctx, "tcp", r.Address)
	} else {
		return nil, ErrUnavailable
	}
	if e != nil {
		return nil, ErrUnavailable
	}
	deadline := time.Now().Add(r.Timeout)
	if t, ok := ctx.Deadline(); ok && t.Before(deadline) {
		deadline = t
	}
	if e = c.SetDeadline(deadline); e != nil {
		c.Close()
		return nil, ErrUnavailable
	}
	if r.Password != "" {
		args := []string{"AUTH"}
		if r.Username != "" {
			args = append(args, r.Username)
		}
		args = append(args, r.Password)
		if _, e = command(c, args...); e != nil {
			c.Close()
			return nil, ErrUnavailable
		}
	}
	return c, nil
}

// InitializeEpoch is explicit coordinator work AFTER MySQL BlockRate and Redis
// reconstruction. It is never invoked on an Acquire failure or missing marker.
// Existing durable grants remain the final same-window upper bound.
func (r *RedisGate) InitializeEpoch(ctx context.Context, p RatePolicy) error {
	c, e := r.connect(ctx)
	if e != nil {
		return e
	}
	defer c.Close()
	_, e = command(c, "EVAL", `redis.call('SET',KEYS[1],ARGV[1]); return 1`, "1", r.Prefix+"{maas-rate}:epoch", rateMarker(p))
	return e
}

const rateScript = `
local tm=redis.call('TIME')
local now=tm[1]*1000+math.floor(tm[2]/1000)
local width=tonumber(ARGV[2])
local start=math.floor(now/width)*width
if redis.call('GET',KEYS[1])~=ARGV[1] or start~=tonumber(ARGV[3]) then return {-1,now} end
if redis.call('EXISTS',KEYS[4])==1 then return {-2,now} end
local g=tonumber(redis.call('GET',KEYS[2]) or '0')
local k=tonumber(redis.call('GET',KEYS[3]) or '0')
if g>=tonumber(ARGV[4]) or k>=tonumber(ARGV[5]) then return {0,now} end
local expiry=start+width
redis.call('INCR',KEYS[2]); redis.call('PEXPIREAT',KEYS[2],expiry)
redis.call('INCR',KEYS[3]); redis.call('PEXPIREAT',KEYS[3],expiry)
redis.call('SET',KEYS[4],ARGV[6]); redis.call('PEXPIREAT',KEYS[4],expiry)
return {1,now}
`

func (r *RedisGate) Acquire(ctx context.Context, request, key string, p RatePolicy) (Permit, error) {
	out := Permit{}
	if !p.Ready || p.WindowMS < 1 || p.WindowMS > 86400000 || p.GlobalLimit < 1 || p.KeyLimit < 1 || p.GlobalLimit > maxCounter || p.KeyLimit > maxCounter || !validUUID(request) || !validUUID(key) {
		return out, ErrUnavailable
	}
	c, e := r.connect(ctx)
	if e != nil {
		return out, e
	}
	defer c.Close()
	if p.RedisIdentity != "" {
		identity, e := redisIdentity(c)
		if e != nil || identity != p.RedisIdentity {
			return out, ErrUnavailable
		}
	}
	tm, e := command(c, "TIME")
	if e != nil || len(tm.array) != 2 {
		return out, ErrUnavailable
	}
	secs, e := strconv.ParseInt(tm.array[0].text, 10, 64)
	if e != nil {
		return out, ErrUnavailable
	}
	micro, e := strconv.ParseInt(tm.array[1].text, 10, 64)
	if e != nil {
		return out, ErrUnavailable
	}
	start := (secs*1000 + micro/1000) / p.WindowMS * p.WindowMS
	prefix := r.Prefix + "{maas-rate}:"
	bucket := prefix + decimal(p.Epoch) + ":" + p.Revision + ":" + decimal(start) + ":"
	id := uuid.NewString()
	reply, e := command(c, "EVAL", rateScript, "4", prefix+"epoch", bucket+"global", bucket+key, prefix+"request:"+decimal(p.Epoch)+":"+request, rateMarker(p), decimal(p.WindowMS), decimal(start), decimal(p.GlobalLimit), decimal(p.KeyLimit), id)
	if e != nil || len(reply.array) != 2 {
		return out, ErrUnavailable
	}
	code := reply.array[0].integer
	if code == -2 {
		return out, ErrConflict
	}
	if code != 1 {
		return out, ErrBusy
	}
	st := time.UnixMilli(start).UTC()
	end := time.UnixMilli(start + p.WindowMS).UTC()
	return Permit{ID: id, Epoch: p.Epoch, PolicyID: p.Revision, Revision: p.Revision, Windows: []RateWindow{{Scope: "global", Start: st.Format(time.RFC3339Nano), End: end.Format(time.RFC3339Nano), Limit: decimal(p.GlobalLimit)}, {Scope: "key/" + key, Start: st.Format(time.RFC3339Nano), End: end.Format(time.RFC3339Nano), Limit: decimal(p.KeyLimit)}}}, nil
}
