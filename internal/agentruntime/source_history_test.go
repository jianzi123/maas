package agentruntime

import (
	"encoding/json"
	"testing"
)

func TestToolsHistoryBindsOriginalStepAcrossRestart(t *testing.T) {
	args := json.RawMessage(`{"a":6,"b":7,"op":"multiply"}`)
	r := Run{ID: "run", MessageID: "user", Status: "running", AR: &ARExecution{}, Steps: []Step{{Calls: []Call{{ID: "runtime-uuid", SourceID: "provider-call", Name: "bounded_arithmetic", Arguments: args, State: "completed", Result: "42"}}}}}
	v := Session{Runs: []Run{r}, Messages: []Message{{ID: "user", RunID: r.ID, Role: "user", Parts: []Part{{Type: "text", Text: "compute"}}}, {ID: "assistant", RunID: r.ID, Role: "assistant", Parts: []Part{{Type: "tool_call", CallID: "runtime-uuid", SourceCallID: "untrusted-duplicate", Name: "bounded_arithmetic", Arguments: args}}}, {ID: "tool", RunID: r.ID, Role: "tool", Parts: []Part{{Type: "tool_result", CallID: "runtime-uuid", Name: "bounded_arithmetic", Text: "42"}}}}}
	b, _ := json.Marshal(v)
	var restored Session
	json.Unmarshal(b, &restored)
	messages, e := modelHistory(restored, restored.Runs[0])
	if e != nil || messages[1].Parts[0].SourceCallID != "provider-call" {
		t.Fatal("source identity not restored from Step.Call", messages, e)
	}
	if v.Messages[1].Parts[0].SourceCallID != "untrusted-duplicate" {
		t.Fatal("history projection mutated session without CAS")
	}
	for _, bad := range []string{"missing_record", "pending", "wrong_arguments", "wrong_result", "wrong_run"} {
		t.Run(bad, func(t *testing.T) {
			var copy Session
			json.Unmarshal(b, &copy)
			switch bad {
			case "missing_record":
				copy.Runs[0].Steps = nil
			case "pending":
				copy.Runs[0].Steps[0].Calls[0].State = "pending"
			case "wrong_arguments":
				copy.Messages[1].Parts[0].Arguments = json.RawMessage(`{}`)
			case "wrong_result":
				copy.Messages[2].Parts[0].Text = "forged"
			case "wrong_run":
				copy.Messages[2].RunID = "foreign"
			}
			// A foreign run is excluded from chosen history rather than forwarded.
			msgs, e := modelHistory(copy, copy.Runs[0])
			if bad == "wrong_run" {
				if e == nil && len(msgs) == 3 {
					t.Fatal("foreign result forwarded")
				}
			} else if e == nil {
				t.Fatal("unbound feedback accepted")
			}
		})
	}
}
