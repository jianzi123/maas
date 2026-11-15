export interface paths {
  "/api/admin/v1/session": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /** @description Validate current session from primary; no-store. */
    get: operations["getSession"];
    put?: never;
    /** @description Same-origin login; validate Origin and application/json; HttpOnly Secure SameSite=Strict cookie. */
    post: operations["createSession"];
    /** @description Revoke session before clearing cookie. Already logged out is idempotent 204; authenticated write requires CSRF. */
    delete: operations["deleteSession"];
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/api/admin/v1/models": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /** @description Model metadata without endpoint URLs or credentials. */
    get: operations["listAdminModels"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/api/admin/v1/keys": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /** @description Metadata and MySQL budget state; never secret. Known use, inflight reservation and unknown hold are separate. */
    get: operations["listKeys"];
    put?: never;
    /** @description Create one-time platform key with explicit UTC period and nullable request/token/money caps. No implicit 100/day default; 0 blocks, null disables. */
    post: operations["createKey"];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/api/admin/v1/keys/{key_id}": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get?: never;
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    /** @description CAS expected_revision; update limits without resetting window usage/holds; window kind and historical currency cannot be changed to bypass existing budget. */
    patch: operations["updateKeyQuota"];
    trace?: never;
  };
  "/api/admin/v1/keys/{key_id}/revoke": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get?: never;
    put?: never;
    /** @description Idempotent irreversible revocation. Return only after primary commit; reject all later admissions. */
    post: operations["revokeKey"];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/api/admin/v1/usage/requests": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /** @description UTC admission-day filtering; max 31 days; descending admitted_at/request_id cursor. */
    get: operations["listUsageRequests"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/api/admin/v1/usage/summary": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /** @description UTC admission day/key/alias/source/currency/price_version groups; never combine currencies or replace missing usage/cost with zero. Current period budget state is separate from daily retained detail. */
    get: operations["getUsageSummary"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/v1/models": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /** @description Valid platform key; no generation quota charged; enabled models only. */
    get: operations["listModels"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/v1/chat/completions": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get?: never;
    put?: never;
    /** @description Text subset. Go is sole admission via private Higress ext-auth: Redis rate permit first, then MySQL transaction reserves every enabled budget and slot and rate witness. No automatic generation retry; missing usage retains unknown holds. Responses/Codex full compatibility not claimed. */
    post: operations["createChatCompletion"];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/healthz": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /** @description Cluster probe only. Process liveness; no paid upstream probe. */
    get: operations["liveness"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/readyz": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    /** @description Cluster probe only. Writable primary, expected route revision, dependencies and no drain. */
    get: operations["readiness"];
    put?: never;
    post?: never;
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/api/admin/v1/model-releases": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get: operations["listModelReleases"];
    put?: never;
    post: operations["createModelRelease"];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/api/admin/v1/model-releases/{namespace}/{name}": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get: operations["getModelRelease"];
    put: operations["updateModelRelease"];
    post?: never;
    delete: operations["deleteModelRelease"];
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/api/admin/v1/model-releases/{namespace}/{name}/rollback": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get?: never;
    put?: never;
    post: operations["rollbackModelRelease"];
    delete?: never;
    options?: never;
    head?: never;
    patch?: never;
    trace?: never;
  };
  "/api/admin/v1/release-operations/{operation_id}": {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    get: operations["getReleaseOperation"];
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
        /** @enum {string} */
        code:
          | "invalid_request"
          | "model_not_found"
          | "unsupported_field"
          | "retention_window_exceeded"
          | "payload_too_large"
          | "invalid_api_key"
          | "unauthenticated"
          | "csrf_failed"
          | "forbidden"
          | "source_disabled"
          | "not_found"
          | "key_revoked"
          | "state_conflict"
          | "concurrency_exceeded"
          | "login_rate_limited"
          | "upstream_error"
          | "upstream_protocol_error"
          | "upstream_rate_limited"
          | "upstream_timeout"
          | "dependency_unavailable"
          | "admission_busy"
          | "route_not_ready"
          | "accounting_unavailable"
          | "shutting_down"
          | "internal_error"
          | "client_write_timeout"
          | "client_cancelled"
          | "owner_lost"
          | "request_budget_exceeded"
          | "token_budget_exceeded"
          | "money_budget_exceeded"
          | "rate_limited"
          | "budget_bound_unavailable"
          | "pricing_unavailable"
          | "rate_limiter_unavailable"
          | "policy_changed"
          | "currency_mismatch"
          | "budget_bound_breached"
          | "release_not_callable"
          | "release_revision_mismatch"
          | "release_dependency_unavailable"
          | "release_alias_conflict"
          | "resource_version_conflict"
          | "release_validation_pending";
        message: string;
        /** Format: uuid */
        request_id: string;
        retryable: boolean;
        reset_at: string | null;
        retry_after_seconds: number | null;
        param: string | null;
        budget_dimension:
          ("requests" | "tokens" | "money" | "rate" | "concurrency") | null;
        policy_revision: string | null;
      };
    };
    Usage: {
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
    Session: {
      /** Format: uuid */
      admin_id: string;
      /** Format: date-time */
      expires_at: string;
      csrf_token: string;
    };
    Login: {
      username: string;
      password: string;
    };
    Key: {
      /** Format: uuid */
      id: string;
      name: string;
      key_prefix: string;
      /** @enum {string} */
      state: "active" | "revoked";
      /** Format: date-time */
      created_at: string;
      revoked_at: string | null;
      budget_policy: components["schemas"]["BudgetPolicy"];
      budget_state: components["schemas"]["BudgetState"];
    };
    KeyCreate: {
      name: string;
      budget_policy: components["schemas"]["BudgetPolicyInput"];
    };
    KeyCreated: {
      key: components["schemas"]["Key"];
      /** @description Only returned once. Never retry creation automatically. */
      secret: string;
    };
    KeyPatch: {
      expected_revision: string;
      limits: components["schemas"]["BudgetLimits"];
    };
    Capabilities: {
      streaming: boolean;
      verified_max_output_tokens: number;
      temperature_supported: boolean;
      /** @enum {string} */
      usage_available: "verified" | "unavailable" | "unknown";
      capability_revision: string;
      /** @enum {string} */
      hard_budget_status: "verified" | "unverified" | "unsupported";
      budget_unavailable_reason: string | null;
      protocols: ("chat_completions" | "responses")[];
    };
    PublicModel: {
      id: string;
      /** @constant */
      object: "model";
      /** @constant */
      owned_by: "maas";
      /** @enum {string} */
      source_type: "internal" | "external";
      capabilities: components["schemas"]["Capabilities"];
      release_binding: components["schemas"]["ReleaseInvocationBinding"] | null;
      callable: boolean;
    };
    AdminModel: {
      id: string;
      /** @constant */
      object: "model";
      /** @constant */
      owned_by: "maas";
      /** @enum {string} */
      source_type: "internal" | "external";
      capabilities: components["schemas"]["Capabilities"];
      /** Format: uuid */
      source_id: string;
      display_name: string;
      /** @enum {string} */
      check_state: "unknown" | "available" | "unavailable";
      checked_at: string | null;
      config_revision: string;
      release_binding: components["schemas"]["ReleaseInvocationBinding"] | null;
      callable: boolean;
    };
    Message: {
      /** @enum {string} */
      role: "system" | "user" | "assistant";
      content: string;
    };
    ChatRequest: {
      model: string;
      /** @description At least one nonblank user content; aggregate <=32768 Unicode code points; body <=256KiB. Runtime rejects whitespace-only user input. */
      messages: components["schemas"]["Message"][];
      /** @default false */
      stream: boolean;
      /** @description Runtime maximum is min(4096, model verified limit); omitted default min(1024, verified limit). */
      max_tokens?: number;
      temperature?: number;
    };
    ChatResponse: {
      id: string;
      /** @constant */
      object: "chat.completion";
      created: number;
      model: string;
      choices: {
        /** @constant */
        index: 0;
        message: {
          /** @constant */
          role: "assistant";
          content: string;
        };
        /** @enum {string} */
        finish_reason: "stop" | "length";
      }[];
      usage: components["schemas"]["Usage"];
    };
    ChatChunk: {
      id: string;
      /** @constant */
      object: "chat.completion.chunk";
      created: number;
      model: string;
      choices: {
        /** @constant */
        index: 0;
        delta: {
          /** @constant */
          role?: "assistant";
          content?: string;
        };
        finish_reason: ("stop" | "length") | null;
      }[];
      usage?: components["schemas"]["Usage"];
    };
    RequestRecord: {
      /** Format: uuid */
      request_id: string;
      /** Format: uuid */
      key_id: string;
      model_alias: string;
      upstream_model: string;
      /** Format: uuid */
      source_id: string;
      /** @enum {string} */
      source_type: "internal" | "external";
      config_revision: string;
      /** Format: date-time */
      received_at: string;
      /** Format: date-time */
      admitted_at: string;
      finished_at: string | null;
      /** Format: date */
      quota_date: string;
      /** @enum {string} */
      status:
        | "in_progress"
        | "succeeded"
        | "failed"
        | "cancelled"
        | "timed_out"
        | "interrupted";
      /** @enum {string} */
      submission_state: "submitted" | "not_submitted" | "unknown";
      quota_consumed: number;
      error_code:
        | (
            | "invalid_request"
            | "model_not_found"
            | "unsupported_field"
            | "retention_window_exceeded"
            | "payload_too_large"
            | "invalid_api_key"
            | "unauthenticated"
            | "csrf_failed"
            | "forbidden"
            | "source_disabled"
            | "not_found"
            | "key_revoked"
            | "state_conflict"
            | "concurrency_exceeded"
            | "login_rate_limited"
            | "upstream_error"
            | "upstream_protocol_error"
            | "upstream_rate_limited"
            | "upstream_timeout"
            | "dependency_unavailable"
            | "admission_busy"
            | "route_not_ready"
            | "accounting_unavailable"
            | "shutting_down"
            | "internal_error"
            | "client_write_timeout"
            | "client_cancelled"
            | "owner_lost"
            | "request_budget_exceeded"
            | "token_budget_exceeded"
            | "money_budget_exceeded"
            | "rate_limited"
            | "budget_bound_unavailable"
            | "pricing_unavailable"
            | "rate_limiter_unavailable"
            | "policy_changed"
            | "currency_mismatch"
            | "budget_bound_breached"
          )
        | null;
      duration_ms: number | null;
      first_chunk_ms: number | null;
      usage: components["schemas"]["Usage"];
      /** @enum {string} */
      metering_state: "complete" | "incomplete";
      reservation_plan: components["schemas"]["ReservationPlan"];
      budget_accounting: components["schemas"]["BudgetAccounting"] | null;
      rate_witness: components["schemas"]["RateWitness"];
      invocation_binding: components["schemas"]["ReleaseInvocationBinding"];
    };
    SummaryRow: {
      /** Format: date */
      quota_date: string;
      /** Format: uuid */
      key_id: string;
      model_alias: string;
      /** Format: uuid */
      source_id: string;
      /** @enum {string} */
      source_type: "internal" | "external";
      admitted_total: number;
      in_progress: number;
      succeeded: number;
      failed: number;
      cancelled: number;
      timed_out: number;
      interrupted: number;
      quota_used: number;
      submitted_known: number;
      submission_unknown: number;
      not_submitted: number;
      input_tokens_known: number;
      output_tokens_known: number;
      total_tokens_known: number;
      missing_input_requests: number;
      missing_output_requests: number;
      missing_total_requests: number;
      missing_token_requests: number;
      currency: string | null;
      price_version: string | null;
      cost_known_atomic: string | null;
      money_uncertainty_held_atomic: string | null;
      token_uncertainty_held: string;
      missing_cost_requests: number;
    };
    Health: {
      /** @enum {string} */
      status: "ok" | "not_ready";
    };
    KeyPage: {
      data: components["schemas"]["Key"][];
      next_cursor: string | null;
      /** Format: date-time */
      generated_at: string;
      data_complete: boolean;
    };
    RequestPage: {
      data: components["schemas"]["RequestRecord"][];
      next_cursor: string | null;
      /** Format: date-time */
      generated_at: string;
      data_complete: boolean;
    };
    SummaryPage: {
      data: components["schemas"]["SummaryRow"][];
      next_cursor: string | null;
      /** Format: date-time */
      generated_at: string;
      data_complete: boolean;
    };
    PublicModelList: {
      /** @constant */
      object: "list";
      data: components["schemas"]["PublicModel"][];
    };
    AdminModelList: {
      /** @constant */
      object: "list";
      data: components["schemas"]["AdminModel"][];
    };
    AtomicInteger: string;
    MoneyLimit: {
      currency: string;
      limit_atomic: string;
    };
    BudgetLimits: {
      requests: string | null;
      tokens: string | null;
      money: components["schemas"]["MoneyLimit"] | null;
    };
    BudgetPolicyInput: {
      /** @enum {string} */
      window_kind: "utc_day" | "utc_month";
      limits: components["schemas"]["BudgetLimits"];
    };
    BudgetCounterVector: {
      requests: string;
      tokens: string;
      money_atomic: string | null;
    };
    BudgetAvailableVector: {
      requests: string | null;
      tokens: string | null;
      money_atomic: string | null;
    };
    BudgetState: {
      /** @enum {string} */
      window_kind: "utc_day" | "utc_month";
      /** Format: date-time */
      window_start: string;
      /** Format: date-time */
      window_end: string;
      admission_blocked: boolean;
      block_reason: "budget_bound_breached" | null;
      currency: string | null;
      known_used: components["schemas"]["BudgetCounterVector"];
      inflight_reserved: components["schemas"]["BudgetCounterVector"];
      uncertainty_held: components["schemas"]["BudgetCounterVector"];
      available: components["schemas"]["BudgetAvailableVector"];
    };
    ReservationPlan: {
      /** @constant */
      schema_version: "1.0";
      model_alias: string;
      /** Format: uuid */
      source_id: string;
      config_revision: string;
      capability_revision: string;
      budget_policy_revision: string;
      /** @enum {string} */
      window_kind: "utc_day" | "utc_month";
      /** @constant */
      token_metric: "prompt_plus_completion";
      /** @constant */
      request_reserved: "1";
      input_upper_tokens: string | null;
      output_upper_tokens: string | null;
      total_upper_tokens: string | null;
      token_reserved: string | null;
      money_reserved_atomic: string | null;
      currency: string | null;
      price_snapshot_id: string | null;
      price_snapshot_sha256: string | null;
      price_version: string | null;
      rate_policy_revision: string;
    } & (unknown & unknown);
    PriceSnapshot: {
      /** Format: uuid */
      id: string;
      version: string;
      /** Format: uuid */
      source_id: string;
      upstream_model: string;
      currency: string;
      /** @constant */
      scale: 9;
      /** @constant */
      tokens_per_price_unit: 1000000;
      /** Format: date-time */
      effective_at: string;
      input_uncached_per_million_atomic: string;
      input_cached_per_million_atomic: string;
      output_visible_per_million_atomic: string;
      output_reasoning_per_million_atomic: string;
    };
    DimensionSettlement: {
      reserved: string;
      known_used: string;
      unknown_held: string;
      released: string;
      overrun: string;
      /** @enum {string} */
      state: "known" | "held" | "released" | "anomalous";
    } & (unknown & unknown & unknown & unknown);
    BudgetAccounting: {
      policy_revision: string;
      /** @enum {string} */
      window_kind: "utc_day" | "utc_month";
      /** Format: date-time */
      window_start: string;
      /** Format: date-time */
      window_end: string;
      request: components["schemas"]["DimensionSettlement"];
      token: components["schemas"]["DimensionSettlement"] | null;
      money: components["schemas"]["DimensionSettlement"] | null;
      token_actual: string | null;
      /** @enum {string} */
      token_basis:
        "upstream_total" | "component_sum" | "not_submitted" | "unavailable";
      cost_actual_atomic: string | null;
      /** @enum {string} */
      cost_state: "known" | "unavailable" | "upper_bound" | "anomalous";
      currency: string | null;
      price_snapshot_id: string | null;
      price_version: string | null;
      missing_reason:
        | (
            | "not_provided"
            | "partial_usage"
            | "partial_price_categories"
            | "not_priced"
            | "owner_lost"
            | "bound_breached"
          )
        | null;
    } & (unknown & unknown);
    RateWitness: {
      /** Format: uuid */
      permit_id: string;
      rate_epoch: string;
      policy_id: string;
      policy_revision: string;
      windows: {
        scope_id: string;
        /** Format: date-time */
        window_start: string;
        /** Format: date-time */
        window_end: string;
        limit: string;
      }[];
    };
    BudgetPolicy: {
      /** @enum {string} */
      window_kind: "utc_day" | "utc_month";
      limits: components["schemas"]["BudgetLimits"];
      revision: string;
    };
    ReleaseProfileRef: {
      name: string;
      revision: string;
    };
    ReleaseSecretKeyRef: {
      name: string;
      key: string;
    };
    ReleaseSpec: {
      modelAlias: string;
      source: {
        /** @enum {string} */
        type: "SelfHosted" | "ExternalAPI";
        selfHosted?: {
          /** @constant */
          engine: "SGLang";
          /** @constant */
          workload: "LeaderWorkerSet";
          weights: {
            pvcName: string;
            path: string;
            sha256: string;
            modelRevision: string;
          };
          runtimeProfileRef: components["schemas"]["ReleaseProfileRef"];
          placementProfileRef: components["schemas"]["ReleaseProfileRef"];
          image: string;
          groups: number;
          podsPerGroup: number;
          gpusPerPod: number;
          /** @constant */
          gpuResourceName: "nvidia.com/gpu";
          cpuPerPod: string;
          memoryPerPod: string;
          tensorParallelSize: number;
          /** @constant */
          pipelineParallelSize: 1;
          startupTimeoutSeconds: number;
        };
        externalAPI?: {
          /** @enum {string} */
          provider: "DeepSeek" | "OpenAICompatible";
          endpointRef: components["schemas"]["ReleaseProfileRef"];
          upstreamModel: string;
          /** @constant */
          protocol: "OpenAIChatCompletions";
          credentialSecretRef: components["schemas"]["ReleaseSecretKeyRef"];
        };
      } & (
        | {
            /** @constant */
            type?: "SelfHosted";
          }
        | {
            /** @constant */
            type?: "ExternalAPI";
          }
      );
      gatewayRef: components["schemas"]["ReleaseProfileRef"];
      businessRefs: {
        capabilityProfileRef: components["schemas"]["ReleaseProfileRef"];
        pricePolicyRef: components["schemas"]["ReleaseProfileRef"];
        intakePolicyRef: components["schemas"]["ReleaseProfileRef"];
      };
      lifecycle: {
        /** @enum {string} */
        desiredState: "Published" | "Paused";
        /** @enum {string} */
        strategy: "BlueGreen" | "Recreate";
        drainTimeoutSeconds: number;
        progressDeadlineSeconds: number;
        retainedRevisions: number;
        /** @constant */
        retainUserData: true;
      };
    };
    ReleaseCreateMetadata: {
      name: string;
      namespace: string;
    };
    ReleaseMetadata: {
      name: string;
      namespace: string;
      /** Format: uuid */
      uid?: string;
      resourceVersion?: string;
      generation?: number;
      deletionTimestamp?: string | null;
      finalizers?: string[];
    } & {
      [key: string]: unknown;
    };
    ReleaseInvocationBinding: {
      /** Format: uuid */
      model_release_uid: string;
      model_release_namespace: string;
      model_release_name: string;
      model_release_generation: number;
      release_revision: string;
      /** Format: uuid */
      publication_id: string;
      activation_epoch: number;
      route_binding_sha256: string;
      /** @enum {string} */
      admission_purpose: "serving" | "validation";
      price_snapshot_id: string | null;
      price_version: string | null;
    };
    ReleaseCondition: {
      /** @enum {string} */
      type:
        | "Accepted"
        | "DependenciesReady"
        | "RuntimeReady"
        | "GatewayApplied"
        | "AccountingReady"
        | "ValidationPassed"
        | "Callable"
        | "Progressing"
        | "Degraded"
        | "AdmissionClosed"
        | "Drained"
        | "CleanupComplete";
      /** @enum {string} */
      status: "True" | "False" | "Unknown";
      reason: string;
      message: string;
      observedGeneration: number;
      /** Format: date-time */
      lastTransitionTime: string;
    };
    ReleaseResourceRef: {
      apiVersion: string;
      kind: string;
      namespace: string;
      name: string;
      uid: string | null;
      /** @enum {string} */
      ownership:
        "exclusive" | "shared-entry" | "user-reference" | "installation";
      publication_id: string | null;
    };
    ReleaseOperation: {
      /** Format: uuid */
      id: string;
      /** @enum {string} */
      action: "Create" | "Update" | "Pause" | "Resume" | "Rollback" | "Delete";
      /** @enum {string} */
      state: "Accepted" | "Running" | "Succeeded" | "Failed" | "Unknown";
      namespace: string;
      name: string;
      cr_uid: string | null;
      requested_generation: number | null;
      publication_id: string | null;
      /** Format: date-time */
      created_at: string;
      /** Format: date-time */
      updated_at: string;
      reason: string | null;
      message: string;
    };
    ReleaseStatus: {
      observedGeneration: number;
      /** @enum {string} */
      phase:
        | "Pending"
        | "Preparing"
        | "Validating"
        | "Ready"
        | "Updating"
        | "Paused"
        | "Draining"
        | "Deleting"
        | "Degraded"
        | "Failed";
      desiredRevision: string | null;
      activeRevision: string | null;
      activeGeneration: number | null;
      publication_id: string | null;
      activation_epoch: number;
      availableGroups: number;
      conditions: components["schemas"]["ReleaseCondition"][];
      resources: components["schemas"]["ReleaseResourceRef"][];
      operation: components["schemas"]["ReleaseOperation"] | null;
    };
    ReleaseModelRelease: {
      /** @constant */
      apiVersion: "serving.maas.example/v1alpha1";
      /** @constant */
      kind: "ModelRelease";
      metadata: components["schemas"]["ReleaseMetadata"];
      spec: components["schemas"]["ReleaseSpec"];
      status?: components["schemas"]["ReleaseStatus"];
    };
    ReleaseReleaseInput: {
      /** @constant */
      apiVersion: "serving.maas.example/v1alpha1";
      /** @constant */
      kind: "ModelRelease";
      metadata: components["schemas"]["ReleaseCreateMetadata"];
      spec: components["schemas"]["ReleaseSpec"];
    };
    ReleaseRollbackInput: {
      target_revision: string;
    };
    ReleaseAccepted: {
      operation: components["schemas"]["ReleaseOperation"];
      resource: components["schemas"]["ReleaseModelRelease"] | null;
    };
    ReleaseControlCommand: {
      /** Format: uuid */
      command_id: string;
      /** @enum {string} */
      action:
        | "Prepare"
        | "RequestValidation"
        | "RecordGatewayReceipt"
        | "Activate"
        | "CloseAdmission"
        | "RetireRuntime"
        | "RecordCleanup";
      /** Format: uuid */
      cr_uid: string;
      observed_generation: number;
      reconcile_epoch: number;
      expected_active_publication_id: string | null;
      target_publication_id: string | null;
      revision: string;
      evidence_refs: string[];
    };
    ReleaseList: {
      data: components["schemas"]["ReleaseModelRelease"][];
      next_cursor: string | null;
      /** Format: date-time */
      generated_at: string;
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
  getSession: {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Validate current session from primary; no-store. */
      200: {
        headers: {
          /** @description Server generated trusted request id. */
          "X-Request-ID"?: string;
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Session"];
        };
      };
      /** @description Structured sanitized error; see architecture error mapping. */
      401: {
        headers: {
          /** @description Server generated trusted request id. */
          "X-Request-ID"?: string;
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured sanitized error; see architecture error mapping. */
      503: {
        headers: {
          /** @description Server generated trusted request id. */
          "X-Request-ID"?: string;
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
    };
  };
  createSession: {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody: {
      content: {
        "application/json": components["schemas"]["Login"];
      };
    };
    responses: {
      /** @description Same-origin login; validate Origin and application/json; HttpOnly Secure SameSite=Strict cookie. */
      200: {
        headers: {
          /** @description Server generated trusted request id. */
          "X-Request-ID"?: string;
          /** @description __Host-maas_session cookie; Path=/; Secure; HttpOnly; SameSite=Strict; no Domain. */
          "Set-Cookie"?: string;
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Session"];
        };
      };
      /** @description Structured sanitized error; see architecture error mapping. */
      400: {
        headers: {
          /** @description Server generated trusted request id. */
          "X-Request-ID"?: string;
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured sanitized error; see architecture error mapping. */
      401: {
        headers: {
          /** @description Server generated trusted request id. */
          "X-Request-ID"?: string;
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured sanitized error; see architecture error mapping. */
      403: {
        headers: {
          /** @description Server generated trusted request id. */
          "X-Request-ID"?: string;
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured sanitized error; see architecture error mapping. */
      429: {
        headers: {
          /** @description Server generated trusted request id. */
          "X-Request-ID"?: string;
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured sanitized error; see architecture error mapping. */
      503: {
        headers: {
          /** @description Server generated trusted request id. */
          "X-Request-ID"?: string;
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
    };
  };
  deleteSession: {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Revoke session before clearing cookie. Already logged out is idempotent 204; authenticated write requires CSRF. */
      204: {
        headers: {
          /** @description Server generated trusted request id. */
          "X-Request-ID"?: string;
          [name: string]: unknown;
        };
        content?: never;
      };
      /** @description Structured sanitized error; see architecture error mapping. */
      403: {
        headers: {
          /** @description Server generated trusted request id. */
          "X-Request-ID"?: string;
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured sanitized error; see architecture error mapping. */
      503: {
        headers: {
          /** @description Server generated trusted request id. */
          "X-Request-ID"?: string;
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
    };
  };
  listAdminModels: {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Model metadata without endpoint URLs or credentials. */
      200: {
        headers: {
          /** @description Server generated trusted request id. */
          "X-Request-ID"?: string;
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["AdminModelList"];
        };
      };
      /** @description Structured sanitized error; see architecture error mapping. */
      401: {
        headers: {
          /** @description Server generated trusted request id. */
          "X-Request-ID"?: string;
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured sanitized error; see architecture error mapping. */
      503: {
        headers: {
          /** @description Server generated trusted request id. */
          "X-Request-ID"?: string;
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
    };
  };
  listKeys: {
    parameters: {
      query?: {
        page_size?: number;
        cursor?: string;
      };
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Newest first metadata with current UTC quota; never secret. */
      200: {
        headers: {
          /** @description Server generated trusted request id. */
          "X-Request-ID"?: string;
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["KeyPage"];
        };
      };
      /** @description Structured sanitized error; see architecture error mapping. */
      400: {
        headers: {
          /** @description Server generated trusted request id. */
          "X-Request-ID"?: string;
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured sanitized error; see architecture error mapping. */
      401: {
        headers: {
          /** @description Server generated trusted request id. */
          "X-Request-ID"?: string;
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured sanitized error; see architecture error mapping. */
      503: {
        headers: {
          /** @description Server generated trusted request id. */
          "X-Request-ID"?: string;
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
    };
  };
  createKey: {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody: {
      content: {
        "application/json": components["schemas"]["KeyCreate"];
      };
    };
    responses: {
      /** @description Created with the explicitly supplied budget_policy and request/token/money limits. No implicit quota default. The secret is returned once; do not automatically retry creation. */
      201: {
        headers: {
          /** @description Server generated trusted request id. */
          "X-Request-ID"?: string;
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["KeyCreated"];
        };
      };
      /** @description Structured sanitized error; see architecture error mapping. */
      400: {
        headers: {
          /** @description Server generated trusted request id. */
          "X-Request-ID"?: string;
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured sanitized error; see architecture error mapping. */
      401: {
        headers: {
          /** @description Server generated trusted request id. */
          "X-Request-ID"?: string;
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured sanitized error; see architecture error mapping. */
      403: {
        headers: {
          /** @description Server generated trusted request id. */
          "X-Request-ID"?: string;
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description policy_changed or state_conflict; no reset. */
      409: {
        headers: {
          /** @description Server generated trusted request id. */
          "X-Request-ID"?: string;
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured sanitized error; see architecture error mapping. */
      503: {
        headers: {
          /** @description Server generated trusted request id. */
          "X-Request-ID"?: string;
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
    };
  };
  updateKeyQuota: {
    parameters: {
      query?: never;
      header?: never;
      path: {
        key_id: string;
      };
      cookie?: never;
    };
    requestBody: {
      content: {
        "application/json": components["schemas"]["KeyPatch"];
      };
    };
    responses: {
      /** @description Serialize quota update with admission; lower limit clamps remaining to zero. */
      200: {
        headers: {
          /** @description Server generated trusted request id. */
          "X-Request-ID"?: string;
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Key"];
        };
      };
      /** @description Structured sanitized error; see architecture error mapping. */
      400: {
        headers: {
          /** @description Server generated trusted request id. */
          "X-Request-ID"?: string;
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured sanitized error; see architecture error mapping. */
      401: {
        headers: {
          /** @description Server generated trusted request id. */
          "X-Request-ID"?: string;
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured sanitized error; see architecture error mapping. */
      403: {
        headers: {
          /** @description Server generated trusted request id. */
          "X-Request-ID"?: string;
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured sanitized error; see architecture error mapping. */
      404: {
        headers: {
          /** @description Server generated trusted request id. */
          "X-Request-ID"?: string;
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description policy_changed or state_conflict; no reset. */
      409: {
        headers: {
          /** @description Server generated trusted request id. */
          "X-Request-ID"?: string;
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured sanitized error; see architecture error mapping. */
      503: {
        headers: {
          /** @description Server generated trusted request id. */
          "X-Request-ID"?: string;
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
    };
  };
  revokeKey: {
    parameters: {
      query?: never;
      header?: never;
      path: {
        key_id: string;
      };
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Idempotent irreversible revocation. Return only after primary commit; reject all later admissions. */
      200: {
        headers: {
          /** @description Server generated trusted request id. */
          "X-Request-ID"?: string;
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Key"];
        };
      };
      /** @description Structured sanitized error; see architecture error mapping. */
      401: {
        headers: {
          /** @description Server generated trusted request id. */
          "X-Request-ID"?: string;
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured sanitized error; see architecture error mapping. */
      403: {
        headers: {
          /** @description Server generated trusted request id. */
          "X-Request-ID"?: string;
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured sanitized error; see architecture error mapping. */
      404: {
        headers: {
          /** @description Server generated trusted request id. */
          "X-Request-ID"?: string;
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured sanitized error; see architecture error mapping. */
      503: {
        headers: {
          /** @description Server generated trusted request id. */
          "X-Request-ID"?: string;
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
    };
  };
  listUsageRequests: {
    parameters: {
      query?: {
        /** @description UTC inclusive. Default today. */
        date_from?: string;
        /** @description UTC exclusive; >date_from, <=31 days. Default tomorrow. */
        date_to?: string;
        key_id?: string;
        model_alias?: string;
        source_id?: string;
        status?:
          | "in_progress"
          | "succeeded"
          | "failed"
          | "cancelled"
          | "timed_out"
          | "interrupted";
        page_size?: number;
        cursor?: string;
      };
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description UTC admission-day filtering; max 31 days; descending admitted_at/request_id cursor. */
      200: {
        headers: {
          /** @description Server generated trusted request id. */
          "X-Request-ID"?: string;
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["RequestPage"];
        };
      };
      /** @description Structured sanitized error; see architecture error mapping. */
      400: {
        headers: {
          /** @description Server generated trusted request id. */
          "X-Request-ID"?: string;
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured sanitized error; see architecture error mapping. */
      401: {
        headers: {
          /** @description Server generated trusted request id. */
          "X-Request-ID"?: string;
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured sanitized error; see architecture error mapping. */
      503: {
        headers: {
          /** @description Server generated trusted request id. */
          "X-Request-ID"?: string;
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
    };
  };
  getUsageSummary: {
    parameters: {
      query?: {
        /** @description UTC inclusive. Default today. */
        date_from?: string;
        /** @description UTC exclusive; >date_from, <=31 days. Default tomorrow. */
        date_to?: string;
        key_id?: string;
        model_alias?: string;
        source_id?: string;
        page_size?: number;
        cursor?: string;
        currency?: string;
        price_version?: string;
      };
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description UTC day/key/alias/source grouped rows. Sum all result counts = admitted_total; known tokens and missing counts separate. Ascending dimension cursor. */
      200: {
        headers: {
          /** @description Server generated trusted request id. */
          "X-Request-ID"?: string;
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["SummaryPage"];
        };
      };
      /** @description Structured sanitized error; see architecture error mapping. */
      400: {
        headers: {
          /** @description Server generated trusted request id. */
          "X-Request-ID"?: string;
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured sanitized error; see architecture error mapping. */
      401: {
        headers: {
          /** @description Server generated trusted request id. */
          "X-Request-ID"?: string;
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured sanitized error; see architecture error mapping. */
      503: {
        headers: {
          /** @description Server generated trusted request id. */
          "X-Request-ID"?: string;
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
    };
  };
  listModels: {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Valid platform key; no generation quota charged; enabled models only. */
      200: {
        headers: {
          /** @description Server generated trusted request id. */
          "X-Request-ID"?: string;
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["PublicModelList"];
        };
      };
      /** @description Structured sanitized error; see architecture error mapping. */
      401: {
        headers: {
          /** @description Server generated trusted request id. */
          "X-Request-ID"?: string;
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured sanitized error; see architecture error mapping. */
      503: {
        headers: {
          /** @description Server generated trusted request id. */
          "X-Request-ID"?: string;
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
    };
  };
  createChatCompletion: {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody: {
      content: {
        "application/json": components["schemas"]["ChatRequest"];
      };
    };
    responses: {
      /** @description Text subset only. No generation retry/replay. One authoritative admission via private Higress ext-auth. stream=true returns SSE; error after stream starts uses event:error and closes without DONE. */
      200: {
        headers: {
          /** @description Server generated trusted request id. */
          "X-Request-ID"?: string;
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ChatResponse"];
          "text/event-stream": string;
        };
      };
      /** @description Structured sanitized error; see architecture error mapping. */
      400: {
        headers: {
          /** @description Server generated trusted request id. */
          "X-Request-ID"?: string;
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured sanitized error; see architecture error mapping. */
      401: {
        headers: {
          /** @description Server generated trusted request id. */
          "X-Request-ID"?: string;
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured sanitized error; see architecture error mapping. */
      403: {
        headers: {
          /** @description Server generated trusted request id. */
          "X-Request-ID"?: string;
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description policy_changed or state_conflict; no reset. */
      409: {
        headers: {
          /** @description Server generated trusted request id. */
          "X-Request-ID"?: string;
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured sanitized error; see architecture error mapping. */
      413: {
        headers: {
          /** @description Server generated trusted request id. */
          "X-Request-ID"?: string;
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured sanitized error; see architecture error mapping. */
      429: {
        headers: {
          /** @description Server generated trusted request id. */
          "X-Request-ID"?: string;
          /** @description Seconds; quota uses next UTC reset, concurrency candidate 1. Never authorizes automatic generation retries. */
          "Retry-After"?: number;
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured sanitized error; see architecture error mapping. */
      500: {
        headers: {
          /** @description Server generated trusted request id. */
          "X-Request-ID"?: string;
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured sanitized error; see architecture error mapping. */
      502: {
        headers: {
          /** @description Server generated trusted request id. */
          "X-Request-ID"?: string;
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured sanitized error; see architecture error mapping. */
      503: {
        headers: {
          /** @description Server generated trusted request id. */
          "X-Request-ID"?: string;
          /** @description Seconds; quota uses next UTC reset, concurrency candidate 1. Never authorizes automatic generation retries. */
          "Retry-After"?: number;
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured sanitized error; see architecture error mapping. */
      504: {
        headers: {
          /** @description Server generated trusted request id. */
          "X-Request-ID"?: string;
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
    };
  };
  liveness: {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Cluster probe only. Process liveness; no paid upstream probe. */
      200: {
        headers: {
          /** @description Server generated trusted request id. */
          "X-Request-ID"?: string;
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Health"];
        };
      };
      /** @description Structured sanitized error; see architecture error mapping. */
      500: {
        headers: {
          /** @description Server generated trusted request id. */
          "X-Request-ID"?: string;
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
    };
  };
  readiness: {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Cluster probe only. Writable primary, expected route revision, dependencies and no drain. */
      200: {
        headers: {
          /** @description Server generated trusted request id. */
          "X-Request-ID"?: string;
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Health"];
        };
      };
      /** @description Structured sanitized error; see architecture error mapping. */
      503: {
        headers: {
          /** @description Server generated trusted request id. */
          "X-Request-ID"?: string;
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
    };
  };
  listModelReleases: {
    parameters: {
      query?: {
        namespace?: string;
        page_size?: number;
        cursor?: string;
      };
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Observed state. */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ReleaseList"];
        };
      };
      /** @description Structured sanitized error */
      400: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured sanitized error */
      401: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured sanitized error */
      403: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured sanitized error */
      404: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured sanitized error */
      409: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured sanitized error */
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
  createModelRelease: {
    parameters: {
      query?: never;
      header?: never;
      path?: never;
      cookie?: never;
    };
    requestBody: {
      content: {
        "application/json": components["schemas"]["ReleaseReleaseInput"];
      };
    };
    responses: {
      /** @description Desired intent accepted; not callable. */
      202: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ReleaseAccepted"];
        };
      };
      /** @description Structured sanitized error */
      400: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured sanitized error */
      401: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured sanitized error */
      403: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured sanitized error */
      404: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured sanitized error */
      409: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured sanitized error */
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
  getModelRelease: {
    parameters: {
      query?: never;
      header?: never;
      path: {
        namespace: string;
        name: string;
      };
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Observed state. */
      200: {
        headers: {
          /** @description Quoted resourceVersion */
          ETag?: string;
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ReleaseModelRelease"];
        };
      };
      /** @description Structured sanitized error */
      400: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured sanitized error */
      401: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured sanitized error */
      403: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured sanitized error */
      404: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured sanitized error */
      409: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured sanitized error */
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
  updateModelRelease: {
    parameters: {
      query?: never;
      header: {
        /** @description Quoted resourceVersion from ETag; no force adoption. */
        "If-Match": string;
      };
      path: {
        namespace: string;
        name: string;
      };
      cookie?: never;
    };
    requestBody: {
      content: {
        "application/json": components["schemas"]["ReleaseReleaseInput"];
      };
    };
    responses: {
      /** @description Desired intent accepted; not callable. */
      202: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ReleaseAccepted"];
        };
      };
      /** @description Structured sanitized error */
      400: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured sanitized error */
      401: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured sanitized error */
      403: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured sanitized error */
      404: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured sanitized error */
      409: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured sanitized error */
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
  deleteModelRelease: {
    parameters: {
      query?: never;
      header: {
        /** @description Quoted resourceVersion from ETag; no force adoption. */
        "If-Match": string;
      };
      path: {
        namespace: string;
        name: string;
      };
      cookie?: never;
    };
    requestBody?: never;
    responses: {
      /** @description Desired intent accepted; not callable. */
      202: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ReleaseAccepted"];
        };
      };
      /** @description Structured sanitized error */
      400: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured sanitized error */
      401: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured sanitized error */
      403: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured sanitized error */
      404: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured sanitized error */
      409: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured sanitized error */
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
  rollbackModelRelease: {
    parameters: {
      query?: never;
      header: {
        /** @description Quoted resourceVersion from ETag; no force adoption. */
        "If-Match": string;
      };
      path: {
        namespace: string;
        name: string;
      };
      cookie?: never;
    };
    requestBody: {
      content: {
        "application/json": components["schemas"]["ReleaseRollbackInput"];
      };
    };
    responses: {
      /** @description Desired intent accepted; not callable. */
      202: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ReleaseAccepted"];
        };
      };
      /** @description Structured sanitized error */
      400: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured sanitized error */
      401: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured sanitized error */
      403: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured sanitized error */
      404: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured sanitized error */
      409: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured sanitized error */
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
  getReleaseOperation: {
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
      /** @description Observed state. */
      200: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["ReleaseOperation"];
        };
      };
      /** @description Structured sanitized error */
      400: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured sanitized error */
      401: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured sanitized error */
      403: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured sanitized error */
      404: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured sanitized error */
      409: {
        headers: {
          [name: string]: unknown;
        };
        content: {
          "application/json": components["schemas"]["Error"];
        };
      };
      /** @description Structured sanitized error */
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
