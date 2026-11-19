package agentruntime

import (
	"context"
	"encoding/json"
	"errors"
	"net/http/httptest"
	"strings"
	"testing"
	"time"
)

func TestHTTPHostRunsSameCoreAndJoinsShutdown(t *testing.T) {
	s, model, v := setupService(t, toolResponse, controlledTool(false))
	host, e := NewHost(context.Background(), s, 1, func(_ context.Context, p Principal) (Principal, error) { return p, nil })
	if e != nil {
		t.Fatal(e)
	}
	defer host.Close()
	h := ControlledHandler{Service: s, Auth: testAuth{}, Dispatch: host.Schedule}
	body, _ := json.Marshal(input("agent"))
	req := httptest.NewRequest("POST", "/__maas/controlled-agent/v0/sessions/"+v.ID+"/runs", strings.NewReader(string(body)))
	req.Header.Set("X-CSRF-Token", "verified")
	rr := httptest.NewRecorder()
	h.ServeHTTP(rr, req)
	if rr.Code != 202 {
		t.Fatal(rr.Code, rr.Body.String())
	}
	var r Run
	if json.Unmarshal(rr.Body.Bytes(), &r) != nil {
		t.Fatal(rr.Body.String())
	}
	deadline := time.Now().Add(2 * time.Second)
	for readRun(t, s, v, r).Status != "completed" {
		if time.Now().After(deadline) {
			t.Fatal(readRun(t, s, v, r))
		}
		time.Sleep(time.Millisecond)
	}
	if model.calls.Load() != 2 {
		t.Fatal(model.calls.Load())
	}
	host.Close()
	if e = host.Schedule(actor, v.ID, r.ID); !errors.Is(e, ErrUnavailable) {
		t.Fatal(e)
	}
}
func TestUnknownWriteOutcomeNeverReplays(t *testing.T) {
	tool := controlledTool(true)
	tool.f = func(context.Context) (string, error) { return "", errors.New("result lost") }
	s, m, v := setupService(t, toolResponse, tool)
	r := send(t, s, v, input("agent"))
	_ = s.Drive(context.Background(), actor, v.ID, r.ID)
	c := readRun(t, s, v, r).Steps[0].Calls[0]
	if e := s.Approve(context.Background(), actor, v.ID, r.ID, c.ID, c.Hash, true); e != nil {
		t.Fatal(e)
	}
	if e := s.Drive(context.Background(), actor, v.ID, r.ID); e != nil {
		t.Fatal(e)
	}
	if got := readRun(t, s, v, r); got.Status != "needs_confirmation" {
		t.Fatal(got)
	}
	_ = s.Recover(context.Background(), actor, v.ID, r.ID)
	if e := s.Drive(context.Background(), actor, v.ID, r.ID); !errors.Is(e, ErrConflict) {
		t.Fatal(e)
	}
	if tool.calls.Load() != 1 || m.calls.Load() != 1 {
		t.Fatal("uncertain write replayed")
	}
}
func TestEditKeepsOriginalAndRebuildsBranch(t *testing.T) {
	s, m, v := setupService(t, plain)
	r := send(t, s, v, input("chat"))
	_ = s.Drive(context.Background(), actor, v.ID, r.ID)
	in := input("chat")
	in.ClientID = "edit-1"
	in.ParentID = r.MessageID
	in.Text = "edited text"
	edited := send(t, s, v, in)
	m.f = func(ctx context.Context, req Request, emit func(string) error) (Response, error) {
		if len(req.Messages) != 1 || req.Messages[0].ParentID != r.MessageID || req.Messages[0].Parts[0].Text != "edited text" {
			t.Fatal(req.Messages)
		}
		return plain(ctx, req, emit)
	}
	if e := s.Drive(context.Background(), actor, v.ID, edited.ID); e != nil {
		t.Fatal(e)
	}
	doc, _ := s.Get(context.Background(), actor, v.ID)
	if len(doc.Runs) != 2 || len(doc.Messages) != 4 || doc.Runs[0].Steps[0].RequestID == doc.Runs[1].Steps[0].RequestID {
		t.Fatal(doc)
	}
	// The next ordinary turn sees the edited branch exactly once.
	in.ParentID = ""
	in.ClientID = "after-edit"
	in.Text = "next"
	next := send(t, s, v, in)
	m.f = func(ctx context.Context, req Request, emit func(string) error) (Response, error) {
		if len(req.Messages) != 3 || req.Messages[0].Parts[0].Text != "edited text" || req.Messages[2].Parts[0].Text != "next" {
			t.Fatal(req.Messages)
		}
		return plain(ctx, req, emit)
	}
	if e := s.Drive(context.Background(), actor, v.ID, next.ID); e != nil {
		t.Fatal(e)
	}
}
func TestDurationAndBudgetBound(t *testing.T) {
	t.Run("duration", func(t *testing.T) {
		s, _, v := setupService(t, func(ctx context.Context, r Request, _ func(string) error) (Response, error) {
			<-ctx.Done()
			return Response{}, ctx.Err()
		})
		s.Limits.Duration = 20 * time.Millisecond
		r := send(t, s, v, input("chat"))
		if e := s.Drive(context.Background(), actor, v.ID, r.ID); e != nil {
			t.Fatal(e)
		}
		if got := readRun(t, s, v, r); got.Status != "limit_reached" || got.Reason != "duration_limit" {
			t.Fatal(got)
		}
	})
	t.Run("bound", func(t *testing.T) {
		s, _, v := setupService(t, func(_ context.Context, r Request, _ func(string) error) (Response, error) {
			u := known()
			*u.Tokens = r.TokenUpper + 1
			return Response{RequestID: r.RequestID, Finish: "stop", Usage: u}, nil
		})
		r := send(t, s, v, input("chat"))
		_ = s.Drive(context.Background(), actor, v.ID, r.ID)
		if readRun(t, s, v, r).Reason != "model_budget_bound_violated" {
			t.Fatal(readRun(t, s, v, r))
		}
	})
}
