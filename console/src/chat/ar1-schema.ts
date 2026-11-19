export interface paths {
  "/api/agent/v1/capabilities": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get: operations["getChatCapabilities"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/api/agent/v1/sessions": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get: operations["listConversations"];
    put?: never;
    /** @description Persist command key (trusted principal, create-session, client_operation_id), canonical request hash and new Session in the SAME MySQL transaction. Same key/hash returns original Session (201 for initial creation, 200 for known duplicate); different hash returns 409 operation_conflict without mutation. Authorize first. Deleted Session is not recreated by duplicate POST; return 409 state_conflict and recover original command with GET. After unknown ACK or refresh clients GET session-creation-commands/{original operation_id}; never guess by title or automatically POST. Principal is never accepted from body. */
    post: operations["createConversation"];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/api/agent/v1/sessions/{session_id}": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get: operations["getConversationSnapshot"];
    put?: never;
    post?: never;
    delete: operations["deleteConversation"];
    options?: never;
    head?: never;
    patch: operations["renameConversation"];
    trace?: never;
  };
  "/api/agent/v1/sessions/{session_id}/messages": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get: operations["listConversationMessages"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/api/agent/v1/sessions/{session_id}/runs": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get?: never;
    put?: never;
    /** @description Before mutation, max_model_calls must be integer 1..10000 and exactly 1 for chat. No implicit defaults. Invalid wire/Chat bound: 400 invalid_request. Installation may set a LOWER explicit cap; above that cap: 422 run_limit_exceeded. Never silently reduce the requested cap or truncate child_request_ids. Count stable unique child model attempts, including in-flight/unknown, against accepted limit before dispatch; restore reads keep the full list. Request count and money/token budgets remain the original kernel responsibility. */
    post: operations["submitMessageAndRun"];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/api/agent/v1/sessions/{session_id}/runs/{run_id}": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get: operations["getRun"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/api/agent/v1/sessions/{session_id}/runs/{run_id}/steps": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get: operations["listRunStepPage"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/api/agent/v1/sessions/{session_id}/runs/{run_id}/tool-calls": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get: operations["listRunToolCallPage"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/api/agent/v1/sessions/{session_id}/runs/{run_id}/cancel": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get?: never;
    put?: never;
    post: operations["requestRunCancel"];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/api/agent/v1/sessions/{session_id}/commands/{operation_id}": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get: operations["lookupOriginalCommand"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/api/agent/v1/sessions/{session_id}/runs/{run_id}/checkpoint": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get: operations["getRunCheckpoint"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/api/agent/v1/sessions/{session_id}/runs/{run_id}/approvals/{approval_id}": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get: operations["getRunApproval"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/api/agent/v1/sessions/{session_id}/runs/{run_id}/approvals/{approval_id}/decision": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get?: never;
    put?: never;
    post: operations["decideToolApproval"];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/api/agent/v1/sessions/{session_id}/runs/{run_id}/events": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get: operations["replaySessionEvents"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/api/agent/v1/sessions/{session_id}/runs/{run_id}/events/stream": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /** @description Only one of after/Last-Event-ID. SSE event:type id:envelope.cursor data:SessionEvent. Replay committed events then follow; at-least-once. Heartbeats have no business ID. Expired cursor 410; obtain snapshot and server resume_cursor. No execution on GET. */
    get: operations["followSessionEvents"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/api/agent/v1/session-creation-commands/{operation_id}": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /** @description Read only using authenticated principal + create-session domain + original client_operation_id, without knowing session_id. No principal/owner/hash query override. 200 accepted returns original session_id and request hash. 404 not_found means no visible authoritative retained result: creation outcome remains unknown. 503 dependency_unavailable means read unavailable: outcome remains unknown. Neither response authorizes POST or a new operation ID. Retained tombstone may return 410 and requires manual recovery, never reuse the ID. Deleted original Sessions do not make this command create or select another Session. */
    get: operations["lookupSessionCreationCommand"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
}
export type webhooks = Record<string, never>;
export interface components {
  schemas: {
    Error: {
      error: {
        code: string;
        message: string;
        /** Format: uuid */
        http_request_id: string;
        run_id: string | null;
        child_request_id: string | null;
        retryable: boolean;
        snapshot_required: boolean;
      };
    };
    /** @description Explicit requested caps intersect with installation policy; no implicit production defaults. Money scale=9. max_duration includes approval and recovery wall time. */
    RunLimits: {
      max_steps: number;
      max_model_calls: number;
      max_tool_calls: number;
      max_duration_ms: number;
      tool_timeout_ms: number;
      max_tool_output_bytes: number;
      max_context_tokens: number;
      no_progress_limit: number;
      max_tokens: string;
      max_money_atomic: string;
      currency: string;
    };
    ConversationCreate: {
      /** Format: uuid */
      client_operation_id: string;
      title: string;
      model_alias: string;
    };
    ConversationRename: {
      title: string;
    };
    Conversation: {
      /** Format: uuid */
      id: string;
      /** Format: uuid */
      owner_id: string;
      title: string;
      model_alias: string;
      revision: string;
      active_run_id: string | null;
      /** Format: date-time */
      created_at: string;
      /** Format: date-time */
      updated_at: string;
      deleted_at: string | null;
    };
    TextPart: {
      /** @constant */
      type: "text";
      text: string;
    };
    ToolPart: {
      /** @constant */
      type: "tool_call";
      /** Format: uuid */
      call_id: string;
      name: string;
      tool_revision: string;
      arguments: {
        [key: string]: unknown;
      };
      args_sha256: string;
    };
    ToolResultPart: {
      /** @constant */
      type: "tool_result";
      /** Format: uuid */
      call_id: string;
      /** @enum {string} */
      outcome: "succeeded" | "failed" | "unknown";
      result:
        Record<string, never> | unknown[] | string | number | boolean | null;
    };
    Message: {
      /** Format: uuid */
      id: string;
      /** Format: uuid */
      session_id: string;
      position: string;
      /** @enum {string} */
      role: "user" | "assistant" | "tool";
      parts: (
        | components["schemas"]["TextPart"]
        | components["schemas"]["ToolPart"]
        | components["schemas"]["ToolResultPart"]
      )[];
      /** @enum {string} */
      status: "partial" | "committed" | "interrupted";
      run_id: string | null;
      supersedes_message_id: string | null;
      /** Format: date-time */
      created_at: string;
    };
    RunCreate: {
      /** Format: uuid */
      client_operation_id: string;
      /** @enum {string} */
      mode: "chat" | "agent";
      /** @enum {string} */
      operation: "send" | "edit" | "regenerate";
      text: string | null;
      referenced_message_id: string | null;
      model_alias: string;
      limits: components["schemas"]["RunLimits"];
      tools: {
        name: string;
        revision: string;
      }[];
    } & (unknown & unknown & unknown & unknown);
    RunUsageGroup: {
      currency: string;
      price_version: string;
      known_tokens: string;
      held_tokens: string;
      inflight_tokens: string;
      known_money_atomic: string;
      held_money_atomic: string;
      inflight_money_atomic: string;
    };
    Run: {
      /** Format: uuid */
      id: string;
      /** Format: uuid */
      session_id: string;
      /** Format: uuid */
      client_operation_id: string;
      /** @enum {string} */
      mode: "chat" | "agent";
      /** @enum {string} */
      state:
        | "accepted"
        | "running"
        | "waiting_approval"
        | "needs_confirmation"
        | "completed"
        | "failed"
        | "cancelled"
        | "limit_reached";
      revision: string;
      fence: string;
      /** Format: uuid */
      input_head_message_id: string;
      model_alias: string;
      /** @enum {string} */
      protocol_revision: "text-v1" | "tools-v1";
      limits: components["schemas"]["RunLimits"];
      cancel_requested: boolean;
      step_count: number;
      child_request_ids: string[];
      usage_groups: components["schemas"]["RunUsageGroup"][];
      aggregation_complete: boolean;
      last_event_seq: string;
      resume_cursor: string;
      reason: string | null;
      /** Format: date-time */
      created_at: string;
      /** Format: date-time */
      deadline_at: string;
      finished_at: string | null;
    } & (unknown & unknown);
    Step: {
      /** Format: uuid */
      id: string;
      /** Format: uuid */
      run_id: string;
      index: number;
      /** Format: uuid */
      model_call_id: string;
      child_request_id: string | null;
      /** @enum {string} */
      state:
        | "prepared"
        | "model_running"
        | "waiting_tools"
        | "completed"
        | "failed"
        | "unknown";
      /** @enum {string} */
      protocol_revision: "text-v1" | "tools-v1";
      input_sha256: string;
      output_sha256: string | null;
    };
    ToolManifest: {
      name: string;
      revision: string;
      schema_sha256: string;
      input_schema: Record<string, never>;
      output_schema: Record<string, never>;
      /** @enum {string} */
      effect: "pure" | "read_only" | "idempotent_write" | "non_idempotent";
      required_scope: string[];
      requires_approval: boolean;
      timeout_ms: number;
      max_output_bytes: number;
    };
    ToolCall: {
      /** Format: uuid */
      id: string;
      /** Format: uuid */
      run_id: string;
      /** Format: uuid */
      step_id: string;
      name: string;
      tool_revision: string;
      args_sha256: string;
      /** @enum {string} */
      state:
        | "proposed"
        | "waiting_approval"
        | "dispatching"
        | "running"
        | "succeeded"
        | "failed"
        | "unknown"
        | "cancelled";
      /** @enum {string} */
      effect: "pure" | "read_only" | "idempotent_write" | "non_idempotent";
      attempt: number;
      /** Format: uuid */
      idempotency_key: string;
      result: components["schemas"]["ToolResultPart"] | null;
      source_call_id: string;
      arguments: {
        [key: string]: unknown;
      };
    };
    Approval: {
      /** Format: uuid */
      id: string;
      /** Format: uuid */
      run_id: string;
      /** Format: uuid */
      call_id: string;
      tool_revision: string;
      args_sha256: string;
      policy_revision: string;
      scope_sha256: string;
      /** Format: date-time */
      expires_at: string;
      /** @enum {string} */
      state: "pending" | "allowed" | "denied" | "expired" | "revoked";
      tool_name: string;
      arguments: {
        [key: string]: unknown;
      };
    };
    LegacyUsage: {
      input_tokens: number | null;
      output_tokens: number | null;
      total_tokens: number | null;
      /** @enum {string} */
      source: "upstream" | "unavailable";
      missing_reason:
        | (
            | "not_provided"
            | "partial"
            | "cancelled_before_usage"
            | "interrupted_before_usage"
          )
        | null;
      input_cached_tokens: number | null;
      reasoning_tokens: number | null;
    } & (unknown & unknown & unknown);
    ModelToolProposal: {
      source_call_id: string;
      name: string;
      arguments: {
        [key: string]: unknown;
      };
    };
    /** @description Internal typed ModelClient result only, not a public inference response or proof. Consumer MUST read original child terminal/authority through the trusted store before executing tools. No public caller may submit this object. */
    ModelCallResult: {
      /** @enum {string} */
      protocol_revision: "text-v1" | "tools-v1";
      /** Format: uuid */
      child_request_id: string;
      model_alias: string;
      text: string | null;
      tool_calls: components["schemas"]["ModelToolProposal"][];
      /** @enum {string} */
      finish_reason: "stop" | "length" | "tool_calls";
      usage: components["schemas"]["LegacyUsage"];
    } & (unknown & unknown);
    ApprovalDecision: {
      /** Format: uuid */
      decision_id: string;
      /** @enum {string} */
      decision: "allow" | "deny";
      args_sha256: string;
      tool_revision: string;
      policy_revision: string;
    };
    Checkpoint: {
      /** Format: uuid */
      run_id: string;
      revision: string;
      last_event_seq: string;
      last_completed_step: number;
      /** Format: uuid */
      message_head_id: string;
      context_sha256: string;
      context_strategy_revision: string;
      registry_sha256: string;
      policy_revision: string;
      pending_child_request_ids: string[];
      pending_tool_call_ids: string[];
      fence: string;
    };
    Command: {
      /** Format: uuid */
      client_operation_id: string;
      /** Format: uuid */
      session_id: string;
      /** @enum {string} */
      state: "accepted" | "unknown";
      run_id: string | null;
      request_sha256: string;
    };
    RunAccepted: {
      conversation: components["schemas"]["Conversation"];
      run: components["schemas"]["Run"];
      input_message: components["schemas"]["Message"];
      operation: components["schemas"]["Command"];
      resume_cursor: string;
    };
    Snapshot: {
      conversation: components["schemas"]["Conversation"];
      messages: components["schemas"]["Message"][];
      runs: components["schemas"]["Run"][];
      last_event_seq: string;
      event_run_id: string | null;
      resume_cursor: string | null;
      messages_next_cursor: string | null;
    };
    Capabilities: {
      /** @constant */
      protocol_revision: "ar.api/1.0";
      event_versions: "ar.session.event/1.0"[];
      model_modes: {
        model_alias: string;
        /** @constant */
        text_protocol: "text-v1";
        tools_protocol: "tools-v1" | null;
        capability_revision: string;
        /** @enum {string} */
        approval_state: "controlled" | "approved" | "pending";
      }[];
      tools: components["schemas"]["ToolManifest"][];
      /** @constant */
      attachments_enabled: false;
    };
    /** @description Only durable committed events. seq is per-run decimal string; IDs/offsets and type/state consistency require semantic checks. No secrets or raw provider payload. */
    SessionEvent:
      | {
          /** @constant */
          version: "ar.session.event/1.0";
          /** Format: uuid */
          id: string;
          /** Format: uuid */
          session_id: string;
          seq: string;
          cursor: string;
          /** Format: date-time */
          created_at: string;
          /** Format: uuid */
          run_id: string;
          /** @constant */
          type: "run.accepted";
          data: components["schemas"]["Run"];
        }
      | {
          /** @constant */
          version: "ar.session.event/1.0";
          /** Format: uuid */
          id: string;
          /** Format: uuid */
          session_id: string;
          seq: string;
          cursor: string;
          /** Format: date-time */
          created_at: string;
          /** Format: uuid */
          run_id: string;
          /** @constant */
          type: "run.started";
          data: components["schemas"]["Run"];
        }
      | {
          /** @constant */
          version: "ar.session.event/1.0";
          /** Format: uuid */
          id: string;
          /** Format: uuid */
          session_id: string;
          seq: string;
          cursor: string;
          /** Format: date-time */
          created_at: string;
          /** Format: uuid */
          run_id: string;
          /** @constant */
          type: "run.cancel_requested";
          data: {
            /** Format: uuid */
            run_id: string;
          };
        }
      | {
          /** @constant */
          version: "ar.session.event/1.0";
          /** Format: uuid */
          id: string;
          /** Format: uuid */
          session_id: string;
          seq: string;
          cursor: string;
          /** Format: date-time */
          created_at: string;
          /** Format: uuid */
          run_id: string;
          /** @constant */
          type: "run.completed";
          data: components["schemas"]["Run"] & {
            /** @constant */
            state?: "completed";
          };
        }
      | {
          /** @constant */
          version: "ar.session.event/1.0";
          /** Format: uuid */
          id: string;
          /** Format: uuid */
          session_id: string;
          seq: string;
          cursor: string;
          /** Format: date-time */
          created_at: string;
          /** Format: uuid */
          run_id: string;
          /** @constant */
          type: "run.failed";
          data: components["schemas"]["Run"] & {
            /** @constant */
            state?: "failed";
          };
        }
      | {
          /** @constant */
          version: "ar.session.event/1.0";
          /** Format: uuid */
          id: string;
          /** Format: uuid */
          session_id: string;
          seq: string;
          cursor: string;
          /** Format: date-time */
          created_at: string;
          /** Format: uuid */
          run_id: string;
          /** @constant */
          type: "run.cancelled";
          data: components["schemas"]["Run"] & {
            /** @constant */
            state?: "cancelled";
          };
        }
      | {
          /** @constant */
          version: "ar.session.event/1.0";
          /** Format: uuid */
          id: string;
          /** Format: uuid */
          session_id: string;
          seq: string;
          cursor: string;
          /** Format: date-time */
          created_at: string;
          /** Format: uuid */
          run_id: string;
          /** @constant */
          type: "run.limit_reached";
          data: components["schemas"]["Run"] & {
            /** @constant */
            state?: "limit_reached";
          };
        }
      | {
          /** @constant */
          version: "ar.session.event/1.0";
          /** Format: uuid */
          id: string;
          /** Format: uuid */
          session_id: string;
          seq: string;
          cursor: string;
          /** Format: date-time */
          created_at: string;
          /** Format: uuid */
          run_id: string;
          /** @constant */
          type: "run.needs_confirmation";
          data: components["schemas"]["Run"] & {
            /** @constant */
            state?: "needs_confirmation";
          };
        }
      | {
          /** @constant */
          version: "ar.session.event/1.0";
          /** Format: uuid */
          id: string;
          /** Format: uuid */
          session_id: string;
          seq: string;
          cursor: string;
          /** Format: date-time */
          created_at: string;
          /** Format: uuid */
          run_id: string;
          /** @constant */
          type: "message.created";
          data: components["schemas"]["Message"];
        }
      | {
          /** @constant */
          version: "ar.session.event/1.0";
          /** Format: uuid */
          id: string;
          /** Format: uuid */
          session_id: string;
          seq: string;
          cursor: string;
          /** Format: date-time */
          created_at: string;
          /** Format: uuid */
          run_id: string;
          /** @constant */
          type: "message.delta";
          data: {
            /** Format: uuid */
            message_id: string;
            offset: string;
            text: string;
          };
        }
      | {
          /** @constant */
          version: "ar.session.event/1.0";
          /** Format: uuid */
          id: string;
          /** Format: uuid */
          session_id: string;
          seq: string;
          cursor: string;
          /** Format: date-time */
          created_at: string;
          /** Format: uuid */
          run_id: string;
          /** @constant */
          type: "message.committed";
          data: components["schemas"]["Message"];
        }
      | {
          /** @constant */
          version: "ar.session.event/1.0";
          /** Format: uuid */
          id: string;
          /** Format: uuid */
          session_id: string;
          seq: string;
          cursor: string;
          /** Format: date-time */
          created_at: string;
          /** Format: uuid */
          run_id: string;
          /** @constant */
          type: "step.started";
          data: components["schemas"]["Step"];
        }
      | {
          /** @constant */
          version: "ar.session.event/1.0";
          /** Format: uuid */
          id: string;
          /** Format: uuid */
          session_id: string;
          seq: string;
          cursor: string;
          /** Format: date-time */
          created_at: string;
          /** Format: uuid */
          run_id: string;
          /** @constant */
          type: "step.finished";
          data: components["schemas"]["Step"];
        }
      | {
          /** @constant */
          version: "ar.session.event/1.0";
          /** Format: uuid */
          id: string;
          /** Format: uuid */
          session_id: string;
          seq: string;
          cursor: string;
          /** Format: date-time */
          created_at: string;
          /** Format: uuid */
          run_id: string;
          /** @constant */
          type: "tool.proposed";
          data: components["schemas"]["ToolCall"];
        }
      | {
          /** @constant */
          version: "ar.session.event/1.0";
          /** Format: uuid */
          id: string;
          /** Format: uuid */
          session_id: string;
          seq: string;
          cursor: string;
          /** Format: date-time */
          created_at: string;
          /** Format: uuid */
          run_id: string;
          /** @constant */
          type: "tool.started";
          data: components["schemas"]["ToolCall"];
        }
      | {
          /** @constant */
          version: "ar.session.event/1.0";
          /** Format: uuid */
          id: string;
          /** Format: uuid */
          session_id: string;
          seq: string;
          cursor: string;
          /** Format: date-time */
          created_at: string;
          /** Format: uuid */
          run_id: string;
          /** @constant */
          type: "tool.result";
          data: components["schemas"]["ToolResultPart"];
        }
      | {
          /** @constant */
          version: "ar.session.event/1.0";
          /** Format: uuid */
          id: string;
          /** Format: uuid */
          session_id: string;
          seq: string;
          cursor: string;
          /** Format: date-time */
          created_at: string;
          /** Format: uuid */
          run_id: string;
          /** @constant */
          type: "approval.required";
          data: components["schemas"]["Approval"];
        }
      | {
          /** @constant */
          version: "ar.session.event/1.0";
          /** Format: uuid */
          id: string;
          /** Format: uuid */
          session_id: string;
          seq: string;
          cursor: string;
          /** Format: date-time */
          created_at: string;
          /** Format: uuid */
          run_id: string;
          /** @constant */
          type: "approval.resolved";
          data: components["schemas"]["Approval"];
        }
      | {
          /** @constant */
          version: "ar.session.event/1.0";
          /** Format: uuid */
          id: string;
          /** Format: uuid */
          session_id: string;
          seq: string;
          cursor: string;
          /** Format: date-time */
          created_at: string;
          /** Format: uuid */
          run_id: string;
          /** @constant */
          type: "checkpoint.saved";
          data: components["schemas"]["Checkpoint"];
        }
      | {
          /** @constant */
          version: "ar.session.event/1.0";
          /** Format: uuid */
          id: string;
          /** Format: uuid */
          session_id: string;
          seq: string;
          cursor: string;
          /** Format: date-time */
          created_at: string;
          /** Format: uuid */
          run_id: string;
          /** @constant */
          type: "run.usage";
          data: {
            /** Format: uuid */
            run_id: string;
            groups: components["schemas"]["RunUsageGroup"][];
          };
        };
    ConversationPage: {
      data: components["schemas"]["Conversation"][];
      next_cursor: string | null;
    };
    MessagePage: {
      data: components["schemas"]["Message"][];
      next_cursor: string | null;
    };
    EventPage: {
      data: components["schemas"]["SessionEvent"][];
      next_cursor: string | null;
    };
    StepPage: {
      data: components["schemas"]["Step"][];
      next_cursor: string | null;
    };
    ToolCallPage: {
      data: components["schemas"]["ToolCall"][];
      next_cursor: string | null;
    };
    /** @description Durable create-session command result scoped by authenticated principal and create-session operation kind, never a caller supplied owner. accepted proves original creation committed; it does not prove the Session still exists. Original deleted ID remains unchanged. */
    SessionCreationCommand: {
      /** Format: uuid */
      client_operation_id: string;
      /** Format: uuid */
      session_id: string;
      /** @constant */
      state: "accepted";
      request_sha256: string;
    };
  };
  responses: never;
  parameters: never;
  requestBodies: never;
  headers: never;
  pathItems: never;
}
export type $defs = Record<string, never>;
export interface operations {
  getChatCapabilities: {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Structured response; version/capability and original identity constraints in ADR. */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Capabilities"];
        };
      };
      /** @description Structured response; version/capability and original identity constraints in ADR. */
      400: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured response; version/capability and original identity constraints in ADR. */
      401: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured response; version/capability and original identity constraints in ADR. */
      403: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured response; version/capability and original identity constraints in ADR. */
      404: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured response; version/capability and original identity constraints in ADR. */
      409: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured response; version/capability and original identity constraints in ADR. */
      410: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured response; version/capability and original identity constraints in ADR. */
      422: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured response; version/capability and original identity constraints in ADR. */
      429: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured response; version/capability and original identity constraints in ADR. */
      503: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
    };
  };
  listConversations: {
    parameters: {
      query?: {
        cursor?: string;
        page_size?: number;
      };
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Structured response; version/capability and original identity constraints in ADR. */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ConversationPage"];
        };
      };
      /** @description Structured response; version/capability and original identity constraints in ADR. */
      400: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured response; version/capability and original identity constraints in ADR. */
      401: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured response; version/capability and original identity constraints in ADR. */
      403: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured response; version/capability and original identity constraints in ADR. */
      404: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured response; version/capability and original identity constraints in ADR. */
      409: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured response; version/capability and original identity constraints in ADR. */
      410: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured response; version/capability and original identity constraints in ADR. */
      422: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured response; version/capability and original identity constraints in ADR. */
      429: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured response; version/capability and original identity constraints in ADR. */
      503: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
    };
  };
  createConversation: {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody: {
      content: {
        "application/json": components["schemas"]["ConversationCreate"];
      };
    };
    responses: {
      /** @description Same key and canonical hash: original extant Session, no new mutation. */
      200: {
        headers: {
          /** @description Quoted opaque revision; required for applicable mutations. */
          ETag?: string;
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Conversation"];
        };
      };
      /** @description Structured response; version/capability and original identity constraints in ADR. */
      201: {
        headers: {
          /** @description Quoted opaque revision; required for applicable mutations. */
          ETag?: string;
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Conversation"];
        };
      };
      /** @description Structured response; version/capability and original identity constraints in ADR. */
      400: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured response; version/capability and original identity constraints in ADR. */
      401: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured response; version/capability and original identity constraints in ADR. */
      403: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured response; version/capability and original identity constraints in ADR. */
      404: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured response; version/capability and original identity constraints in ADR. */
      409: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured response; version/capability and original identity constraints in ADR. */
      410: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured response; version/capability and original identity constraints in ADR. */
      422: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured response; version/capability and original identity constraints in ADR. */
      429: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured response; version/capability and original identity constraints in ADR. */
      503: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
    };
  };
  getConversationSnapshot: {
    parameters: {
      query?: never;
      header?: never;
      path: {
        session_id: string;
      };
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Structured response; version/capability and original identity constraints in ADR. */
      200: {
        headers: {
          /** @description Quoted opaque revision; required for applicable mutations. */
          ETag?: string;
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Snapshot"];
        };
      };
      /** @description Structured response; version/capability and original identity constraints in ADR. */
      400: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured response; version/capability and original identity constraints in ADR. */
      401: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured response; version/capability and original identity constraints in ADR. */
      403: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured response; version/capability and original identity constraints in ADR. */
      404: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured response; version/capability and original identity constraints in ADR. */
      409: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured response; version/capability and original identity constraints in ADR. */
      410: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured response; version/capability and original identity constraints in ADR. */
      422: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured response; version/capability and original identity constraints in ADR. */
      429: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured response; version/capability and original identity constraints in ADR. */
      503: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
    };
  };
  deleteConversation: {
    parameters: {
      query?: never;
      header: {
        "If-Match": string;
      };
      path: {
        session_id: string;
      };
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description No content */
      204: {
        headers: {
          /** @description Quoted opaque revision; required for applicable mutations. */
          ETag?: string;
          [name: string]: unknown;
        };
        content?: never;
      };
      /** @description Structured response; version/capability and original identity constraints in ADR. */
      400: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured response; version/capability and original identity constraints in ADR. */
      401: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured response; version/capability and original identity constraints in ADR. */
      403: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured response; version/capability and original identity constraints in ADR. */
      404: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured response; version/capability and original identity constraints in ADR. */
      409: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured response; version/capability and original identity constraints in ADR. */
      410: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured response; version/capability and original identity constraints in ADR. */
      422: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured response; version/capability and original identity constraints in ADR. */
      429: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured response; version/capability and original identity constraints in ADR. */
      503: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
    };
  };
  renameConversation: {
    parameters: {
      query?: never;
      header: {
        "If-Match": string;
      };
      path: {
        session_id: string;
      };
      cookie?: never;
    };
    requestBody: {
      content: {
        "application/json": components["schemas"]["ConversationRename"];
      };
    };
    responses: {
      /** @description Structured response; version/capability and original identity constraints in ADR. */
      200: {
        headers: {
          /** @description Quoted opaque revision; required for applicable mutations. */
          ETag?: string;
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Conversation"];
        };
      };
      /** @description Structured response; version/capability and original identity constraints in ADR. */
      400: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured response; version/capability and original identity constraints in ADR. */
      401: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured response; version/capability and original identity constraints in ADR. */
      403: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured response; version/capability and original identity constraints in ADR. */
      404: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured response; version/capability and original identity constraints in ADR. */
      409: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured response; version/capability and original identity constraints in ADR. */
      410: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured response; version/capability and original identity constraints in ADR. */
      422: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured response; version/capability and original identity constraints in ADR. */
      429: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured response; version/capability and original identity constraints in ADR. */
      503: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
    };
  };
  listConversationMessages: {
    parameters: {
      query?: {
        cursor?: string;
        page_size?: number;
      };
      header?: never;
      path: {
        session_id: string;
      };
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Structured response; version/capability and original identity constraints in ADR. */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["MessagePage"];
        };
      };
      /** @description Structured response; version/capability and original identity constraints in ADR. */
      400: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured response; version/capability and original identity constraints in ADR. */
      401: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured response; version/capability and original identity constraints in ADR. */
      403: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured response; version/capability and original identity constraints in ADR. */
      404: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured response; version/capability and original identity constraints in ADR. */
      409: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured response; version/capability and original identity constraints in ADR. */
      410: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured response; version/capability and original identity constraints in ADR. */
      422: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured response; version/capability and original identity constraints in ADR. */
      429: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured response; version/capability and original identity constraints in ADR. */
      503: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
    };
  };
  submitMessageAndRun: {
    parameters: {
      query?: never;
      header: {
        "If-Match": string;
      };
      path: {
        session_id: string;
      };
      cookie?: never;
    };
    requestBody: {
      content: {
        "application/json": components["schemas"]["RunCreate"];
      };
    };
    responses: {
      /** @description Structured response; version/capability and original identity constraints in ADR. */
      202: {
        headers: {
          /** @description Quoted opaque revision; required for applicable mutations. */
          ETag?: string;
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["RunAccepted"];
        };
      };
      /** @description Structured response; version/capability and original identity constraints in ADR. */
      400: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured response; version/capability and original identity constraints in ADR. */
      401: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured response; version/capability and original identity constraints in ADR. */
      403: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured response; version/capability and original identity constraints in ADR. */
      404: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured response; version/capability and original identity constraints in ADR. */
      409: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured response; version/capability and original identity constraints in ADR. */
      410: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured response; version/capability and original identity constraints in ADR. */
      422: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured response; version/capability and original identity constraints in ADR. */
      429: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured response; version/capability and original identity constraints in ADR. */
      503: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
    };
  };
  getRun: {
    parameters: {
      query?: never;
      header?: never;
      path: {
        session_id: string;
        run_id: string;
      };
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Structured response; version/capability and original identity constraints in ADR. */
      200: {
        headers: {
          /** @description Quoted opaque revision; required for applicable mutations. */
          ETag?: string;
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Run"];
        };
      };
      /** @description Structured response; version/capability and original identity constraints in ADR. */
      400: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured response; version/capability and original identity constraints in ADR. */
      401: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured response; version/capability and original identity constraints in ADR. */
      403: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured response; version/capability and original identity constraints in ADR. */
      404: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured response; version/capability and original identity constraints in ADR. */
      409: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured response; version/capability and original identity constraints in ADR. */
      410: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured response; version/capability and original identity constraints in ADR. */
      422: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured response; version/capability and original identity constraints in ADR. */
      429: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured response; version/capability and original identity constraints in ADR. */
      503: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
    };
  };
  listRunStepPage: {
    parameters: {
      query?: {
        cursor?: string;
        page_size?: number;
      };
      header?: never;
      path: {
        session_id: string;
        run_id: string;
      };
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Structured response; version/capability and original identity constraints in ADR. */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["StepPage"];
        };
      };
      /** @description Structured response; version/capability and original identity constraints in ADR. */
      400: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured response; version/capability and original identity constraints in ADR. */
      401: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured response; version/capability and original identity constraints in ADR. */
      403: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured response; version/capability and original identity constraints in ADR. */
      404: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured response; version/capability and original identity constraints in ADR. */
      409: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured response; version/capability and original identity constraints in ADR. */
      410: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured response; version/capability and original identity constraints in ADR. */
      422: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured response; version/capability and original identity constraints in ADR. */
      429: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured response; version/capability and original identity constraints in ADR. */
      503: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
    };
  };
  listRunToolCallPage: {
    parameters: {
      query?: {
        cursor?: string;
        page_size?: number;
      };
      header?: never;
      path: {
        session_id: string;
        run_id: string;
      };
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Structured response; version/capability and original identity constraints in ADR. */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ToolCallPage"];
        };
      };
      /** @description Structured response; version/capability and original identity constraints in ADR. */
      400: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured response; version/capability and original identity constraints in ADR. */
      401: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured response; version/capability and original identity constraints in ADR. */
      403: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured response; version/capability and original identity constraints in ADR. */
      404: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured response; version/capability and original identity constraints in ADR. */
      409: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured response; version/capability and original identity constraints in ADR. */
      410: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured response; version/capability and original identity constraints in ADR. */
      422: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured response; version/capability and original identity constraints in ADR. */
      429: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured response; version/capability and original identity constraints in ADR. */
      503: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
    };
  };
  requestRunCancel: {
    parameters: {
      query?: never;
      header?: never;
      path: {
        session_id: string;
        run_id: string;
      };
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Structured response; version/capability and original identity constraints in ADR. */
      202: {
        headers: {
          /** @description Quoted opaque revision; required for applicable mutations. */
          ETag?: string;
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Run"];
        };
      };
      /** @description Structured response; version/capability and original identity constraints in ADR. */
      400: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured response; version/capability and original identity constraints in ADR. */
      401: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured response; version/capability and original identity constraints in ADR. */
      403: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured response; version/capability and original identity constraints in ADR. */
      404: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured response; version/capability and original identity constraints in ADR. */
      409: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured response; version/capability and original identity constraints in ADR. */
      410: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured response; version/capability and original identity constraints in ADR. */
      422: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured response; version/capability and original identity constraints in ADR. */
      429: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured response; version/capability and original identity constraints in ADR. */
      503: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
    };
  };
  lookupOriginalCommand: {
    parameters: {
      query?: never;
      header?: never;
      path: {
        session_id: string;
        operation_id: string;
      };
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Structured response; version/capability and original identity constraints in ADR. */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Command"];
        };
      };
      /** @description Structured response; version/capability and original identity constraints in ADR. */
      400: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured response; version/capability and original identity constraints in ADR. */
      401: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured response; version/capability and original identity constraints in ADR. */
      403: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured response; version/capability and original identity constraints in ADR. */
      404: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured response; version/capability and original identity constraints in ADR. */
      409: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured response; version/capability and original identity constraints in ADR. */
      410: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured response; version/capability and original identity constraints in ADR. */
      422: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured response; version/capability and original identity constraints in ADR. */
      429: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured response; version/capability and original identity constraints in ADR. */
      503: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
    };
  };
  getRunCheckpoint: {
    parameters: {
      query?: never;
      header?: never;
      path: {
        session_id: string;
        run_id: string;
      };
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Structured response; version/capability and original identity constraints in ADR. */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Checkpoint"];
        };
      };
      /** @description Structured response; version/capability and original identity constraints in ADR. */
      400: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured response; version/capability and original identity constraints in ADR. */
      401: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured response; version/capability and original identity constraints in ADR. */
      403: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured response; version/capability and original identity constraints in ADR. */
      404: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured response; version/capability and original identity constraints in ADR. */
      409: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured response; version/capability and original identity constraints in ADR. */
      410: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured response; version/capability and original identity constraints in ADR. */
      422: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured response; version/capability and original identity constraints in ADR. */
      429: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured response; version/capability and original identity constraints in ADR. */
      503: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
    };
  };
  getRunApproval: {
    parameters: {
      query?: never;
      header?: never;
      path: {
        session_id: string;
        run_id: string;
        approval_id: string;
      };
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Structured response; version/capability and original identity constraints in ADR. */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Approval"];
        };
      };
      /** @description Structured response; version/capability and original identity constraints in ADR. */
      400: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured response; version/capability and original identity constraints in ADR. */
      401: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured response; version/capability and original identity constraints in ADR. */
      403: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured response; version/capability and original identity constraints in ADR. */
      404: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured response; version/capability and original identity constraints in ADR. */
      409: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured response; version/capability and original identity constraints in ADR. */
      410: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured response; version/capability and original identity constraints in ADR. */
      422: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured response; version/capability and original identity constraints in ADR. */
      429: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured response; version/capability and original identity constraints in ADR. */
      503: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
    };
  };
  decideToolApproval: {
    parameters: {
      query?: never;
      header?: never;
      path: {
        session_id: string;
        run_id: string;
        approval_id: string;
      };
      cookie?: never;
    };
    requestBody: {
      content: {
        "application/json": components["schemas"]["ApprovalDecision"];
      };
    };
    responses: {
      /** @description Structured response; version/capability and original identity constraints in ADR. */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Approval"];
        };
      };
      /** @description Structured response; version/capability and original identity constraints in ADR. */
      400: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured response; version/capability and original identity constraints in ADR. */
      401: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured response; version/capability and original identity constraints in ADR. */
      403: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured response; version/capability and original identity constraints in ADR. */
      404: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured response; version/capability and original identity constraints in ADR. */
      409: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured response; version/capability and original identity constraints in ADR. */
      410: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured response; version/capability and original identity constraints in ADR. */
      422: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured response; version/capability and original identity constraints in ADR. */
      429: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured response; version/capability and original identity constraints in ADR. */
      503: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
    };
  };
  replaySessionEvents: {
    parameters: {
      query?: {
        after?: string;
        page_size?: number;
      };
      header?: never;
      path: {
        session_id: string;
        run_id: string;
      };
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Structured response; version/capability and original identity constraints in ADR. */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["EventPage"];
        };
      };
      /** @description Structured response; version/capability and original identity constraints in ADR. */
      400: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured response; version/capability and original identity constraints in ADR. */
      401: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured response; version/capability and original identity constraints in ADR. */
      403: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured response; version/capability and original identity constraints in ADR. */
      404: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured response; version/capability and original identity constraints in ADR. */
      409: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured response; version/capability and original identity constraints in ADR. */
      410: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured response; version/capability and original identity constraints in ADR. */
      422: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured response; version/capability and original identity constraints in ADR. */
      429: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured response; version/capability and original identity constraints in ADR. */
      503: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
    };
  };
  followSessionEvents: {
    parameters: {
      query?: {
        after?: string;
      };
      header?: {
        "Last-Event-ID"?: string;
      };
      path: {
        session_id: string;
        run_id: string;
      };
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Committed application events. Not ChatChunk and no inference [DONE] completion shortcut. */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "text/event-stream": string;
        };
      };
      /** @description Structured response; version/capability and original identity constraints in ADR. */
      400: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured response; version/capability and original identity constraints in ADR. */
      401: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured response; version/capability and original identity constraints in ADR. */
      403: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured response; version/capability and original identity constraints in ADR. */
      404: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured response; version/capability and original identity constraints in ADR. */
      409: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured response; version/capability and original identity constraints in ADR. */
      410: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured response; version/capability and original identity constraints in ADR. */
      422: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured response; version/capability and original identity constraints in ADR. */
      429: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured response; version/capability and original identity constraints in ADR. */
      503: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
    };
  };
  lookupSessionCreationCommand: {
    parameters: {
      query?: never;
      header?: never;
      path: {
        operation_id: string;
      };
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Original committed create-session mapping for this principal only. */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["SessionCreationCommand"];
        };
      };
      /** @description Structured response; version/capability and original identity constraints in ADR. */
      400: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured response; version/capability and original identity constraints in ADR. */
      401: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured response; version/capability and original identity constraints in ADR. */
      403: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured response; version/capability and original identity constraints in ADR. */
      404: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured response; version/capability and original identity constraints in ADR. */
      410: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured response; version/capability and original identity constraints in ADR. */
      503: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
    };
  };
}
