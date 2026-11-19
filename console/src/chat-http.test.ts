import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
const { webcrypto } = await vi.importActual<{ webcrypto: Crypto }>(
  "node:crypto",
);
import { HTTPChat } from "./chat/http";
import { Api } from "./api/client";

const root = "/api/agent/v1",
  sid = "10000000-0000-4000-8000-000000000001",
  rid = "10000000-0000-4000-8000-000000000002",
  mid = "10000000-0000-4000-8000-000000000003",
  owner = "10000000-0000-4000-8000-000000000004",
  eid = "10000000-0000-4000-8000-000000000005";
const date = "2026-11-19T05:00:00Z";
const limits = {
  max_steps: 4,
  max_model_calls: 4,
  max_tool_calls: 8,
  max_duration_ms: 10000,
  tool_timeout_ms: 1000,
  max_tool_output_bytes: 8192,
  max_context_tokens: 32768,
  no_progress_limit: 3,
  max_tokens: "100",
  max_money_atomic: "100",
  currency: "TST",
};
const config = { limits, tools: [] };
const caps = {
  protocol_revision: "ar.api/1.0",
  event_versions: ["ar.session.event/1.0"],
  model_modes: [
    {
      model_alias: "demo",
      text_protocol: "text-v1",
      tools_protocol: "tools-v1",
      capability_revision: "controlled-v1",
      approval_state: "controlled",
    },
  ],
  tools: [],
  attachments_enabled: false,
};
const conversation = {
  id: sid,
  owner_id: owner,
  title: "原会话",
  model_alias: "demo",
  revision: "1",
  active_run_id: null,
  created_at: date,
  updated_at: date,
  deleted_at: null,
};
const key = "maas.chat.ar1.pending.v1";
const json = (v: unknown, status = 200, headers: Record<string, string> = {}) =>
  new Response(JSON.stringify(v), {
    status,
    headers: { "Content-Type": "application/json", ETag: '"1"', ...headers },
  });
const err = (code: string, status: number) =>
  json(
    {
      error: {
        code,
        message: code,
        http_request_id: eid,
        run_id: null,
        child_request_id: null,
        retryable: false,
        snapshot_required: status === 410,
      },
    },
    status,
    { "X-Request-ID": eid },
  );
const run = (extra: Record<string, unknown> = {}) => ({
  id: rid,
  session_id: sid,
  client_operation_id: eid,
  mode: "chat",
  state: "running",
  revision: "1",
  fence: "1",
  input_head_message_id: mid,
  model_alias: "demo",
  protocol_revision: "text-v1",
  limits: { ...limits, max_model_calls: 1 },
  cancel_requested: false,
  step_count: 1,
  child_request_ids: [eid],
  usage_groups: [],
  aggregation_complete: false,
  last_event_seq: "1",
  resume_cursor: "opaque-A",
  reason: null,
  created_at: date,
  deadline_at: "2026-11-19T05:00:10Z",
  finished_at: null,
  ...extra,
});
const message = (text: string) => ({
  id: mid,
  session_id: sid,
  position: "1",
  role: "assistant",
  parts: [{ type: "text", text }],
  status: "partial",
  run_id: rid,
  supersedes_message_id: null,
  created_at: date,
});
const snapshot = (
  runs: unknown[] = [],
  messages: unknown[] = [],
  seq = "0",
  cursor: string | null = null,
) => ({
  conversation: { ...conversation, active_run_id: runs.length ? rid : null },
  messages,
  runs,
  last_event_seq: seq,
  event_run_id: runs.length ? rid : null,
  resume_cursor: cursor,
  messages_next_cursor: null,
});
const sse = (data: unknown, seq = "2", sidOverride = sid) => ({
  version: "ar.session.event/1.0",
  id: eid,
  session_id: sidOverride,
  run_id: rid,
  seq,
  cursor: "opaque-B",
  created_at: date,
  type: "message.delta",
  data,
});
const frame = (e: ReturnType<typeof sse>) =>
  "id: " +
  e.cursor +
  "\nevent: " +
  e.type +
  "\ndata: " +
  JSON.stringify(e) +
  "\n\n";
