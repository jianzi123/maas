// Explicit development/test transport. This file is removed by the production build.
import fixture from "./fixture-data.json";
import { validate, type S, type D } from "./api/contracts";
import stable from "../contracts/openapi-v0.4.json";
export const now = "2026-11-05T09:50:00Z",
  rid = "00000000-0000-4000-8000-000000000001",
  keyId = "00000000-0000-4000-8000-000000000002";
export const lookupSample = fixture.cases.find(
  (x) => x.name === "cancelled_usage_unknown_slot_quarantined",
)!.value as D["RequestLookupPage"];
export const historySample = fixture.cases.find(
  (x) => x.name === "retained_external_revision",
)!.value as D["ReleaseRevisionPage"];
const record = lookupSample.data[0]!;
const counters = { requests: "0", tokens: "0", money_atomic: "0" };
export const keySample: S["Key"] = {
  id: keyId,
  name: "开发验证 Key（模拟）",
  key_prefix: "fixture_only",
  state: "active",
  created_at: now,
  revoked_at: null,
  budget_policy: {
    window_kind: "utc_day",
    revision: "fixture-budget-v1",
    limits: {
      requests: "7",
      tokens: "900719925474099312345",
      money: {
        currency: "USD",
        limit_atomic: "99999999999999999999999999999999999999",
      },
    },
  },
  budget_state: {
    window_kind: "utc_day",
    window_start: "2026-11-05T00:00:00Z",
    window_end: "2026-11-06T00:00:00Z",
    admission_blocked: false,
    block_reason: null,
    currency: "USD",
    known_used: { requests: "1", tokens: "0", money_atomic: "0" },
    inflight_reserved: { ...counters },
    uncertainty_held: { requests: "0", tokens: "140", money_atomic: "520000" },
    available: {
      requests: "6",
      tokens: "900719925474099312205",
      money_atomic: "99999999999999999999999999999999479999",
    },
  },
};
export const releaseSample: S["ReleaseModelRelease"] = {
  ...fixture.external,
  apiVersion: "serving.maas.example/v1alpha1",
  kind: "ModelRelease",
  spec: fixture.external.spec as S["ReleaseSpec"],
  metadata: {
    ...fixture.external.metadata,
    uid: historySample.requested_cr_uid,
    generation: 2,
    resourceVersion: "420",
  },
  status: {
    observedGeneration: 2,
    phase: "Degraded",
    desiredRevision: "a".repeat(64),
    activeRevision: "c".repeat(64),
    activeGeneration: 1,
    publication_id: record.invocation_binding.publication_id,
    activation_epoch: 1,
    availableGroups: 0,
    conditions: [
      {
        type: "Accepted",
        status: "True",
        reason: "Accepted",
        message: "模拟：候选配置已受理",
        observedGeneration: 2,
        lastTransitionTime: now,
      },
      {
        type: "GatewayApplied",
        status: "Unknown",
        reason: "EvidenceMissing",
        message: "模拟：候选网关证据缺失",
        observedGeneration: 2,
        lastTransitionTime: now,
      },
      {
        type: "Callable",
        status: "True",
        reason: "PreviousActive",
        message: "模拟：旧活动版本仍可调用",
        observedGeneration: 1,
        lastTransitionTime: now,
      },
    ],
    resources: [],
    operation: null,
  },
};
export const modelSample: S["AdminModel"] = {
  id: "model-a",
  display_name: "DeepSeek · 开发样例",
  object: "model",
  owned_by: "maas",
  source_type: "external",
  source_id: record.source_id,
  check_state: "unknown",
  checked_at: null,
  config_revision: "fixture-v1",
  callable: true,
  release_binding: record.invocation_binding,
  capabilities: {
    streaming: true,
    verified_max_output_tokens: 40,
    temperature_supported: false,
    usage_available: "unavailable",
    capability_revision: "fixture-only",
    hard_budget_status: "verified",
    budget_unavailable_reason: null,
    protocols: ["chat_completions"],
  },
};
const zeroSummary = Object.fromEntries(
  Object.entries(stable.components.schemas.SummaryRow.properties).map(
    ([k, v]) => [k, "type" in v && v.type === "integer" ? 0 : null],
  ),
);
export const summarySample = {
  ...zeroSummary,
  quota_date: "2026-11-04",
  key_id: keyId,
  model_alias: "model-a",
  source_id: record.source_id,
  source_type: "external",
  admitted_total: 1,
  cancelled: 1,
  quota_used: 1,
  submitted_known: 1,
  missing_input_requests: 1,
  missing_output_requests: 1,
  missing_total_requests: 1,
  missing_token_requests: 1,
  currency: "USD",
  price_version: "synthetic-price-v1",
  cost_known_atomic: "0",
  money_uncertainty_held_atomic: "520000",
  token_uncertainty_held: "140",
  missing_cost_requests: 1,
} as S["SummaryRow"];
let loggedIn = false;
let keys = [structuredClone(keySample)],
  releases = [structuredClone(releaseSample)],
  operation: S["ReleaseOperation"] | null = null;
