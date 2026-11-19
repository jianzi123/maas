package agentruntime

import (
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"strconv"
	"strings"
)

// Authenticator verifies session, CSRF/origin for mutations and returns trusted
// identity/permissions. No request header/body may directly select a principal.
type Authenticator interface {
	Authenticate(*http.Request, bool) (Principal, error)
}
type Handler struct {
	Service  *Service
	Auth     Authenticator
	Dispatch func(Principal, string, string) error
}

// ServeHTTP exposes a candidate versioned protocol. It never starts execution on
// GET, replay or reconnect. Hosts schedule durable queued runs via the same Drive.
func (h Handler) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Cache-Control", "no-store")
	w.Header().Set("Content-Type", "application/json")
	fail := func(e error) {
		code := 503
		if errors.Is(e, ErrNotFound) {
			code = 404
		}
		if errors.Is(e, ErrInvalid) {
			code = 400
		}
		if errors.Is(e, ErrConflict) {
			code = 409
		}
		if errors.Is(e, ErrForbidden) {
			code = 403
		}
		if errors.Is(e, ErrCapability) {
			code = 422
		}
		reason := "dependency_unavailable"
		if code != 503 {
			reason = e.Error()
		}
		w.WriteHeader(code)
		_ = json.NewEncoder(w).Encode(map[string]any{"error": map[string]any{"code": reason, "retryable": false}})
	}
	if h.Service == nil || h.Auth == nil {
		fail(ErrUnavailable)
		return
	}
	p, e := h.Auth.Authenticate(r, r.Method != "GET")
	if e != nil || p.ID == "" || p.Revision == "" {
		fail(ErrForbidden)
		return
	}
	path := strings.TrimPrefix(r.URL.Path, "/api/agent/v1/")
	if path == r.URL.Path {
		fail(ErrNotFound)
		return
	}
	parts := strings.Split(path, "/")
	decode := func(out any) error {
		r.Body = http.MaxBytesReader(w, r.Body, int64(h.Service.Limits.InputBytes)+4096)
		d := json.NewDecoder(r.Body)
		d.DisallowUnknownFields()
		if d.Decode(out) != nil {
			return ErrInvalid
		}
		if d.Decode(new(any)) != io.EOF {
			return ErrInvalid
		}
		return nil
	}
	respond := func(value any) { _ = json.NewEncoder(w).Encode(value) }
	if len(parts) == 1 && parts[0] == "sessions" {
		switch r.Method {
		case "POST":
			var in struct {
				Title string `json:"title"`
			}
			if e = decode(&in); e != nil {
				fail(e)
				return
			}
			v, e := h.Service.Create(r.Context(), p, in.Title)
			if e != nil {
				fail(e)
				return
			}
			w.WriteHeader(201)
			respond(v)
			return
		case "GET":
			v, e := h.Service.List(r.Context(), p)
			if e != nil {
				fail(e)
				return
			}
			respond(map[string]any{"items": v})
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
	if len(parts) == 2 {
		switch r.Method {
		case "GET":
			v, e := h.Service.Get(r.Context(), p, sid)
			if e != nil {
				fail(e)
				return
			}
			respond(v)
			return
		case "PATCH", "DELETE":
			var in struct {
				Title string `json:"title"`
			}
			if r.Method == "PATCH" {
				if e = decode(&in); e != nil {
					fail(e)
					return
				}
			}
			if e = h.Service.Update(r.Context(), p, sid, in.Title, r.Method == "DELETE"); e != nil {
				fail(e)
				return
			}
			w.WriteHeader(204)
			return
		}
		fail(ErrNotFound)
		return
	}
	if len(parts) == 3 && parts[2] == "runs" && r.Method == "POST" {
		var in Submit
		if e = decode(&in); e != nil {
			fail(e)
			return
		}
		v, e := h.Service.Submit(r.Context(), p, sid, in)
		if e != nil {
			fail(e)
			return
		}
		if h.Dispatch != nil && v.Status == "queued" {
			if e = h.Dispatch(p, sid, v.ID); e != nil {
				fail(e)
				return
			}
		}
		w.WriteHeader(202)
		respond(v)
		return
	}
	if len(parts) < 4 || parts[2] != "runs" {
		fail(ErrNotFound)
		return
	}
	rid := parts[3]
	if len(parts) == 4 && r.Method == "GET" {
		v, e := h.Service.Get(r.Context(), p, sid)
		if e != nil {
			fail(e)
			return
		}
		vRun := run(&v, rid)
		if vRun == nil {
			fail(ErrNotFound)
			return
		}
		respond(vRun)
		return
	}
	if len(parts) == 5 && parts[4] == "cancel" && r.Method == "POST" {
		if e = h.Service.Cancel(r.Context(), p, sid, rid); e != nil {
			fail(e)
			return
		}
		w.WriteHeader(202)
		respond(map[string]any{"cancel_requested": true})
		return
	}
	if len(parts) == 5 && parts[4] == "approvals" && r.Method == "POST" {
		var in struct {
			CallID string `json:"call_id"`
			Hash   string `json:"sha256"`
			Allow  bool   `json:"allow"`
		}
		if e = decode(&in); e != nil {
			fail(e)
			return
		}
		if e = h.Service.Approve(r.Context(), p, sid, rid, in.CallID, in.Hash, in.Allow); e != nil {
			fail(e)
			return
		}
		if in.Allow && h.Dispatch != nil {
			if e = h.Dispatch(p, sid, rid); e != nil {
				fail(e)
				return
			}
		}
		w.WriteHeader(202)
		respond(map[string]bool{"accepted": true})
		return
	}
	if len(parts) == 5 && parts[4] == "events" && r.Method == "GET" {
		cursor := r.URL.Query().Get("after")
		if cursor == "" {
			cursor = r.Header.Get("Last-Event-ID")
		}
		after := int64(0)
		if cursor != "" {
			after, e = strconv.ParseInt(cursor, 10, 64)
			if e != nil {
				fail(ErrInvalid)
				return
			}
		}
		items, e := h.Service.Events(r.Context(), p, sid, rid, after)
		if e != nil {
			fail(e)
			return
		}
		if strings.Contains(r.Header.Get("Accept"), "text/event-stream") {
			w.Header().Set("Content-Type", "text/event-stream")
			for _, x := range items {
				b, _ := json.Marshal(x)
				_, _ = fmt.Fprintf(w, "id: %d\nevent: %s\ndata: %s\n\n", x.Cursor, x.Type, b)
			}
			if f, ok := w.(http.Flusher); ok {
				f.Flush()
			}
			return
		}
		next := after
		if len(items) > 0 {
			next = items[len(items)-1].Cursor
		}
		respond(map[string]any{"items": items, "next_cursor": next})
		return
	}
	fail(ErrNotFound)
}
