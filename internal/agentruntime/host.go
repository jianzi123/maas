package agentruntime

import (
	"context"
	"sync"
	"time"
)

// Host owns bounded execution goroutines and joins them on shutdown. The caller
// supplies current authorization again for each execution; HTTP replay never
// schedules work. Queued documents survive process death and may be scheduled
// after recovery; in-flight operations require explicit Recover, never replay.
type Host struct {
	service *Service
	ctx     context.Context
	cancel  context.CancelFunc
	mu      sync.Mutex
	closed  bool
	wg      sync.WaitGroup
	slots   chan struct{}
	active  map[string]bool
	// Resolve must revalidate current identity/permissions. It never trusts a
	// serialized browser principal or the permissions saved in the run document.
	Resolve func(context.Context, Principal) (Principal, error)
}

func NewHost(ctx context.Context, s *Service, concurrency int, resolve func(context.Context, Principal) (Principal, error)) (*Host, error) {
	if s == nil || resolve == nil || concurrency < 1 || concurrency > 128 {
		return nil, ErrInvalid
	}
	root, cancel := context.WithCancel(ctx)
	return &Host{service: s, ctx: root, cancel: cancel, slots: make(chan struct{}, concurrency), active: map[string]bool{}, Resolve: resolve}, nil
}
func (h *Host) Schedule(p Principal, sid, rid string) error {
	h.mu.Lock()
	defer h.mu.Unlock()
	if h.closed || h.ctx.Err() != nil {
		return ErrUnavailable
	}
	key := sid + "/" + rid
	if h.active[key] {
		return nil
	}
	select {
	case h.slots <- struct{}{}:
	default:
		return ErrUnavailable
	}
	h.wg.Add(1)
	h.active[key] = true
	go func() {
		defer h.wg.Done()
		defer func() { <-h.slots }()
		defer func() { h.mu.Lock(); delete(h.active, key); h.mu.Unlock() }()
		for {
			current, e := h.Resolve(h.ctx, p)
			if e != nil || current.ID != p.ID || current.Revision != p.Revision {
				_, _ = h.service.mutate(h.ctx, p, sid, func(v *Session) error {
					r := run(v, rid)
					if r == nil {
						return ErrNotFound
					}
					if r.Status == "accepted" || r.Status == "waiting_approval" {
						finish(v, r, "failed", "authorization_changed")
					}
					return nil
				})
				return
			}
			v, e := h.service.Get(h.ctx, current, sid)
			if e != nil {
				return
			}
			r := run(&v, rid)
			if r == nil {
				return
			}
			if (r.Status == "accepted" || r.Status == "waiting_approval") && !time.Now().Before(r.Deadline) {
				_ = h.service.Expire(h.ctx, current, sid, rid)
				return
			}
			if r.Status == "accepted" {
				if e = h.service.Drive(h.ctx, current, sid, rid); e != nil {
					return
				}
				continue
			}
			if r.Status != "waiting_approval" {
				return
			}
			timer := time.NewTimer(25 * time.Millisecond)
			select {
			case <-h.ctx.Done():
				timer.Stop()
				return
			case <-timer.C:
			}
		}
	}()
	return nil
}
func (h *Host) Close() { h.mu.Lock(); h.closed = true; h.cancel(); h.mu.Unlock(); h.wg.Wait() }