export function resetFixtures() {
  keys = [structuredClone(keySample)];
  releases = [structuredClone(releaseSample)];
  operation = null;
}
function json(value: unknown, status = 200) {
  return Response.json(value, {
    status,
    headers: {
      "Cache-Control": "no-store",
      "X-Request-ID": "00000000-0000-4000-8000-000000000099",
    },
  });
}
export function fixtureError(code: S["Error"]["error"]["code"], status = 503) {
  return json(
    {
      error: {
        code,
        message: "Synthetic fixture failure",
        request_id: rid,
        retryable: false,
        reset_at: null,
        retry_after_seconds: null,
        param: null,
        budget_dimension: null,
        policy_revision: null,
      },
    },
    status,
  );
}
export const fixtureFetch: typeof fetch = async (input, init = {}) => {
  const u = new URL(String(input), "https://fixture.invalid"),
    p = u.pathname,
    method = init.method ?? "GET",
    body = init.body ? JSON.parse(String(init.body)) : undefined;
  const empty =
    typeof window !== "undefined" &&
    new URLSearchParams(window.location.search).get("scenario") === "empty";
  if (init.signal?.aborted) throw new DOMException("Aborted", "AbortError");
  if (p.endsWith("/session")) {
    if (method === "POST") loggedIn = true;
    if (
      method === "GET" &&
      typeof window !== "undefined" &&
      new URLSearchParams(window.location.search).get("scenario") === "login" &&
      !loggedIn
    )
      return fixtureError("unauthenticated", 401);
    return method === "DELETE"
      ? new Response(null, { status: 204 })
      : json({
          admin_id: keyId,
          expires_at: "2099-01-01T00:00:00Z",
          csrf_token: "fixture-csrf-token-only-00000000000000000000",
        });
  }
  if (p.endsWith("/models"))
    return json({
      object: "list",
      data: empty
        ? []
        : [
            modelSample,
            {
              ...modelSample,
              id: "private-example",
              display_name: "SGLang · 私有样例",
              source_type: "internal",
              callable: false,
              release_binding: null,
              capabilities: {
                ...modelSample.capabilities,
                hard_budget_status: "unverified",
                budget_unavailable_reason: "开发夹具：未提供 GPU / 网关证据",
              },
            },
          ],
    });
  if (p.endsWith("/keys") && method === "GET")
    return json({
      data: empty ? [] : keys,
      next_cursor: null,
      generated_at: now,
      data_complete: true,
    });
  if (p.endsWith("/keys") && method === "POST") {
    validate("KeyCreate", body);
    const key = {
      ...structuredClone(keySample),
      id: crypto.randomUUID(),
      name: body.name,
      budget_policy: { ...body.budget_policy, revision: "fixture-created" },
    };
    keys.push(key);
    return json({ key, secret: "fixture_only_not_a_credential_000001" }, 201);
  }
  if (p.includes("/keys/") && method === "POST") {
    const k = keys.find((k) => p.includes(k.id));
    if (!k) return fixtureError("not_found", 404);
    k.state = "revoked";
    k.revoked_at = now;
    return json(k);
  }
  if (p.includes("/keys/") && method === "PATCH") {
    validate("KeyPatch", body);
    const k = keys.find((k) => p.endsWith(k.id));
    if (!k) return fixtureError("not_found", 404);
    k.budget_policy.limits = body.limits;
    return json(k);
  }
  if (p.endsWith("/usage/requests")) {
    if (u.searchParams.has("request_id")) {
      const result = structuredClone(lookupSample),
        id = u.searchParams.get("request_id")!;
      result.lookup.request_id = id;
      for (const row of result.data) row.request_id = id;
      return json(result);
    }
    return json({
      data: empty ? [] : [record],
      next_cursor: null,
      generated_at: now,
      data_complete: true,
    });
  }
  if (p.endsWith("/usage/summary"))
    return json({
      data: empty ? [] : [summarySample],
      next_cursor: null,
      generated_at: now,
      data_complete: true,
    });
  if (p.endsWith("/revisions")) return json(historySample);
  if (p.includes("/release-operations/"))
    return operation ? json(operation) : fixtureError("not_found", 404);
  if (p.endsWith("/model-releases") && method === "GET")
    return json({
      data: empty ? [] : releases,
      next_cursor: null,
      generated_at: now,
    });
  if (p.includes("/model-releases") && method === "GET") {
    const r = releases.find((x) => p.endsWith(x.metadata.name));
    return r ? json(r) : fixtureError("not_found", 404);
  }
  if (p.includes("/model-releases") && method !== "GET") {
    const r = releases[0] ?? releaseSample;
    operation = {
      id: "00000000-0000-4000-8000-000000000080",
      action:
        method === "DELETE"
          ? "Delete"
          : p.endsWith("/rollback")
            ? "Rollback"
            : method === "POST"
              ? "Create"
              : "Update",
      state: "Accepted",
      namespace: r.metadata.namespace,
      name: r.metadata.name,
      cr_uid: r.metadata.uid ?? null,
      requested_generation: r.metadata.generation ?? null,
      publication_id: null,
      created_at: now,
      updated_at: now,
      reason: null,
      message: "模拟：仅受理，未证明已生效",
    };
    return json({ operation, resource: r }, 202);
  }
  if (p === "/v1/chat/completions") {
    validate("ChatRequest", body);
    const encoder = new TextEncoder();
    let timer: ReturnType<typeof setInterval> | undefined;
    let listener: () => void = () => {};
    const text = [
      "这是开发夹具的流式响应。",
      "停止传输后，可用原请求 ID 回查。",
      "Token 未由上游提供，仍展示未知。",
    ];
    let i = 0;
    const stream = new ReadableStream<Uint8Array>({
      start(c) {
        listener = () => {
          clearInterval(timer);
          c.error(new DOMException("Aborted", "AbortError"));
        };
        init.signal?.addEventListener("abort", listener, { once: true });
        timer = setInterval(() => {
          if (i < text.length) {
            c.enqueue(
              encoder.encode(
                "data: " +
                  JSON.stringify({
                    id: "chatcmpl-" + rid,
                    object: "chat.completion.chunk",
                    created: 1,
                    model: body.model,
                    choices: [
                      {
                        index: 0,
                        delta: { content: text[i++] },
                        finish_reason: null,
                      },
                    ],
                  }) +
                  "\r\n\r\n",
              ),
            );
          } else {
            c.enqueue(
              encoder.encode(
                "data: " +
                  JSON.stringify({
                    id: "chatcmpl-" + rid,
                    object: "chat.completion.chunk",
                    created: 1,
                    model: body.model,
                    choices: [{ index: 0, delta: {}, finish_reason: "stop" }],
                    usage: record.usage,
                  }) +
                  "\n\ndata: [DONE]\n\n",
              ),
            );
            clearInterval(timer);
            init.signal?.removeEventListener("abort", listener);
            c.close();
          }
        }, 220);
      },
      cancel() {
        clearInterval(timer);
        init.signal?.removeEventListener("abort", listener);
      },
    });
    return new Response(stream, {
      headers: { "Content-Type": "text/event-stream", "X-Request-ID": rid },
    });
  }
  return fixtureError("dependency_unavailable");
};