beforeEach(() => {
  sessionStorage.clear();
  vi.stubGlobal("crypto", webcrypto);
});
afterEach(() => {
  sessionStorage.clear();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("AR-1 durable unknown command recovery", () => {
  it("lost creation ACK survives a new adapter; only original GET/hash mapping unlocks, no stored body or credentials", async () => {
    let posts = 0;
    const fetcher = vi.fn(async (path: string, init: RequestInit = {}) => {
      if (path.endsWith("/capabilities")) return json(caps);
      if (init.method === "POST") {
        posts++;
        throw new TypeError("lost ACK");
      }
      if (path.includes("/session-creation-commands/")) {
        const p = JSON.parse(sessionStorage.getItem(key)!);
        return json({
          client_operation_id: p.operation,
          session_id: sid,
          state: "accepted",
          request_sha256: p.hash,
        });
      }
      if (path === root + "/sessions/" + sid)
        return json(snapshot(), 200, { ETag: '"1"' });
      throw Error("unexpected " + path);
    });
    const client = new Api(fetcher as typeof fetch);
    client.csrf = "MEMORY-CSRF";
    const first = new HTTPChat(config, client);
    await first.models();
    await expect(first.create("demo")).rejects.toThrow("未知");
    expect(first.hasPending()).toBe(true);
    const stored = sessionStorage.getItem(key)!;
    expect(stored).not.toContain("MEMORY-CSRF");
    expect(stored).not.toContain("新会话");
    expect(Object.keys(JSON.parse(stored)).sort()).toEqual([
      "hash",
      "kind",
      "operation",
    ]);
    const restored = new HTTPChat(config, client);
    expect((await restored.recover())!.id).toBe(sid);
    expect(restored.hasPending()).toBe(false);
    expect(posts).toBe(1);
    const post = fetcher.mock.calls.find(
      ([, init]) => init?.method === "POST",
    )!;
    expect(new Headers(post[1]!.headers).get("X-CSRF-Token")).toBe(
      "MEMORY-CSRF",
    );
    expect(post[1]!.credentials).toBe("same-origin");
  });
  it.each([404, 503])(
    "lookup %i never proves no dispatch and never permits an automatic create retry",
    async (status) => {
      sessionStorage.setItem(
        key,
        JSON.stringify({
          kind: "create",
          operation: eid,
          hash: "a".repeat(64),
        }),
      );
      const fetcher = vi.fn(async () =>
        err(status === 404 ? "not_found" : "dependency_unavailable", status),
      );
      const service = new HTTPChat(config, new Api(fetcher as typeof fetch));
      await expect(service.recover()).rejects.toThrow();
      await expect(service.create("demo")).rejects.toThrow("未知");
      expect(service.hasPending()).toBe(true);
      expect(fetcher.mock.calls).toHaveLength(1);
    },
  );
  it("wrong operation hash does not bind another session or release the pending barrier", async () => {
    sessionStorage.setItem(
      key,
      JSON.stringify({ kind: "create", operation: eid, hash: "a".repeat(64) }),
    );
    const fetcher = vi.fn(async () =>
      json({
        client_operation_id: eid,
        session_id: sid,
        state: "accepted",
        request_sha256: "b".repeat(64),
      }),
    );
    const service = new HTTPChat(config, new Api(fetcher as typeof fetch));
    await expect(service.recover()).rejects.toThrow("关联");
    expect(service.hasPending()).toBe(true);
    expect(fetcher.mock.calls).toHaveLength(1);
  });
  it("pending model capability is refused before any create POST", async () => {
    const fetcher = vi.fn(async () =>
      json({
        ...caps,
        model_modes: [{ ...caps.model_modes[0], approval_state: "pending" }],
      }),
    );
    const service = new HTTPChat(config, new Api(fetcher as typeof fetch));
    expect((await service.models())[0]!.modes).toEqual([]);
    await expect(service.create("demo")).rejects.toThrow();
    expect(fetcher.mock.calls).toHaveLength(1);
  });
});

describe("AR-1 opaque cursor/UTF-8 stream boundary", () => {
  const setup = async (events: string, options: { gone?: boolean } = {}) => {
    let reads = 0;
    const fetcher = vi.fn(async (path: string, _init: RequestInit = {}) => {
      if (path.includes("/events/stream"))
        return options.gone
          ? err("cursor_expired", 410)
          : new Response(events, {
              headers: { "Content-Type": "text/event-stream" },
            });
      if (
        path.endsWith("/steps?page_size=100") ||
        path.endsWith("/tool-calls?page_size=100")
      )
        return json({ data: [], next_cursor: null });
      if (path === root + "/sessions/" + sid) {
        const next = reads++ > 0;
        return json(
          snapshot(
            [
              run(
                next ? { last_event_seq: "2", resume_cursor: "opaque-B" } : {},
              ),
            ],
            [message(next ? "你🌏" : "你")],
            next ? "2" : "1",
            next ? "opaque-B" : "opaque-A",
          ),
          200,
          { ETag: '"1"' },
        );
      }
      throw Error("unexpected " + path);
    });
    const service = new HTTPChat(config, new Api(fetcher as typeof fetch));
    await service.read(sid);
    return { service, fetcher };
  };
  it("valid byte offset preserves Chinese/emoji and sends only after, never Last-Event-ID", async () => {
    const { service, fetcher } = await setup(
      frame(sse({ message_id: mid, offset: "3", text: "🌏" })),
    );
    const page = await service.events(sid, rid, "opaque-A");
    expect(page.snapshot.messages[0]!.content).toBe("你🌏");
    expect(page.snapshot.runs[0]!.cursor).toBe("opaque-B");
    expect(page.events[0]!.seq).toBe("2");
    expect(fetcher.mock.calls.some(([p]) => p.includes("after=opaque-A"))).toBe(
      true,
    );
    expect(fetcher.mock.calls.every(([, init]) => !init?.method)).toBe(true);
  });
  it.each(["1", "4"])(
    "rejects JS-character or wrong byte offset %s before projecting content",
    async (offset) => {
      const { service } = await setup(
        frame(sse({ message_id: mid, offset, text: "🌏" })),
      );
      await expect(service.events(sid, rid, "opaque-A")).rejects.toThrow(
        "关联",
      );
    },
  );
  it("rejects another session's valid-looking envelope", async () => {
    const { service } = await setup(
      frame(sse({ message_id: mid, offset: "3", text: "🌏" }, "2", owner)),
    );
    await expect(service.events(sid, rid, "opaque-A")).rejects.toThrow("关联");
  });
  it("duplicate run seq is rejected instead of double-appending a delta", async () => {
    const e = sse({ message_id: mid, offset: "3", text: "🌏" });
    const { service } = await setup(frame(e) + frame(e));
    await expect(service.events(sid, rid, "opaque-A")).rejects.toThrow("关联");
  });
  it("EOF does not fabricate a completed run", async () => {
    const { service } = await setup("");
    const page = await service.events(sid, rid, "opaque-A");
    expect(page.events).toHaveLength(0);
    expect(page.snapshot.runs[0]!.state).toBe("running");
  });
  it("410 recovers through a GET snapshot, without executing a model or tool", async () => {
    const { service, fetcher } = await setup("", { gone: true });
    expect(
      (await service.events(sid, rid, "opaque-A")).snapshot.runs[0]!.cursor,
    ).toBe("opaque-B");
    expect(fetcher.mock.calls.every(([, init]) => !init?.method)).toBe(true);
  });
  it("rejects a frame whose SSE id disagrees with envelope cursor", async () => {
    const { service } = await setup(
      frame(sse({ message_id: mid, offset: "3", text: "🌏" })).replace(
        "id: opaque-B",
        "id: forged",
      ),
    );
    await expect(service.events(sid, rid, "opaque-A")).rejects.toThrow("关联");
  });
});

it("large grouped amounts remain exact strings; completed and accounting completeness stay independent", async () => {
  const value = run({
    state: "completed",
    finished_at: date,
    usage_groups: [
      {
        currency: "TST",
        price_version: "v1",
        known_tokens: "900719925474099312345",
        known_money_atomic: "999999999999999999999",
        held_tokens: "8",
        inflight_tokens: "3",
        held_money_atomic: "7",
        inflight_money_atomic: "2",
      },
    ],
  });
  const fetcher = vi.fn(async (path: string) =>
    path === root + "/sessions/" + sid
      ? json(snapshot([value], [], "1", "opaque-A"), 200, { ETag: '"1"' })
      : json({ data: [], next_cursor: null }),
  );
  const r = (
    await new HTTPChat(config, new Api(fetcher as typeof fetch)).read(sid)
  ).runs[0]!;
  expect(r.usageGroups![0]!.known_tokens).toBe("900719925474099312345");
  expect(r.usageGroups![0]!.known_money_atomic).toBe("999999999999999999999");
  expect(r.aggregationComplete).toBe(false);
  expect(r.usage.tokens).toBeNull();
  expect(r.state).toBe("completed");
});

describe("AR-R01 revision-bound page recovery", () => {
  for (const resource of ["messages", "steps", "tool-calls"]) {
    it(
      "restarts the complete snapshot after " +
        resource +
        " cursor expires, using GET only",
      async () => {
        let reads = 0,
          expired = false;
        const calls: { path: string; method: string }[] = [];
        const fetcher = vi.fn(async (path: string, init?: RequestInit) => {
          calls.push({ path, method: init?.method ?? "GET" });
          if (path === root + "/sessions/" + sid) {
            reads++;
            const s = snapshot(
              [
                run({
                  last_event_seq: reads === 1 ? "1" : "2",
                  resume_cursor: reads === 1 ? "opaque-A" : "opaque-B",
                }),
              ],
              [message(reads === 1 ? "old" : "你好🌏")],
              reads === 1 ? "1" : "2",
              reads === 1 ? "opaque-A" : "opaque-B",
            );
            s.conversation.revision = String(reads);
            if (reads === 1 && resource === "messages")
              s.messages_next_cursor = "old-page" as any;
            return json(s, 200, { ETag: '"' + reads + '"' });
          }
          if (path.includes("/" + resource + "?") && !expired) {
            expired = true;
            return err("cursor_expired", 410);
          }
          return json({ data: [], next_cursor: null }, 200, {
            ETag: '"' + reads + '"',
          });
        });
        const service = new HTTPChat(config, new Api(fetcher as typeof fetch));
        const result = await service.read(sid);
        expect(reads).toBe(2);
        expect(result.messages.map((m) => m.content)).toEqual(["你好🌏"]);
        expect(result.runs[0]!.cursor).toBe("opaque-B");
        expect(calls.every((c) => c.method === "GET")).toBe(true);
        expect(calls.filter((c) => c.path.includes("old-page"))).toHaveLength(
          resource === "messages" ? 1 : 0,
        );
      },
    );
  }
  it("continuous mutation is bounded to three snapshots and never creates a run", async () => {
    let reads = 0;
    const calls: string[] = [];
    const fetcher = vi.fn(async (path: string, init?: RequestInit) => {
      calls.push(init?.method ?? "GET");
      if (path === root + "/sessions/" + sid) {
        reads++;
        const s = snapshot();
        s.messages_next_cursor = "expires" as any;
        return json(s, 200, { ETag: '"1"' });
      }
      return err("cursor_expired", 410);
    });
    await expect(
      new HTTPChat(config, new Api(fetcher as typeof fetch)).read(sid),
    ).rejects.toThrow("会话持续变化");
    expect(reads).toBe(3);
    expect(calls.every((c) => c === "GET")).toBe(true);
  });
  it("a malformed 410 does not trigger automatic snapshot recovery", async () => {
    let reads = 0;
    const fetcher = vi.fn(async (path: string) => {
      if (path === root + "/sessions/" + sid) {
        reads++;
        const s = snapshot();
        s.messages_next_cursor = "invalid" as any;
        return json(s, 200, { ETag: '"1"' });
      }
      const response = await err("cursor_expired", 410).json();
      response.error.snapshot_required = false;
      return json(response, 410, { "X-Request-ID": eid });
    });
    await expect(
      new HTTPChat(config, new Api(fetcher as typeof fetch)).read(sid),
    ).rejects.toThrow("关联");
    expect(reads).toBe(1);
  });
});

it("a late A page 410 cannot erase B snapshot or start another recovery loop", async () => {
  let reads = 0;
  let release!: (r: Response) => void;
  const oldPage = new Promise<Response>((r) => (release = r));
  const fetcher = vi.fn(async (path: string) => {
    if (path === root + "/sessions/" + sid) {
      reads++;
      const s = snapshot(
        [
          run({
            last_event_seq: reads === 1 ? "1" : "2",
            resume_cursor: reads === 1 ? "opaque-A" : "opaque-B",
          }),
        ],
        [message(reads === 1 ? "old" : "B你好🙂")],
        reads === 1 ? "1" : "2",
        reads === 1 ? "opaque-A" : "opaque-B",
      );
      s.conversation.revision = String(reads);
      if (reads === 1) s.messages_next_cursor = "A-page" as any;
      return json(s, 200, { ETag: '"' + reads + '"' });
    }
    if (path.includes("A-page")) return oldPage;
    return json({ data: [], next_cursor: null }, 200, {
      ETag: '"' + reads + '"',
    });
  });
  const service = new HTTPChat(config, new Api(fetcher as typeof fetch));
  const a = service.read(sid).catch((e) => e);
  await vi.waitFor(() =>
    expect(fetcher.mock.calls.some(([p]) => String(p).includes("A-page"))).toBe(
      true,
    ),
  );
  const b = await service.read(sid);
  expect(b.runs[0]!.cursor).toBe("opaque-B");
  release(err("cursor_expired", 410));
  await a;
  expect(reads).toBe(2);
  // B's cache remains usable by the next ordinary events call; an empty EOF reads a fresh B snapshot.
  fetcher.mockImplementation(async (path: string) => {
    if (path.includes("/events/stream"))
      return new Response("", {
        headers: { "Content-Type": "text/event-stream" },
      });
    if (path === root + "/sessions/" + sid) {
      const s = snapshot(
        [run({ last_event_seq: "2", resume_cursor: "opaque-B" })],
        [message("B你好🙂")],
        "2",
        "opaque-B",
      );
      s.conversation.revision = "2";
      return json(s, 200, { ETag: '"2"' });
    }
    return json({ data: [], next_cursor: null }, 200, { ETag: '"2"' });
  });
  const result = await service.events(sid, rid, "opaque-B");
  expect(result.snapshot.messages[0]!.content).toBe("B你好🙂");
  expect(result.snapshot.runs[0]!.cursor).toBe("opaque-B");
});

for (const resource of ["steps", "tool-calls"])
  for (const missing of [false, true]) {
    it(
      "AR-R01-C1 " +
        resource +
        " first page " +
        (missing ? "missing" : "changed") +
        " Session ETag cannot join root snapshot",
      async () => {
        let reads = 0;
        const fetcher = vi.fn(async (path: string, init?: RequestInit) => {
          if (path === root + "/sessions/" + sid) {
            reads++;
            const rev = String(reads);
            const s = snapshot(
              [run()],
              [message(reads === 1 ? "old" : "fresh")],
              "1",
              "opaque-A",
            );
            s.conversation.revision = rev;
            return json(s, 200, { ETag: '"' + rev + '"' });
          }
          if (path.includes("/" + resource + "?") && reads === 1) {
            const r = json({ data: [], next_cursor: null }, 200, {
              ETag: '"2"',
            });
            if (missing) r.headers.delete("ETag");
            return r;
          }
          return json({ data: [], next_cursor: null }, 200, {
            ETag: '"' + reads + '"',
          });
        });
        const service = new HTTPChat(config, new Api(fetcher as typeof fetch));
        if (missing) {
          await expect(service.read(sid)).rejects.toThrow("关联");
          expect(reads).toBe(1);
        } else {
          const s = await service.read(sid);
          expect(s.revision).toBe("2");
          expect(s.messages[0]!.content).toBe("fresh");
          expect(reads).toBe(2);
        }
        expect(
          fetcher.mock.calls.every(
            ([, init]) => (init?.method ?? "GET") === "GET",
          ),
        ).toBe(true);
      },
    );
  }

for (const [state, attempt] of [
  ["cancelled", 0],
  ["failed", 1],
  ["unknown", 1],
] as const) {
  it(
    "AR-R02 keeps authoritative " +
      state +
      " attempt=" +
      attempt +
      " without rerunning",
    async () => {
      const r = run({
        state: "limit_reached",
        reason: "max_duration",
        finished_at: date,
      });
      const call = {
        id: mid,
        run_id: rid,
        step_id: eid,
        name: "calculator",
        tool_revision: "1",
        args_sha256: "a".repeat(64),
        state,
        effect: "pure",
        attempt,
        idempotency_key: eid,
        source_call_id: "source-1",
        arguments: { expression: "1+1" },
        result:
          state === "cancelled"
            ? null
            : {
                type: "tool_result",
                call_id: mid,
                outcome: state,
                result: { message: "受控工具终态" },
              },
      };
      const fetcher = vi.fn(async (path: string, init?: RequestInit) => {
        expect(init?.method ?? "GET").toBe("GET");
        return path === root + "/sessions/" + sid
          ? json(snapshot([r], [], "1", "opaque-A"))
          : json({
              data: path.includes("/tool-calls?") ? [call] : [],
              next_cursor: null,
            });
      });
      const s = await new HTTPChat(
        config,
        new Api(fetcher as typeof fetch),
      ).read(sid);
      expect(s.runs[0]!.state).toBe("limit_reached");
      expect(s.runs[0]!.steps[0]!.label).toContain("实际尝试 " + attempt);
      expect(s.runs[0]!.steps[0]!.state).toBe(state);
      expect(s.runs[0]!.steps[0]!.output).toBe(
        state === "cancelled"
          ? undefined
          : JSON.stringify(call.result!.result, null, 2),
      );
      expect(s.runs[0]!.approvals).toEqual([]);
      expect(fetcher).toHaveBeenCalledTimes(3);
    },
  );
}
