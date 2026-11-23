package agentruntime

import (
	"encoding/json"
	"time"
)

const ARVersion = "ar.session.event/1.0"

type ARLimits struct {
	Steps         int    `json:"max_steps"`
	Calls         int    `json:"max_model_calls"`
	Tools         int    `json:"max_tool_calls"`
	Duration      int    `json:"max_duration_ms"`
	ToolTimeout   int    `json:"tool_timeout_ms"`
	OutputBytes   int    `json:"max_tool_output_bytes"`
	ContextTokens int    `json:"max_context_tokens"`
	NoProgress    int    `json:"no_progress_limit"`
	Tokens        string `json:"max_tokens"`
	Money         string `json:"max_money_atomic"`
	Currency      string `json:"currency"`
}
type ARToolRef struct {
	Name     string `json:"name"`
	Revision string `json:"revision"`
}
type ARRunCreate struct {
	OperationID string      `json:"client_operation_id"`
	Mode        string      `json:"mode"`
	Operation   string      `json:"operation"`
	Text        *string     `json:"text"`
	Reference   *string     `json:"referenced_message_id"`
	Alias       string      `json:"model_alias"`
	Limits      ARLimits    `json:"limits"`
	Tools       []ARToolRef `json:"tools"`
}
type ARCreate struct {
	OperationID string `json:"client_operation_id"`
	Title       string `json:"title"`
	Alias       string `json:"model_alias"`
}
type ARSession struct {
	OperationID string     `json:"operation_id"`
	Hash        string     `json:"sha256"`
	Alias       string     `json:"model_alias"`
	Created     time.Time  `json:"created_at"`
	Updated     time.Time  `json:"updated_at"`
	Deleted     *time.Time `json:"deleted_at"`
}
type ARExecution struct {
	Reference      string      `json:"referenced_message_id,omitempty"`
	Limits         ARLimits    `json:"limits"`
	Tools          []ARToolRef `json:"tools"`
	Operation      string      `json:"operation"`
	Created        time.Time   `json:"created_at"`
	Finished       *time.Time  `json:"finished_at"`
	Fence          int64       `json:"fence"`
	Seq            int64       `json:"seq"`
	Cursor         string      `json:"cursor"`
	ContextHash    string      `json:"context_sha256"`
	RegistryHash   string      `json:"registry_sha256"`
	LastSignature  string      `json:"last_signature,omitempty"`
	NoProgress     int         `json:"no_progress"`
	PolicyRevision string      `json:"policy_revision"`
}
type ARUsageGroup struct {
	Currency       string `json:"currency"`
	Price          string `json:"price_version"`
	KnownTokens    string `json:"known_tokens"`
	HeldTokens     string `json:"held_tokens"`
	InflightTokens string `json:"inflight_tokens"`
	KnownMoney     string `json:"known_money_atomic"`
	HeldMoney      string `json:"held_money_atomic"`
	InflightMoney  string `json:"inflight_money_atomic"`
}
type AREnvelope struct {
	Version   string          `json:"version"`
	ID        string          `json:"id"`
	SessionID string          `json:"session_id"`
	RunID     string          `json:"run_id"`
	Seq       string          `json:"seq"`
	Cursor    string          `json:"cursor"`
	Created   time.Time       `json:"created_at"`
	Type      string          `json:"type"`
	Data      json.RawMessage `json:"data"`
}
type ARDecision struct {
	ID             string `json:"decision_id"`
	Decision       string `json:"decision"`
	ArgsHash       string `json:"args_sha256"`
	ToolRevision   string `json:"tool_revision"`
	PolicyRevision string `json:"policy_revision"`
}
