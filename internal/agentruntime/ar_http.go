package agentruntime

import (
	"bytes"
	"context"
	"crypto/hmac"
	"crypto/sha256"
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"sort"
	"strconv"
	"strings"
	"time"

	"github.com/google/uuid"
	"github.com/jianzi123/maas/internal/protocol"
	"github.com/santhosh-tekuri/jsonschema/v5"
)

// Catalog resolves only current authorized metadata. Browser input never supplies
// trusted source/profile/capability approval, credentials or protocol selection.
type ARCatalog interface {
	Resolve(context.Context, Principal, string, string) (Model, error)
	Modes(context.Context, Principal) ([]map[string]any, error)
}
type ARHandler struct {
	Service      *Service
	Auth         Authenticator
	Catalog      ARCatalog
	Policy       ARLimits
	Dispatch     func(Principal, string, string) error
	StreamWindow time.Duration
	key          []byte
	schemas      map[string]*jsonschema.Schema
}

func NewARHandler(s *Service, auth Authenticator, catalog ARCatalog, policy ARLimits, key, contract []byte, stream time.Duration) (*ARHandler, error) {
	if s == nil || auth == nil || catalog == nil || len(key) < 32 || stream <= 0 || stream > time.Minute {
		return nil, ErrInvalid
	}
	c := jsonschema.NewCompiler()
	c.AssertFormat = true
	if e := c.AddResource("https://maas.invalid/ar1.json", bytes.NewReader(contract)); e != nil {
		return nil, e
	}
	var root struct {
		Info struct {
			Version string `json:"version"`
		}
		Components struct {
			Schemas map[string]any `json:"schemas"`
		} `json:"components"`
	}
	if json.Unmarshal(contract, &root) != nil || root.Info.Version != "1.0.0-draft.2" {
		return nil, ErrInvalid
	}
	h := &ARHandler{Service: s, Auth: auth, Catalog: catalog, Policy: policy, key: append([]byte{}, key...), StreamWindow: stream, schemas: map[string]*jsonschema.Schema{}}
	for name := range root.Components.Schemas {
		schema, e := c.Compile("https://maas.invalid/ar1.json#/components/schemas/" + name)
		if e != nil {
			return nil, e
		}
		h.schemas[name] = schema
	}
	if h.Validate("RunLimits", policy) != nil || policy.Calls > s.Limits.Calls || policy.Steps > s.Limits.Steps || policy.OutputBytes > s.Limits.OutputBytes || time.Duration(policy.Duration)*time.Millisecond > s.Limits.Duration || time.Duration(policy.ToolTimeout)*time.Millisecond > s.Limits.ToolTimeout || checkARLimits(policy, ARLimits{Steps: s.Limits.Steps, Calls: s.Limits.Calls, Tools: policy.Tools, Duration: policy.Duration, ToolTimeout: policy.ToolTimeout, OutputBytes: s.Limits.OutputBytes, ContextTokens: policy.ContextTokens, NoProgress: policy.NoProgress, Tokens: decimal(s.Limits.Tokens), Money: decimal(s.Limits.Money), Currency: s.Limits.Currency}) != nil {
		return nil, ErrInvalid
	}
	return h, nil
}
func (h *ARHandler) Validate(name string, value any) error {
	b, e := json.Marshal(value)
	if e != nil {
		return e
	}
	var generic any
	d := json.NewDecoder(bytes.NewReader(b))
	d.UseNumber()
	if e = d.Decode(&generic); e != nil {
		return e
	}
	schema := h.schemas[name]
	if schema == nil {
		return ErrInvalid
	}
	return schema.Validate(generic)
}
func (h *ARHandler) pageToken(p Principal, path string, index any) string {
	b, _ := json.Marshal([]any{p.ID, p.Revision, path, index})
	encoded := base64.RawURLEncoding.EncodeToString(b)
	m := hmac.New(sha256.New, h.key)
	_, _ = m.Write([]byte(encoded))
	return encoded + "." + base64.RawURLEncoding.EncodeToString(m.Sum(nil))
}
func (h *ARHandler) pageIndex(p Principal, path, token string, revision int64) (int, error) {
	if token == "" {
		return 0, nil
	}
	value, e := h.pageValue(p, path, token)
	if e != nil {
		return 0, e
	}
	// Valid old position-only tokens have no provable document watermark.
	var legacy int
	if json.Unmarshal(value, &legacy) == nil && legacy >= 0 {
		return 0, arFailure(410, "cursor_expired")
	}
	var position []int64
	if json.Unmarshal(value, &position) != nil || len(position) != 2 || position[0] < 1 || position[1] < 0 {
		return 0, ErrInvalid
	}
	if position[0] != revision {
		return 0, arFailure(410, "cursor_expired")
	}
	return int(position[1]), nil
}
func (h *ARHandler) pageValue(p Principal, path, token string) (json.RawMessage, error) {
	if len(token) > 4096 {
		return nil, ErrInvalid
	}
	parts := strings.Split(token, ".")
	if len(parts) != 2 {
		return nil, ErrInvalid
	}
	mac, e := base64.RawURLEncoding.DecodeString(parts[1])
	if e != nil {
		return nil, ErrInvalid
	}
	m := hmac.New(sha256.New, h.key)
	_, _ = m.Write([]byte(parts[0]))
	if !hmac.Equal(mac, m.Sum(nil)) {
		return nil, ErrInvalid
	}
	b, e := base64.RawURLEncoding.DecodeString(parts[0])
	if e != nil {
		return nil, ErrInvalid
	}
	var values []json.RawMessage
	if json.Unmarshal(b, &values) != nil || len(values) != 4 {
		return nil, ErrInvalid
	}
	var id, rev, storedPath string
	if json.Unmarshal(values[0], &id) != nil || json.Unmarshal(values[1], &rev) != nil || json.Unmarshal(values[2], &storedPath) != nil || id != p.ID || rev != p.Revision || storedPath != path {
		return nil, ErrInvalid
	}
	return values[3], nil
}
func (h *ARHandler) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	requestID := uuid.NewString()
	w.Header().Set("Cache-Control", "no-store")
	w.Header().Set("Content-Type", "application/json")
	w.Header().Set("X-Request-ID", requestID)
	fail := func(err error) {
		status, code := 503, "dependency_unavailable"
		var ar *arError
		if errors.As(err, &ar) {
			status, code = ar.Status, ar.Code
		} else {
			switch {
			case errors.Is(err, ErrNotFound):
				status, code = 404, "not_found"
			case errors.Is(err, ErrForbidden):
				status, code = 403, "forbidden"
			case errors.Is(err, ErrInvalid):
				status, code = 400, "invalid_request"
			case errors.Is(err, ErrConflict):
				status, code = 409, "state_conflict"
			case errors.Is(err, ErrCapability):
				status, code = 422, "capability_unsupported"
			}
		}
		w.WriteHeader(status)
		_ = json.NewEncoder(w).Encode(map[string]any{"error": map[string]any{"code": code, "message": code, "http_request_id": requestID, "run_id": nil, "child_request_id": nil, "retryable": r.Method == "GET" && status == 503, "snapshot_required": status == 410}})
	}
	if h.Service == nil || h.Auth == nil || h.Catalog == nil || h.schemas == nil {
		fail(ErrUnavailable)
		return
	}
	p, e := h.Auth.Authenticate(r, r.Method != "GET")
	if e != nil || p.ID == "" || p.Revision == "" {
		if e != nil && e.Error() == "unauthenticated" {
			fail(arFailure(401, "unauthenticated"))
			return
		}
		fail(ErrForbidden)
		return
	}
	if _, e = uuid.Parse(p.ID); e != nil {
		fail(ErrForbidden)
		return
	}
	path := strings.TrimPrefix(r.URL.Path, "/api/agent/v1/")
	if path == r.URL.Path {
		fail(ErrNotFound)
		return
	}
	parts := strings.Split(path, "/")
	write := func(schema string, status int, value any) {
		if h.Validate(schema, value) != nil {
			fail(ErrUnavailable)
			return
		}
		w.WriteHeader(status)
		_ = json.NewEncoder(w).Encode(value)
	}
	decode := func(schema string, out any) (string, error) {
		b, e := io.ReadAll(http.MaxBytesReader(w, r.Body, 1<<20))
		if e != nil {
			return "", ErrInvalid
		}
		canonical, e := protocol.Canonical(b)
		if e != nil {
			return "", ErrInvalid
		}
		var value any
		d := json.NewDecoder(bytes.NewReader(canonical))
		d.UseNumber()
		if d.Decode(&value) != nil || h.schemas[schema].Validate(value) != nil || json.Unmarshal(canonical, out) != nil {
			return "", ErrInvalid
		}
		return rawHash(canonical), nil
	}
	pageSize := 20
	if values, ok := r.URL.Query()["page_size"]; ok {
		if len(values) != 1 {
			fail(ErrInvalid)
			return
		}
		pageSize, e = strconv.Atoi(values[0])
		if e != nil || pageSize < 1 || pageSize > 100 {
			fail(ErrInvalid)
			return
		}
	}
	page := func(schema string, data []any, revision int64) {
		index, e := h.pageIndex(p, r.URL.Path, r.URL.Query().Get("cursor"), revision)
		if e != nil {
			fail(e)
			return
		}
		if index > len(data) {
			fail(ErrInvalid)
			return
		}
		end := index + pageSize
		if end > len(data) {
			end = len(data)
		}
		var next any
		if end < len(data) {
			next = h.pageToken(p, r.URL.Path, []int64{revision, int64(end)})
		}
		write(schema, 200, map[string]any{"data": data[index:end], "next_cursor": next})
	}
	if path == "capabilities" && r.Method == "GET" {
		modes, e := h.Catalog.Modes(r.Context(), p)
		if e != nil {
			fail(e)
			return
		}
		tools := []any{}
		for _, spec := range h.Service.Tools.Specs(p) {
			tools = append(tools, arManifest(spec, h.Service.Limits))
		}
		write("Capabilities", 200, map[string]any{"protocol_revision": "ar.api/1.0", "event_versions": []string{ARVersion}, "model_modes": modes, "tools": tools, "attachments_enabled": false})
		return
	}
	if len(parts) == 2 && parts[0] == "session-creation-commands" && r.Method == "GET" {
		if _, e := uuid.Parse(parts[1]); e != nil {
			fail(ErrInvalid)
			return
		}
		v, e := h.Service.Store.Get(r.Context(), creationID(p, parts[1]))
		if e != nil {
			fail(e)
			return
		}
		if v.Owner != p.ID || v.AR == nil {
			fail(ErrNotFound)
			return
		}
		write("SessionCreationCommand", 200, creationCommand(v))
		return
	}
	if path == "sessions" {
		switch r.Method {
		case "POST":
			var in ARCreate
			hash, e := decode("ConversationCreate", &in)
			if e != nil {
				fail(e)
				return
			}
			v, e := h.Service.Store.Get(r.Context(), creationID(p, in.OperationID))
			if errors.Is(e, ErrNotFound) {
				if _, e = h.Catalog.Resolve(r.Context(), p, in.Alias, "chat"); e != nil {
					fail(e)
					return
				}
			} else if e != nil {
				fail(e)
				return
			}
			_ = v
			v, created, e := h.Service.createAR(r.Context(), p, in, hash)
			if e != nil {
				fail(e)
				return
			}
			w.Header().Set("ETag", fmt.Sprintf("\"%d\"", v.Revision))
			status := 200
			if created {
				status = 201
			}
			write("Conversation", status, arConversation(v))
			return
		case "GET":
			all, e := h.Service.List(r.Context(), p)
			if e != nil {
				fail(e)
				return
			}
			visible := []Session{}
			for _, v := range all {
				if v.AR != nil {
					visible = append(visible, v)
				}
			}
			sort.Slice(visible, func(i, j int) bool { return conversationPosition(visible[i]) < conversationPosition(visible[j]) })
			after := ""
			if token := r.URL.Query().Get("cursor"); token != "" {
				value, e := h.pageValue(p, r.URL.Path, token)
				if e != nil || json.Unmarshal(value, &after) != nil {
					fail(ErrInvalid)
					return
				}
			}
			data := []any{}
			var next any
			last := ""
			for _, v := range visible {
				position := conversationPosition(v)
				if position <= after {
					continue
				}
				if len(data) == pageSize {
					next = h.pageToken(p, r.URL.Path, last)
					break
				}
				data = append(data, arConversation(v))
				last = position
			}
			write("ConversationPage", 200, map[string]any{"data": data, "next_cursor": next})
			return
		}
		fail(ErrNotFound)
		return
	}
	if len(parts) < 2 || parts[0] != "sessions" {
		fail(ErrNotFound)
		return
	}
	sid := parts[1]
	v, e := h.Service.Get(r.Context(), p, sid)
	if e != nil {
		fail(e)
		return
	}
	if v.AR == nil {
		fail(ErrNotFound)
		return
	}
	w.Header().Set("ETag", fmt.Sprintf("\"%d\"", v.Revision))
	if len(parts) == 2 {
		switch r.Method {
		case "GET":
			messages := []any{}
			for _, m := range v.Messages {
				messages = append(messages, arMessage(v, m))
			}
			runs := []any{}
			var current *Run
			for i := range v.Runs {
				runs = append(runs, arRun(v, v.Runs[i]))
				current = &v.Runs[i]
			}
			if len(runs) > 100 {
				runs = runs[len(runs)-100:]
			}
			var resume, eventRun, next any
			seq := "0"
			if current != nil {
				resume = current.AR.Cursor
				eventRun = current.ID
				seq = decimal(current.AR.Seq)
			}
			if len(messages) > 100 {
				next = h.pageToken(p, "/api/agent/v1/sessions/"+sid+"/messages", []int64{v.Revision, 100})
				messages = messages[:100]
			}
			write("Snapshot", 200, map[string]any{"conversation": arConversation(v), "messages": messages, "runs": runs, "last_event_seq": seq, "event_run_id": eventRun, "resume_cursor": resume, "messages_next_cursor": next})
			return
		case "PATCH", "DELETE":
			expected, e := revision(r.Header.Get("If-Match"))
			if e != nil {
				fail(e)
				return
			}
			title := v.Title
			if r.Method == "PATCH" {
				var in struct {
					Title string `json:"title"`
				}
				if _, e = decode("ConversationRename", &in); e != nil {
					fail(e)
					return
				}
				title = in.Title
			}
			updated, e := h.Service.mutate(r.Context(), p, sid, func(v *Session) error {
				if v.Revision != expected {
					return arFailure(409, "revision_conflict")
				}
				if r.Method == "DELETE" {
					for _, run := range v.Runs {
						if !terminal(run.Status) {
							return arFailure(409, "conversation_busy")
						}
					}
					now := time.Now().UTC()
					v.Deleted = true
					v.AR.Deleted = &now
				}
				v.Title = title
				return nil
			})
			if e != nil {
				fail(e)
				return
			}
			w.Header().Set("ETag", fmt.Sprintf("\"%d\"", updated.Revision))
			if r.Method == "DELETE" {
				w.WriteHeader(204)
			} else {
				write("Conversation", 200, arConversation(updated))
			}
			return
		}
		fail(ErrNotFound)
		return
	}
	if len(parts) == 3 && parts[2] == "messages" && r.Method == "GET" {
		data := []any{}
		for _, m := range v.Messages {
			data = append(data, arMessage(v, m))
		}
		page("MessagePage", data, v.Revision)
		return
	}
	if len(parts) == 4 && parts[2] == "commands" && r.Method == "GET" {
		for _, run := range v.Runs {
			if run.ClientID == parts[3] {
				write("Command", 200, command(v, run))
				return
			}
		}
		fail(ErrNotFound)
		return
	}
	if len(parts) == 3 && parts[2] == "runs" && r.Method == "POST" {
		var in ARRunCreate
		hash, e := decode("RunCreate", &in)
		if e != nil {
			fail(e)
			return
		}
		value, e := h.submit(r.Context(), p, sid, r.Header.Get("If-Match"), in, hash)
		if e != nil {
			fail(e)
			return
		}
		conversation := value["conversation"].(map[string]any)
		w.Header().Set("ETag", "\""+conversation["revision"].(string)+"\"")
		write("RunAccepted", 202, value)
		return
	}
	if len(parts) < 4 || parts[2] != "runs" {
		fail(ErrNotFound)
		return
	}
	rid := parts[3]
	current := run(&v, rid)
	if current == nil || current.AR == nil {
		fail(ErrNotFound)
		return
	}
	if len(parts) == 4 && r.Method == "GET" {
		write("Run", 200, arRun(v, *current))
		return
	}
	if len(parts) == 5 && r.Method == "GET" {
		switch parts[4] {
		case "steps":
			data := []any{}
			for _, st := range current.Steps {
				data = append(data, arStep(*current, st))
			}
			page("StepPage", data, v.Revision)
			return
		case "tool-calls":
			data := []any{}
			for _, st := range current.Steps {
				for _, call := range st.Calls {
					data = append(data, arCall(*current, st, call))
				}
			}
			page("ToolCallPage", data, v.Revision)
			return
		case "checkpoint":
			write("Checkpoint", 200, arCheckpoint(v, *current))
			return
		}
	}
	if len(parts) == 5 && parts[4] == "cancel" && r.Method == "POST" {
		if e = h.Service.Cancel(r.Context(), p, sid, rid); e != nil {
			fail(e)
			return
		}
		v, e = h.Service.Get(r.Context(), p, sid)
		if e != nil {
			fail(e)
			return
		}
		write("Run", 202, arRun(v, *run(&v, rid)))
		return
	}
	if len(parts) >= 6 && parts[4] == "approvals" {
		call, _ := findCall(current, parts[5])
		if call == nil || call.ApprovalID != parts[5] || call.ApprovalExpires.IsZero() {
			fail(ErrNotFound)
			return
		}
		if len(parts) == 6 && r.Method == "GET" {
			write("Approval", 200, arApproval(*current, *call))
			return
		}
		if len(parts) == 7 && parts[6] == "decision" && r.Method == "POST" {
			var d ARDecision
			if _, e = decode("ApprovalDecision", &d); e != nil {
				fail(e)
				return
			}
			if e = h.decide(r.Context(), p, sid, rid, parts[5], d); e != nil {
				fail(e)
				return
			}
			v, e = h.Service.Get(r.Context(), p, sid)
			if e != nil {
				fail(e)
				return
			}
			c, _ := findCall(run(&v, rid), parts[5])
			write("Approval", 200, arApproval(*run(&v, rid), *c))
			return
		}
	}
	if r.Method == "GET" && ((len(parts) == 5 && parts[4] == "events") || (len(parts) == 6 && parts[4] == "events" && parts[5] == "stream")) {
		after := r.URL.Query().Get("after")
		header := r.Header.Get("Last-Event-ID")
		if len(r.URL.Query()["after"]) > 1 || len(r.Header.Values("Last-Event-ID")) > 1 || (after != "" && header != "") {
			fail(ErrInvalid)
			return
		}
		if len(parts) == 5 && header != "" {
			fail(ErrInvalid)
			return
		}
		if header != "" {
			after = header
		}
		events, e := arEvents(v, *current, after)
		if e != nil {
			fail(e)
			return
		}
		if len(parts) == 5 {
			end := len(events)
			var next any
			if end > pageSize {
				end = pageSize
				next = events[end-1].Cursor
			}
			write("EventPage", 200, map[string]any{"data": events[:end], "next_cursor": next})
			return
		}
		w.Header().Set("Content-Type", "text/event-stream")
		w.Header().Set("X-Accel-Buffering", "no")
		deadline := time.NewTimer(h.StreamWindow)
		defer deadline.Stop()
		tick := time.NewTicker(50 * time.Millisecond)
		defer tick.Stop()
		for {
			for _, ev := range events {
				b, _ := json.Marshal(ev)
				if _, e = fmt.Fprintf(w, "id: %s\nevent: %s\ndata: %s\n\n", ev.Cursor, ev.Type, b); e != nil {
					return
				}
				after = ev.Cursor
			}
			if f, ok := w.(http.Flusher); ok {
				f.Flush()
			}
			if terminal(current.Status) || current.Status == "needs_confirmation" {
				return
			}
			select {
			case <-r.Context().Done():
				return
			case <-deadline.C:
				return
			case <-tick.C:
			}
			// Authorization is rechecked while following; revocation closes the stream.
			fresh, e := h.Auth.Authenticate(r, false)
			if e != nil || fresh.ID != p.ID || fresh.Revision != p.Revision {
				return
			}
			v, e = h.Service.Get(r.Context(), p, sid)
			if e != nil {
				return
			}
			current = run(&v, rid)
			if current == nil {
				return
			}
			events, e = arEvents(v, *current, after)
			if e != nil {
				return
			}
		}
	}
	fail(ErrNotFound)
}
func arEvents(v Session, r Run, after string) ([]AREnvelope, error) {
	out := []AREnvelope{}
	found := after == ""
	for _, ev := range v.Events {
		if ev.RunID != r.ID || len(ev.Wire) == 0 {
			continue
		}
		var wire AREnvelope
		if json.Unmarshal(ev.Wire, &wire) != nil {
			return nil, ErrUnavailable
		}
		if found {
			out = append(out, wire)
		} else if wire.Cursor == after {
			found = true
		}
	}
	if !found {
		return nil, ErrInvalid
	}
	return out, nil
}
func conversationPosition(v Session) string {
	return v.AR.Created.UTC().Format("2006-01-02T15:04:05.000000000Z") + "/" + v.ID
}
func arManifest(s ToolSpec, l Limits) map[string]any {
	output := s.OutputSchema
	if len(output) == 0 {
		output = json.RawMessage(`{"type":"string"}`)
	}
	return map[string]any{"name": s.Name, "revision": s.Version, "schema_sha256": rawHash(mustCanonical(s.Schema)), "input_schema": s.Schema, "output_schema": output, "effect": arEffect(s.Effect), "required_scope": []string{s.Permission}, "requires_approval": s.Approval, "timeout_ms": l.ToolTimeout.Milliseconds(), "max_output_bytes": l.OutputBytes}
}
