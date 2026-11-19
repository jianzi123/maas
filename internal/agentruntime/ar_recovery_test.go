package agentruntime

import (
	"context"
	"encoding/json"
	"errors"
	"strings"
	"testing"
	"time"

	"github.com/google/uuid"
)

func TestAR1FileRestartKeepsExactEventsAndCursorScope(t *testing.T) {
	dir := t.TempDir()
	store, e := OpenLocalStore(dir)
	if e != nil {
		t.Fatal(e)
	}
	h, model, _ := setupAR(t, arPlain, store)
	sid, etag := arCreateSession(t, h)
	rid := arSubmit(t, h, sid, etag, arInput("chat"))
	if e = h.Service.Drive(context.Background(), arActor, sid, rid); e != nil {
		t.Fatal(e)
	}
	base := "sessions/" + sid + "/runs/" + rid
	before := arHTTP(t, h, "GET", base+"/events?page_size=100", nil, "", "EventPage", 200).Body.String()
	body := arDecode(t, arHTTP(t, h, "GET", base, nil, "", "Run", 200))
	cursor := body["resume_cursor"].(string)
	if e = store.Close(); e != nil {
		t.Fatal(e)
	}
	store, e = OpenLocalStore(dir)
	if e != nil {
		t.Fatal(e)
	}
	defer store.Close()
	fresh, newModel, auth := setupAR(t, arPlain, store)
	after := arHTTP(t, fresh, "GET", base+"/events?page_size=100", nil, "", "EventPage", 200).Body.String()
	if before != after {
		t.Fatal("replay recomputed historical payloads")
	}
	arHTTP(t, fresh, "GET", base+"/events?after="+cursor, nil, "", "EventPage", 200)
	other, match := arCreateSession(t, fresh)
	otherRun := arSubmit(t, fresh, other, match, arInput("chat"))
	arHTTP(t, fresh, "GET", "sessions/"+other+"/runs/"+otherRun+"/events?after="+cursor, nil, "", "Error", 400)
	auth.mu.Lock()
	auth.p.ID = uuid.NewString()
	auth.mu.Unlock()
	arHTTP(t, fresh, "GET", base+"/events", nil, "", "Error", 404)
	if model.calls.Load() != 1 || newModel.calls.Load() != 0 {
		t.Fatal("replay generated model work")
	}
}
func TestAR1CancelIsRequestUntilTransportReturns(t *testing.T) {
	started, release := make(chan struct{}), make(chan struct{})
	h, _, _ := setupAR(t, func(ctx context.Context, r Request, _ func(string) error) (Response, error) {
		close(started)
		<-ctx.Done()
		<-release
		return Response{}, ctx.Err()
	}, nil)
	host, e := NewHost(context.Background(), h.Service, 1, h.Service.Reauthorize)
	if e != nil {
		t.Fatal(e)
	}
	defer host.Close()
	h.Dispatch = host.Schedule
	sid, etag := arCreateSession(t, h)
	rid := arSubmit(t, h, sid, etag, arInput("chat"))
	<-started
	base := "sessions/" + sid + "/runs/" + rid
	current := arDecode(t, arHTTP(t, h, "POST", base+"/cancel", nil, "", "Run", 202))
	if current["state"] != "running" || current["cancel_requested"] != true {
		t.Fatal(current)
	}
	close(release)
	deadline := time.Now().Add(2 * time.Second)
	for {
		v, _ := h.Service.Get(context.Background(), arActor, sid)
		if run(&v, rid).Status == "cancelled" {
			break
		}
		if time.Now().After(deadline) {
			t.Fatal(v.Runs)
		}
		time.Sleep(time.Millisecond)
	}
	arHTTP(t, h, "GET", base+"/events?page_size=100", nil, "", "EventPage", 200)
}
func TestAR1ModelUnknownAndPartialAccountingStayExplicit(t *testing.T) {
	t.Run("unknown", func(t *testing.T) {
		h, m, _ := setupAR(t, func(_ context.Context, r Request, _ func(string) error) (Response, error) {
			return Response{RequestID: r.RequestID, OutcomeUnknown: true}, errors.New("submission ACK lost")
		}, nil)
		sid, etag := arCreateSession(t, h)
		rid := arSubmit(t, h, sid, etag, arInput("chat"))
		if e := h.Service.Drive(context.Background(), arActor, sid, rid); e != nil {
			t.Fatal(e)
		}
		body := arDecode(t, arHTTP(t, h, "GET", "sessions/"+sid+"/runs/"+rid, nil, "", "Run", 200))
		if body["state"] != "needs_confirmation" || body["aggregation_complete"] != false {
			t.Fatal(body)
		}
		w := arHTTP(t, h, "GET", "sessions/"+sid, nil, "", "Snapshot", 200)
		arHTTP(t, h, "POST", "sessions/"+sid+"/runs", arInput("chat"), w.Header().Get("ETag"), "Error", 409)
		if m.calls.Load() != 1 {
			t.Fatal(m.calls.Load())
		}
	})
	t.Run("partial", func(t *testing.T) {
		h, _, _ := setupAR(t, func(_ context.Context, r Request, _ func(string) error) (Response, error) {
			return Response{RequestID: r.RequestID, TerminalConfirmed: true, Finish: "stop", Usage: Usage{Currency: "TST", Groups: []ARUsageGroup{{Currency: "TST", Price: "controlled-v1", KnownTokens: "3", HeldTokens: "7", InflightTokens: "0", KnownMoney: "1", HeldMoney: "2", InflightMoney: "0"}}}}, nil
		}, nil)
		sid, etag := arCreateSession(t, h)
		rid := arSubmit(t, h, sid, etag, arInput("chat"))
		_ = h.Service.Drive(context.Background(), arActor, sid, rid)
		body := arDecode(t, arHTTP(t, h, "GET", "sessions/"+sid+"/runs/"+rid, nil, "", "Run", 200))
		g := body["usage_groups"].([]any)[0].(map[string]any)
		if body["aggregation_complete"] != false || g["known_tokens"] != "3" || g["held_tokens"] != "7" {
			t.Fatal(body)
		}
	})
}
func TestAR1ContextAndNoProgressLimitsStopNewChildren(t *testing.T) {
	t.Run("context", func(t *testing.T) {
		h, m, _ := setupAR(t, arPlain, nil)
		h.Service.CountContext = func(context.Context, Request) (int64, error) { return 1000000, nil }
		sid, etag := arCreateSession(t, h)
		rid := arSubmit(t, h, sid, etag, arInput("chat"))
		_ = h.Service.Drive(context.Background(), arActor, sid, rid)
		v, _ := h.Service.Get(context.Background(), arActor, sid)
		if got := run(&v, rid); got.Reason != "context_limit" || len(got.Steps) != 0 || m.calls.Load() != 0 {
			t.Fatal(got)
		}
	})
	t.Run("no_progress", func(t *testing.T) {
		h, m, _ := setupAR(t, func(_ context.Context, r Request, _ func(string) error) (Response, error) {
			return Response{RequestID: r.RequestID, TerminalConfirmed: true, Finish: "tool_calls", Usage: arUsage(), Calls: []Call{{ID: uuid.NewString(), Name: "bounded_arithmetic", Arguments: json.RawMessage(`{"a":6,"b":7,"op":"multiply"}`)}}}, nil
		}, nil)
		sid, etag := arCreateSession(t, h)
		in := arInput("agent")
		in.Limits.NoProgress = 1
		rid := arSubmit(t, h, sid, etag, in)
		if e := h.Service.Drive(context.Background(), arActor, sid, rid); e != nil {
			t.Fatal(e)
		}
		v, _ := h.Service.Get(context.Background(), arActor, sid)
		if got := run(&v, rid); got.Reason != "no_progress_limit" || m.calls.Load() != 2 {
			t.Fatal(got)
		}
	})
	t.Run("revocation", func(t *testing.T) {
		h, m, auth := setupAR(t, arPlain, nil)
		sid, etag := arCreateSession(t, h)
		rid := arSubmit(t, h, sid, etag, arInput("chat"))
		auth.mu.Lock()
		auth.p.Revision = "revoked"
		auth.mu.Unlock()
		_ = h.Service.Drive(context.Background(), arActor, sid, rid)
		v, _ := h.Service.Get(context.Background(), arActor, sid)
		if run(&v, rid).Reason != "authorization_changed" || m.calls.Load() != 0 {
			t.Fatal(v.Runs)
		}
	})
}
func TestAR1RegenerateAndStableSessionPagination(t *testing.T) {
	h, _, _ := setupAR(t, arPlain, nil)
	for i := 0; i < 3; i++ {
		arCreateSession(t, h)
	}
	page := arDecode(t, arHTTP(t, h, "GET", "sessions?page_size=1", nil, "", "ConversationPage", 200))
	cursor := page["next_cursor"].(string)
	// Created timestamps may tie; delete the actual first page item rather than
	// assuming creation call order overrides the UUID tie-breaker.
	first := page["data"].([]any)[0].(map[string]any)["id"].(string)
	arHTTP(t, h, "DELETE", "sessions/"+first, nil, "\"1\"", "", 204)
	next := arDecode(t, arHTTP(t, h, "GET", "sessions?page_size=100&cursor="+cursor, nil, "", "ConversationPage", 200))
	if len(next["data"].([]any)) != 2 {
		t.Fatal("deletion skipped next Session", next)
	}
	second := next["data"].([]any)[0].(map[string]any)["id"].(string)
	w := arHTTP(t, h, "GET", "sessions/"+second, nil, "", "Snapshot", 200)
	rid := arSubmit(t, h, second, w.Header().Get("ETag"), arInput("chat"))
	_ = h.Service.Drive(context.Background(), arActor, second, rid)
	v, _ := h.Service.Get(context.Background(), arActor, second)
	assistant := v.Messages[len(v.Messages)-1].ID
	in := arInput("chat")
	in.Operation = "regenerate"
	in.Text = nil
	in.Reference = &assistant
	newRun := arSubmit(t, h, second, fmtRevision(v.Revision), in)
	if e := h.Service.Drive(context.Background(), arActor, second, newRun); e != nil {
		t.Fatal(e)
	}
	v, _ = h.Service.Get(context.Background(), arActor, second)
	if v.Messages[len(v.Messages)-1].ParentID != assistant || len(v.Runs) != 2 {
		t.Fatal(v.Messages)
	}
}
func fmtRevision(n int64) string { return "\"" + decimal(n) + "\"" }

