package agentruntime

import (
	"context"
	"encoding/json"
	"fmt"
	"testing"
	"time"
)

func TestARReviewSnapshotRevisionWatermark(t *testing.T) {
	for _, oldCount := range []int{0, 98, 100, 102} {
		t.Run(fmt.Sprintf("old_messages_%d", oldCount), func(t *testing.T) {
			first, second := make(chan struct{}), make(chan struct{})
			advance, doneModel := make(chan struct{}), make(chan struct{})
			ctx, cancel := context.WithCancel(context.Background())
			defer cancel()
			pause := func(ctx context.Context, r Request, emit func(string) error) (Response, error) {
				if e := emit("你"); e != nil {
					return Response{}, e
				}
				close(first)
				select {
				case <-advance:
				case <-ctx.Done():
					return Response{}, ctx.Err()
				}
				if e := emit("🙂"); e != nil {
					return Response{}, e
				}
				close(second)
				select {
				case <-doneModel:
				case <-ctx.Done():
					return Response{}, ctx.Err()
				}
				return Response{RequestID: r.RequestID, TerminalConfirmed: true, Finish: "stop", Usage: arUsage()}, nil
			}
			h, m, _ := setupAR(t, arPlain, nil)
			h.Service.Limits.Events = 10000
			h.Service.Limits.InputBytes = 1 << 20
			h.Policy.ContextTokens = 1 << 20
			sid, _ := arCreateSession(t, h)
			for i := 0; i < oldCount/2; i++ {
				prior := arHTTP(t, h, "GET", "sessions/"+sid, nil, "", "Snapshot", 200)
				pr := arSubmit(t, h, sid, prior.Header().Get("ETag"), arInput("chat"))
				if e := h.Service.Drive(ctx, arActor, sid, pr); e != nil {
					t.Fatal(e)
				}
			}
			m.f = pause
			beforeCalls := m.calls.Load()
			initial := arHTTP(t, h, "GET", "sessions/"+sid, nil, "", "Snapshot", 200)
			rid := arSubmit(t, h, sid, initial.Header().Get("ETag"), arInput("chat"))
			driven := make(chan error, 1)
			go func() { driven <- h.Service.Drive(ctx, arActor, sid, rid); close(driven) }()
			defer func() {
				cancel()
				select {
				case <-driven:
				case <-time.After(2 * time.Second):
					t.Error("owned drive did not stop")
				}
			}()
			select {
			case <-first:
			case <-time.After(2 * time.Second):
				t.Fatal("first delta absent")
			}
			snapshot := arDecode(t, arHTTP(t, h, "GET", "sessions/"+sid, nil, "", "Snapshot", 200))
			cursor := snapshot["resume_cursor"].(string)
			messages := snapshot["messages"].([]any)
			token, _ := snapshot["messages_next_cursor"].(string)
			if token != "" {
				page := arDecode(t, arHTTP(t, h, "GET", "sessions/"+sid+"/messages?cursor="+token, nil, "", "MessagePage", 200))
				messages = append(messages, page["data"].([]any)...)
			}
			close(advance)
			select {
			case <-second:
			case <-time.After(2 * time.Second):
				t.Fatal("second delta absent")
			}
			if token != "" {
				expired := arDecode(t, arHTTP(t, h, "GET", "sessions/"+sid+"/messages?cursor="+token, nil, "", "Error", 410))["error"].(map[string]any)
				if expired["code"] != "cursor_expired" || expired["snapshot_required"] != true || expired["retryable"] != false {
					t.Fatal(expired)
				}
			}
			fresh := arDecode(t, arHTTP(t, h, "GET", "sessions/"+sid, nil, "", "Snapshot", 200))
			freshMessages := fresh["messages"].([]any)
			freshToken, _ := fresh["messages_next_cursor"].(string)
			if freshToken != "" {
				page := arDecode(t, arHTTP(t, h, "GET", "sessions/"+sid+"/messages?cursor="+freshToken, nil, "", "MessagePage", 200))
				freshMessages = append(freshMessages, page["data"].([]any)...)
			}
			freshText := ""
			for _, raw := range freshMessages {
				msg := raw.(map[string]any)
				if msg["role"] == "assistant" {
					freshText = msg["parts"].([]any)[0].(map[string]any)["text"].(string)
				}
			}
			if freshText != "你🙂" {
				t.Fatal("fresh snapshot lost or repeated text", freshText)
			}
			current, _ := h.Service.Get(ctx, arActor, sid)
			freshReplay := arDecode(t, arHTTP(t, h, "GET", "sessions/"+sid+"/runs/"+rid+"/events?after="+fresh["resume_cursor"].(string), nil, "", "EventPage", 200))
			for _, raw := range freshReplay["data"].([]any) {
				if raw.(map[string]any)["type"] == "message.delta" {
					t.Fatal("fresh snapshot replay duplicated text")
				}
			}
			afterReads, _ := h.Service.Get(ctx, arActor, sid)
			if afterReads.Revision != current.Revision {
				t.Fatal("GET wrote session")
			}
			close(doneModel)
			if e := <-driven; e != nil {
				t.Fatal(e)
			}
			if freshToken != "" {
				arHTTP(t, h, "GET", "sessions/"+sid+"/messages?cursor="+freshToken, nil, "", "Error", 410)
			}
			latest := arHTTP(t, h, "GET", "sessions/"+sid, nil, "", "Snapshot", 200)
			edited := arInput("chat")
			edited.Operation = "edit"
			ref := freshMessages[0].(map[string]any)["id"].(string)
			edited.Reference = &ref
			arSubmit(t, h, sid, latest.Header().Get("ETag"), edited)
			if freshToken != "" {
				arHTTP(t, h, "GET", "sessions/"+sid+"/messages?cursor="+freshToken, nil, "", "Error", 410)
			}
			replay := arDecode(t, arHTTP(t, h, "GET", "sessions/"+sid+"/runs/"+rid+"/events?after="+cursor, nil, "", "EventPage", 200))
			deltas := 0
			for _, raw := range replay["data"].([]any) {
				ev := raw.(map[string]any)
				if ev["type"] == "message.delta" {
					deltas++
					d := ev["data"].(map[string]any)
					if d["offset"] != "3" || d["text"] != "🙂" {
						t.Fatal(d)
					}
				}
			}
			if deltas != 1 || m.calls.Load() != beforeCalls+1 {
				t.Fatal("replay changed work", deltas, m.calls.Load())
			}
			text := ""
			for _, raw := range messages {
				msg := raw.(map[string]any)
				if msg["role"] == "assistant" {
					text = msg["parts"].([]any)[0].(map[string]any)["text"].(string)
				}
			}
			t.Logf("history=%d snapshot_seq=%v tail_text=%q replay_deltas=%d model_calls=%d", oldCount, snapshot["last_event_seq"], text, deltas, m.calls.Load()-beforeCalls)
			if text != "你" {
				t.Fatalf("snapshot pages exceeded captured watermark: got %q, want %q; cursor replay still contains emoji", text, "你")
			}
		})
	}
}

