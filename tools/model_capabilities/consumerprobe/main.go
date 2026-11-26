// Command consumerprobe exercises existing exported Go contracts. It is not a
// ModelClient implementation, service, provider connector, or settlement client.
package main

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"os"

	a "github.com/jianzi123/maas/internal/agentruntime"
	"github.com/jianzi123/maas/internal/agentruntime/kernelmodel"
	"github.com/jianzi123/maas/internal/kernel"
	"github.com/jianzi123/maas/internal/protocol"
	"github.com/santhosh-tekuri/jsonschema/v5"
)

type input struct {
	Operation   string          `json:"operation"`
	Protocol    string          `json:"protocol,omitempty"`
	Permissions map[string]bool `json:"permissions,omitempty"`
	Calls       []a.Call        `json:"calls,omitempty"`
}

type output struct {
	Status            string       `json:"status"`
	Reason            string       `json:"reason,omitempty"`
	Executions        int          `json:"executions"`
	Results           []string     `json:"results,omitempty"`
	Specs             []a.ToolSpec `json:"specs,omitempty"`
	PrepareCalls      int          `json:"prepare_calls"`
	SupplierCalls     int          `json:"supplier_calls"`
	TerminalConfirmed bool         `json:"terminal_confirmed"`
}

func evaluate(in input) output {
	out := output{Status: "rejected"}
	p := a.Principal{ID: "controlled-probe", Revision: "1", Permissions: in.Permissions}
	registry, err := a.NewRegistry(a.Calculator{}, a.ModelDirectory{Read: func(_ context.Context, p a.Principal) ([]string, error) {
		if !p.Permissions["models.read"] {
			return nil, a.ErrForbidden
		}
		return []string{"controlled-visible-model"}, nil
	}})
	if err != nil {
		out.Reason = err.Error()
		return out
	}
	if in.Operation == "specs" {
		out.Status = "specs"
		out.Specs = registry.Specs(p)
		return out
	}
	if in.Operation == "supports" {
		// An installed Relay pointer and proof hooks isolate the protocol gate. No
		// Generate of text-v1 is permitted by this probe.
		client := kernelmodel.RelayModel{Relay: &kernel.Relay{}, Prepare: func(context.Context, a.Request) (kernel.RelayCall, error) {
			out.PrepareCalls++
			return kernel.RelayCall{}, a.ErrUnavailable
		}, Usage: func(context.Context, string) (a.Usage, error) { return a.Usage{}, a.ErrUnavailable }}
		err = client.Supports(context.Background(), a.Model{Protocol: in.Protocol})
		if err == nil {
			out.Status = "protocol_supported"
		} else {
			out.Reason = err.Error()
		}
		if in.Protocol != "text-v1" {
			response, generateErr := client.Generate(context.Background(), a.Request{Model: a.Model{Protocol: in.Protocol}, RequestID: "controlled-child"}, func(string) error { return nil })
			out.TerminalConfirmed = response.TerminalConfirmed
			if generateErr == nil {
				out.Status = "unexpected_generate_acceptance"
			}
		}
		return out
	}
	if in.Operation != "batch" {
		out.Reason = "unknown_probe_operation"
		return out
	}
	seen := map[string]bool{}
	tools := []a.Tool{}
	for _, call := range in.Calls {
		tool, ok := registry.Lookup(call.Name)
		if !ok {
			out.Reason = "unknown_tool"
			return out
		}
		if !p.Permissions[tool.Spec().Permission] {
			out.Reason = "tool_forbidden"
			return out
		}
		if call.ID == "" || seen[call.ID] {
			out.Reason = "duplicate_or_empty_call_id"
			return out
		}
		seen[call.ID] = true
		if _, err = protocol.Canonical(call.Arguments); err != nil {
			out.Reason = "invalid_or_duplicate_JSON"
			return out
		}
		compiler := jsonschema.NewCompiler()
		if err = compiler.AddResource("inmemory://tool.json", bytes.NewReader(tool.Spec().Schema)); err != nil {
			out.Reason = err.Error()
			return out
		}
		schema, err := compiler.Compile("inmemory://tool.json")
		if err != nil {
			out.Reason = err.Error()
			return out
		}
		var args any
		decoder := json.NewDecoder(bytes.NewReader(call.Arguments))
		decoder.UseNumber()
		if decoder.Decode(&args) != nil || decoder.Decode(new(any)) != io.EOF || schema.Validate(args) != nil {
			out.Reason = "arguments_schema"
			return out
		}
		tools = append(tools, tool)
	}
	for index, call := range in.Calls {
		result, err := tools[index].Execute(context.Background(), p, call.ID, call.Arguments)
		if err != nil {
			out.Reason = err.Error()
			return out
		}
		out.Executions++
		out.Results = append(out.Results, result)
	}
	out.Status = "completed"
	return out
}

func main() {
	decoder := json.NewDecoder(io.LimitReader(os.Stdin, 1<<20))
	decoder.DisallowUnknownFields()
	var in input
	if err := decoder.Decode(&in); err != nil {
		fmt.Fprintln(os.Stderr, "probe input rejected")
		os.Exit(2)
	}
	if decoder.Decode(new(any)) != io.EOF {
		os.Exit(2)
	}
	if err := json.NewEncoder(os.Stdout).Encode(evaluate(in)); err != nil {
		os.Exit(2)
	}
}
