//go:build agentcontrolled

// This executable is an explicit controlled-model development example. It has
// no network/provider client and is excluded from ordinary production builds.
package main

import (
	"context"
	"encoding/json"
	"flag"
	"fmt"
	"os"
	"time"

	a "github.com/jianzi123/maas/internal/agentruntime"
)

type controlledModel struct{}

func (controlledModel) Supports(_ context.Context, m a.Model) error {
	if m.Source != "controlled-local" || m.Revision != "1" || (m.Protocol != "tools-v1" && m.Protocol != "text-v1") {
		return a.ErrCapability
	}
	return nil
}
func (controlledModel) Generate(_ context.Context, r a.Request, emit func(string) error) (a.Response, error) {
	t, m := int64(10), int64(1)
	response := a.Response{RequestID: r.RequestID, TerminalConfirmed: true, Usage: a.Usage{Tokens: &t, Money: &m, Currency: "TST"}}
	response.Usage.Complete = true
	response.Usage.Groups = []a.ARUsageGroup{{Currency: "TST", Price: "controlled-v1", KnownTokens: "10", KnownMoney: "1", HeldTokens: "0", InflightTokens: "0", HeldMoney: "0", InflightMoney: "0"}}
	if r.Model.Protocol == "text-v1" {
		if e := emit("Controlled Chat response."); e != nil {
			return response, e
		}
		response.Finish = "stop"
		return response, nil
	}
	for _, msg := range r.Messages {
		if msg.Role == "tool" && msg.Parts[0].Name == "list_visible_models" {
			if e := emit("6 × 7 = 42; directory is visible only to the authenticated owner."); e != nil {
				return response, e
			}
			response.Finish = "stop"
			return response, nil
		}
	}
	response.Finish = "tool_calls"
	response.Calls = []a.Call{{ID: "demo-calculate", Name: "bounded_arithmetic", Arguments: json.RawMessage(`{"a":6,"b":7,"op":"multiply"}`)}, {ID: "demo-catalog", Name: "list_visible_models", Arguments: json.RawMessage(`{}`)}}
	return response, nil
}
func main() {
	if e := execute(); e != nil {
		fmt.Fprintln(os.Stderr, e)
		os.Exit(1)
	}
}
func execute() error {
	dir := flag.String("state-dir", "", "explicit local development state directory")
	listen := flag.String("listen", "", "optional loopback AR-1 server, for example 127.0.0.1:4188")
	owner := flag.String("owner-id", "", "stable local test principal UUID; required for HTTP mode")
	contract := flag.String("contract", "docs/contracts/agent-runtime/ar1-draft2/openapi.json", "locked AR-1 draft2 contract file")
	flag.Parse()
	if *dir == "" {
		return a.ErrInvalid
	}
	store, e := a.OpenLocalStore(*dir)
	if e != nil {
		return e
	}
	defer store.Close()
	if *listen != "" {
		return serveAR(*listen, *owner, *contract, *dir, store)
	}
	tools, e := a.NewRegistry(a.Calculator{}, a.ModelDirectory{Read: func(_ context.Context, p a.Principal) ([]string, error) {
		return []string{p.ID + "/controlled-model"}, nil
	}})
	if e != nil {
		return e
	}
	limits := a.Limits{Currency: "TST", Steps: 4, Calls: 4, Tokens: 100, Money: 100, Duration: 10 * time.Second, ToolTimeout: time.Second, ApprovalTTL: time.Minute, InputBytes: 32768, OutputBytes: 8192, Events: 500}
	s, e := a.NewService(store, controlledModel{}, tools, limits)
	if e != nil {
		return e
	}
	p := a.Principal{ID: "local-demo-owner", Revision: "controlled-auth-v1", Permissions: map[string]bool{"tools.calculate": true, "models.read": true}}
	ctx := context.Background()
	v, e := s.Create(ctx, p, "controlled model / real pure and read tools")
	if e != nil {
		return e
	}
	r, e := s.Submit(ctx, p, v.ID, a.Submit{ClientID: "demo-input", Text: "Multiply 6 by 7 and list my visible models", Mode: "agent", Model: a.Model{Alias: "demo", Source: "controlled-local", Revision: "1", Protocol: "tools-v1"}})
	if e != nil {
		return e
	}
	if e = s.Drive(ctx, p, v.ID, r.ID); e != nil {
		return e
	}
	events, e := s.Events(ctx, p, v.ID, r.ID, 0)
	if e != nil {
		return e
	}
	enc := json.NewEncoder(os.Stdout)
	for _, ev := range events {
		if e = enc.Encode(ev); e != nil {
			return e
		}
	}
	return nil
}