func TestARReviewToolDeadlineRemainsSchemaValid(t *testing.T) {
	for _, cancelEarly := range []bool{false, true} {
		t.Run(fmt.Sprintf("cancel_%t", cancelEarly), func(t *testing.T) {
			entered := make(chan struct{})
			tool := controlledTool(false)
			tool.f = func(ctx context.Context) (string, error) { close(entered); <-ctx.Done(); return "", ctx.Err() }
			h, m, _ := setupAR(t, func(_ context.Context, r Request, _ func(string) error) (Response, error) {
				return Response{RequestID: r.RequestID, TerminalConfirmed: true, Finish: "tool_calls", Calls: []Call{{ID: "source-call-1", Name: "controlled_tool", Arguments: json.RawMessage("{}")}}, Usage: arUsage()}, nil
			}, nil, tool)
			sid, etag := arCreateSession(t, h)
			in := arInput("agent")
			in.Tools = []ARToolRef{{Name: "controlled_tool", Revision: "1"}}
			in.Limits.Duration = 1000
			rid := arSubmit(t, h, sid, etag, in)
			driven := make(chan error, 1)
			go func() { driven <- h.Service.Drive(context.Background(), arActor, sid, rid) }()
			select {
			case <-entered:
			case <-time.After(2 * time.Second):
				t.Fatal("tool not entered")
			}
			if cancelEarly {
				arHTTP(t, h, "POST", "sessions/"+sid+"/runs/"+rid+"/cancel", nil, "", "Run", 202)
			}
			select {
			case e := <-driven:
				if e != nil {
					t.Fatal(e)
				}
			case <-time.After(3 * time.Second):
				t.Fatal("owned drive did not stop")
			}
			v, e := h.Service.Get(context.Background(), arActor, sid)
			if e != nil {
				t.Fatal(e)
			}
			run := run(&v, rid)
			call := run.Steps[0].Calls[0]
			t.Logf("run=%s tool=%s model_calls=%d tool_calls=%d", run.Status, call.State, m.calls.Load(), tool.calls.Load())
			arHTTP(t, h, "GET", "sessions/"+sid+"/runs/"+rid+"/tool-calls", nil, "", "ToolCallPage", 200)
		})
	}
}
