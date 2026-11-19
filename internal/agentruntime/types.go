// Package agentruntime implements versioned Chat/Agent execution. Accounting is
// always owned by kernel; these documents contain references and projections only.
package agentruntime

import (
	"context"
	"encoding/json"
	"errors"
	"time"
)

var (
	ErrConflict    = errors.New("state_conflict")
	ErrNotFound    = errors.New("not_found")
	ErrForbidden   = errors.New("forbidden")
	ErrInvalid     = errors.New("invalid_input")
	ErrCapability  = errors.New("model_capability_unavailable")
	ErrUnavailable = errors.New("dependency_unavailable")
)

const Version = "agent-v1"

type Principal struct {
	ID, Revision string
	Permissions  map[string]bool
}
type Model struct {
	Alias    string `json:"alias"`
	Source   string `json:"source_id"`
	Revision string `json:"revision"`
	Protocol string `json:"protocol"` // text-v1 or tools-v1; never inferred
}
type Part struct {
	Type      string          `json:"type"`
	Text      string          `json:"text,omitempty"`
	CallID    string          `json:"call_id,omitempty"`
	Name      string          `json:"name,omitempty"`
	Arguments json.RawMessage `json:"arguments,omitempty"`
}
type Message struct {
	ID       string `json:"id"`
	Role     string `json:"role"`
	RunID    string `json:"run_id"`
	ParentID string `json:"parent_id,omitempty"`
	Parts    []Part `json:"parts"`
}
type Usage struct {
	Tokens   *int64 `json:"tokens"`
	Money    *int64 `json:"money_atomic"`
	Currency string `json:"currency"`
}
type Limits struct {
	Currency    string        `json:"currency"`
	Steps       int           `json:"steps"`
	Calls       int           `json:"model_calls"`
	Tokens      int64         `json:"tokens"`
	Money       int64         `json:"money_atomic"`
	Duration    time.Duration `json:"duration_ns"`
	ToolTimeout time.Duration `json:"tool_timeout_ns"`
	ApprovalTTL time.Duration `json:"approval_ttl_ns"`
	InputBytes  int           `json:"input_bytes"`
	OutputBytes int           `json:"output_bytes"`
	Events      int           `json:"max_events"`
}

func (l Limits) valid() bool {
	return l.Steps > 0 && l.Steps <= 256 && l.Calls > 0 && l.Calls <= 256 && l.Tokens > 0 && l.Tokens <= 9007199254740991 && l.Money > 0 && l.Money <= 9007199254740991 && l.Duration > 0 && l.Duration <= 24*time.Hour && l.ToolTimeout > 0 && l.ApprovalTTL > 0 && l.InputBytes > 0 && l.InputBytes <= 1<<20 && l.OutputBytes > 0 && l.OutputBytes <= 1<<20 && l.Events >= 32 && l.Events <= 100000
}

type Call struct {
	ID              string          `json:"id"`
	Name            string          `json:"name"`
	Arguments       json.RawMessage `json:"arguments"`
	ToolVersion     string          `json:"tool_version"`
	Hash            string          `json:"sha256"`
	State           string          `json:"state"`
	Result          string          `json:"result,omitempty"`
	ApprovalExpires time.Time       `json:"approval_expires_at,omitempty"`
}
type Step struct {
	Number    int    `json:"number"`
	RequestID string `json:"request_id"`
	State     string `json:"state"`
	Calls     []Call `json:"tool_calls"`
	Usage     Usage  `json:"usage"`
}
type Checkpoint struct {
	Phase          string `json:"phase"`
	CompletedSteps int    `json:"completed_steps"`
	PendingCall    string `json:"pending_call,omitempty"`
	RequestID      string `json:"request_id,omitempty"`
}
type Run struct {
	ID              string     `json:"id"`
	MessageID       string     `json:"message_id"`
	ClientID        string     `json:"client_id"`
	InputHash       string     `json:"input_sha256"`
	AuthRevision    string     `json:"auth_revision"`
	Granted         []string   `json:"granted_permissions"`
	Mode            string     `json:"mode"`
	Model           Model      `json:"model"`
	Status          string     `json:"status"`
	Reason          string     `json:"reason,omitempty"`
	CancelRequested bool       `json:"cancel_requested"`
	Executor        string     `json:"executor,omitempty"`
	Deadline        time.Time  `json:"deadline"`
	Limits          Limits     `json:"limits"`
	Steps           []Step     `json:"steps"`
	Checkpoint      Checkpoint `json:"checkpoint"`
	Usage           Usage      `json:"usage"`
}
type Event struct {
	Cursor int64           `json:"cursor"`
	RunID  string          `json:"run_id"`
	Type   string          `json:"type"`
	At     time.Time       `json:"at"`
	Data   json.RawMessage `json:"data"`
}
type Session struct {
	Version  string    `json:"schema_version"`
	ID       string    `json:"id"`
	Owner    string    `json:"owner"`
	Title    string    `json:"title"`
	Deleted  bool      `json:"deleted"`
	Revision int64     `json:"revision"`
	Messages []Message `json:"messages"`
	Runs     []Run     `json:"runs"`
	Events   []Event   `json:"events"`
}

// CompareAndSwap must atomically replace the entire document or return conflict.
// A commit whose outcome is unknown MUST NOT be retried as a generation call.
type SessionStore interface {
	Get(context.Context, string) (Session, error)
	List(context.Context, string) ([]Session, error)
	CompareAndSwap(context.Context, Session, int64) error
}
type Request struct {
	Principal                   Principal
	SessionID, RunID, RequestID string
	Model                       Model
	Messages                    []Message
	Tools                       []ToolSpec
	TokenUpper, MoneyUpper      int64
	Currency                    string
}
type Response struct {
	RequestID string
	Finish    string // stop or tool_calls; EOF is never success
	Calls     []Call
	Usage     Usage
}
type ModelClient interface {
	Supports(context.Context, Model) error
	Generate(context.Context, Request, func(string) error) (Response, error)
}
type ToolSpec struct {
	Name       string          `json:"name"`
	Version    string          `json:"version"`
	Schema     json.RawMessage `json:"parameters"`
	Permission string          `json:"permission"`
	Effect     string          `json:"effect"` // pure, read, write
	Approval   bool            `json:"approval_required"`
}
type Tool interface {
	Spec() ToolSpec
	Execute(context.Context, Principal, string, json.RawMessage) (string, error)
}
type ToolRegistry interface {
	Lookup(string) (Tool, bool)
	Specs(Principal) []ToolSpec
}
type AgentLoop interface {
	Drive(context.Context, Principal, string, string) error
}
type Submit struct {
	ClientID string `json:"client_id"`
	Text     string `json:"text"`
	ParentID string `json:"parent_message_id,omitempty"`
	Mode     string `json:"mode"`
	Model    Model  `json:"model"`
}