func TestAR1UnconfirmedTerminalNeverDispatchesTools(t *testing.T) {
	tool := controlledTool(false)
	h, model, _ := setupAR(t, func(_ context.Context, r Request, _ func(string) error) (Response, error) {
		return Response{RequestID: r.RequestID, Finish: "tool_calls", TerminalConfirmed: false, Usage: arUsage(), Calls: []Call{{ID: "unconfirmed", Name: tool.Spec().Name, Arguments: json.RawMessage(`{}`)}}}, nil
	}, nil, tool)
	sid, etag := arCreateSession(t, h)
	in := arInput("agent")
	in.Tools = []ARToolRef{{Name: tool.Spec().Name, Revision: "1"}}
	rid := arSubmit(t, h, sid, etag, in)
	if e := h.Service.Drive(context.Background(), arActor, sid, rid); e != nil {
		t.Fatal(e)
	}
	v, _ := h.Service.Get(context.Background(), arActor, sid)
	if run(&v, rid).Status != "needs_confirmation" || tool.calls.Load() != 0 || model.calls.Load() != 1 {
		t.Fatal(v.Runs)
	}
}

func TestAR1FailedChildKeepsAuthoritativeKnownUsage(t *testing.T) {
	h, model, _ := setupAR(t, func(_ context.Context, r Request, _ func(string) error) (Response, error) {
		return Response{RequestID: r.RequestID, TerminalConfirmed: true, Usage: arUsage()}, errors.New("confirmed failed child")
	}, nil)
	sid, etag := arCreateSession(t, h)
	rid := arSubmit(t, h, sid, etag, arInput("chat"))
	if e := h.Service.Drive(context.Background(), arActor, sid, rid); e != nil {
		t.Fatal(e)
	}
	body := arDecode(t, arHTTP(t, h, "GET", "sessions/"+sid+"/runs/"+rid, nil, "", "Run", 200))
	groups := body["usage_groups"].([]any)
	if body["state"] != "failed" || len(groups) != 1 || groups[0].(map[string]any)["known_tokens"] != "10" || model.calls.Load() != 1 {
		t.Fatal(body)
	}
}
func TestAR1SequenceKeepsDecimalPrecision(t *testing.T) {
	h, _, _ := setupAR(t, arPlain, nil)
	sid, etag := arCreateSession(t, h)
	rid := arSubmit(t, h, sid, etag, arInput("chat"))
	_, e := h.Service.mutate(context.Background(), arActor, sid, func(v *Session) error { run(v, rid).AR.Seq = 9007199254740993; return nil })
	if e != nil {
		t.Fatal(e)
	}
	if e = h.Service.Drive(context.Background(), arActor, sid, rid); e != nil {
		t.Fatal(e)
	}
	body := arHTTP(t, h, "GET", "sessions/"+sid+"/runs/"+rid+"/events?page_size=100", nil, "", "EventPage", 200).Body.String()
	if !strings.Contains(body, `"seq":"9007199254740994"`) {
		t.Fatal(body)
	}
}
