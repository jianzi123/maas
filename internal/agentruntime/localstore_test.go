package agentruntime

import (
	"context"
	"errors"
	"os"
	"path/filepath"
	"testing"
)

func TestLocalPersistenceRestartAndExclusiveOwnership(t *testing.T) {
	root := t.TempDir()
	store, e := OpenLocalStore(root)
	if e != nil {
		t.Fatal(e)
	}
	if _, e = OpenLocalStore(root); !errors.Is(e, ErrConflict) {
		t.Fatal("two owners", e)
	}
	model := &scriptedModel{f: plain}
	reg, _ := NewRegistry(Calculator{})
	s, _ := NewService(store, model, reg, limits())
	v, e := s.Create(context.Background(), actor, "durable")
	if e != nil {
		t.Fatal(e)
	}
	r := send(t, s, v, input("chat"))
	if e = s.Drive(context.Background(), actor, v.ID, r.ID); e != nil {
		t.Fatal(e)
	}
	if e = store.Close(); e != nil {
		t.Fatal(e)
	}
	_ = os.WriteFile(filepath.Join(root, "partial.tmp"), []byte("{"), 0600)
	store, e = OpenLocalStore(root)
	if e != nil {
		t.Fatal(e)
	}
	defer store.Close()
	s, _ = NewService(store, model, reg, limits())
	got := readRun(t, s, v, r)
	if got.Status != "completed" || len(got.Steps) != 1 {
		t.Fatal(got)
	}
	items, e := s.List(context.Background(), actor)
	if e != nil || len(items) != 1 {
		t.Fatal(e, items)
	}
	if e = store.CompareAndSwap(context.Background(), v, 0); !errors.Is(e, ErrConflict) {
		t.Fatal("stale CAS", e)
	}
}

func TestLocalRestartRetainsUnknownCheckpointWithoutExecution(t *testing.T) {
	root := t.TempDir()
	store, e := OpenLocalStore(root)
	if e != nil {
		t.Fatal(e)
	}
	model := &scriptedModel{f: plain}
	tools, _ := NewRegistry(Calculator{})
	s, _ := NewService(store, model, tools, limits())
	v, e := s.Create(context.Background(), actor, "restart")
	if e != nil {
		t.Fatal(e)
	}
	r := send(t, s, v, input("chat"))
	_, e = s.mutate(context.Background(), actor, v.ID, func(v *Session) error {
		rr := run(v, r.ID)
		rr.Status = "running"
		rr.Executor = "stopped-process"
		rr.Checkpoint = Checkpoint{Phase: "model_inflight", RequestID: "persisted-before-send"}
		return nil
	})
	if e != nil {
		t.Fatal(e)
	}
	if e = store.Close(); e != nil {
		t.Fatal(e)
	}
	store, e = OpenLocalStore(root)
	if e != nil {
		t.Fatal(e)
	}
	defer store.Close()
	s, _ = NewService(store, model, tools, limits())
	if e = s.Recover(context.Background(), actor, v.ID, r.ID); e != nil {
		t.Fatal(e)
	}
	got := readRun(t, s, v, r)
	if got.Status != "needs_confirmation" || got.Checkpoint.RequestID != "persisted-before-send" || model.calls.Load() != 0 {
		t.Fatal(got)
	}
}
