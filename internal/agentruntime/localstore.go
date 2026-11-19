package agentruntime

import (
	"context"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"sync"

	"github.com/google/uuid"
)

// LocalStore is a single-process development store. MySQLStore remains the
// multi-replica installation provider. Immutable generations are synced before
// publication; a partial temp file is never a committed session. Its directory
// lock is deliberately NOT auto-stolen after a crash: verify the recorded PID
// has stopped before removing .owner-lock. Power-loss guarantees are filesystem
// dependent; this store is not a production durability claim.
type LocalStore struct {
	root   string
	mu     sync.Mutex
	closed bool
}

func OpenLocalStore(root string) (*LocalStore, error) {
	if e := os.MkdirAll(root, 0700); e != nil {
		return nil, e
	}
	lock := filepath.Join(root, ".owner-lock")
	f, e := os.OpenFile(lock, os.O_CREATE|os.O_EXCL|os.O_WRONLY, 0600)
	if e != nil {
		return nil, ErrConflict
	}
	_, e = fmt.Fprintf(f, "%d\n", os.Getpid())
	if e == nil {
		e = f.Sync()
	}
	ce := f.Close()
	if e != nil || ce != nil {
		_ = os.Remove(lock)
		return nil, ErrUnavailable
	}
	return &LocalStore{root: root}, nil
}
func (s *LocalStore) Close() error {
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.closed {
		return nil
	}
	s.closed = true
	return os.Remove(filepath.Join(s.root, ".owner-lock"))
}
func (s *LocalStore) get(id string) (Session, error) {
	if s.closed {
		return Session{}, ErrUnavailable
	}
	if _, e := uuid.Parse(id); e != nil {
		return Session{}, ErrNotFound
	}
	files, e := os.ReadDir(s.root)
	if e != nil {
		return Session{}, e
	}
	var latest int64
	name := ""
	for _, f := range files {
		if strings.HasPrefix(f.Name(), id+".") && strings.HasSuffix(f.Name(), ".json") {
			n, e := strconv.ParseInt(strings.TrimSuffix(strings.TrimPrefix(f.Name(), id+"."), ".json"), 10, 64)
			if e == nil && n > latest {
				latest = n
				name = f.Name()
			}
		}
	}
	if name == "" {
		return Session{}, ErrNotFound
	}
	b, e := os.ReadFile(filepath.Join(s.root, name))
	if e != nil {
		return Session{}, e
	}
	var v Session
	if json.Unmarshal(b, &v) != nil || v.ID != id || v.Revision != latest || v.Version != Version {
		return Session{}, ErrUnavailable
	}
	return v, nil
}
func (s *LocalStore) Get(ctx context.Context, id string) (Session, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	if ctx.Err() != nil {
		return Session{}, ctx.Err()
	}
	return s.get(id)
}
func (s *LocalStore) List(ctx context.Context, owner string) ([]Session, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.closed {
		return nil, ErrUnavailable
	}
	files, e := os.ReadDir(s.root)
	if e != nil {
		return nil, e
	}
	seen := map[string]bool{}
	out := []Session{}
	for _, f := range files {
		if ctx.Err() != nil {
			return nil, ctx.Err()
		}
		if !strings.HasSuffix(f.Name(), ".json") {
			continue
		}
		id := strings.Split(f.Name(), ".")[0]
		if seen[id] {
			continue
		}
		seen[id] = true
		v, e := s.get(id)
		if e != nil {
			return nil, e
		}
		if v.Owner == owner && !v.Deleted {
			out = append(out, v)
		}
	}
	return out, nil
}
func (s *LocalStore) CompareAndSwap(ctx context.Context, v Session, expected int64) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	if ctx.Err() != nil {
		return ctx.Err()
	}
	if s.closed {
		return ErrUnavailable
	}
	if _, e := uuid.Parse(v.ID); e != nil || v.Revision != expected+1 || v.Version != Version {
		return ErrInvalid
	}
	old, e := s.get(v.ID)
	if e != nil && !errorsNotFound(e) {
		return e
	}
	if old.Revision != expected {
		return ErrConflict
	}
	b, e := json.Marshal(v)
	if e != nil || len(b) > 32<<20 {
		return ErrInvalid
	}
	tmp := filepath.Join(s.root, uuid.NewString()+".tmp")
	f, e := os.OpenFile(tmp, os.O_CREATE|os.O_EXCL|os.O_WRONLY, 0600)
	if e != nil {
		return e
	}
	defer os.Remove(tmp)
	_, e = f.Write(b)
	if e == nil {
		e = f.Sync()
	}
	ce := f.Close()
	if e != nil {
		return e
	}
	if ce != nil {
		return ce
	}
	return os.Rename(tmp, filepath.Join(s.root, fmt.Sprintf("%s.%020d.json", v.ID, v.Revision)))
}
func errorsNotFound(e error) bool { return e == ErrNotFound }
