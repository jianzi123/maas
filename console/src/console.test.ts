import { describe, it, expect, vi, afterEach } from "vitest";
import { mount, flushPromises } from "@vue/test-utils";
import { Api, ApiError, api, ADMIN } from "./api/client";
import { validate } from "./api/contracts";
import { lookupRequest, revisions, canRollback } from "./api/recovery";
import { streamChat } from "./api/stream";
import { budgetInput, callableLabel, display, latestOnly } from "./domain";
import Keys from "./pages/Keys.vue";
import Models from "./pages/Models.vue";
import {
  fixtureFetch,
  fixtureError,
  keySample,
  releaseSample,
  historySample,
  lookupSample,
  modelSample,
  rid,
  now,
  resetFixtures,
  summarySample,
} from "./fixtures";
import data from "./fixture-data.json";
afterEach(() => {
  vi.restoreAllMocks();
  resetFixtures();
});
describe("shared contract sample consumer", () => {
  for (const c of data.cases)
    it(c.name, () => {
      const call = () => validate(c.schema, c.value, "draft");
      if (c.expected_valid) expect(call).not.toThrow();
      else expect(call).toThrow();
    });
  it("fixtures conform to stable response types", () => {
    for (const [name, value] of Object.entries({
      Key: keySample,
      ReleaseModelRelease: releaseSample,
      AdminModel: modelSample,
      SummaryRow: summarySample,
    }))
      expect(() => validate(name, value)).not.toThrow();
  });
});
describe("explicit budgets and display", () => {
  it("keeps all 38 digits, zero and disabled dimensions distinct", () => {
    const f = {
      window: "utc_day",
      requests: "0",
      tokens: "",
      money: "9".repeat(38),
      currency: "USD",
    };
    const p = budgetInput(f);
    expect(p.limits.requests).toBe("0");
    expect(p.limits.tokens).toBeNull();
    expect(p.limits.money?.limit_atomic).toBe("9".repeat(38));
    expect(display(null)).toContain("未知");
    expect(display(0)).toBe("0");
  });
  it("rejects missing period and noncanonical / imprecise amounts", () => {
    for (const requests of ["01", "-1", "1.2", "1e9", "9".repeat(39)])
      expect(() =>
        budgetInput({
          window: "utc_day",
          requests,
          tokens: "",
          money: "",
          currency: "",
        }),
      ).toThrow();
    expect(() =>
      budgetInput({
        window: "",
        requests: "",
        tokens: "",
        money: "",
        currency: "",
      }),
    ).toThrow();
  });
  it("old callable publication survives failed desired candidate", () => {
    expect(releaseSample.status?.phase).toBe("Degraded");
    expect(callableLabel(releaseSample)).toBe("活动版本可调用");
    const r = structuredClone(releaseSample);
    r.status!.conditions = [];
    expect(callableLabel(r)).toContain("未知");
  });
  it("discards out-of-order readonly results", async () => {
    const gate = latestOnly<string>(),
      commit = vi.fn();
    let resolve!: (v: string) => void;
    const first = gate.run(
      () => new Promise<string>((r) => (resolve = r)),
      commit,
    );
    await gate.run(async () => "new", commit);
    resolve("old");
    await first;
    expect(commit.mock.calls).toEqual([["new"]]);
  });
});
describe("transport and recovery invariants", () => {
  it("sends management CSRF and same-origin cookies, without automatic retry", async () => {
    const f = vi.fn<typeof fetch>(
      async () => new Response(null, { status: 204 }),
    );
    const c = new Api(f);
    c.csrf = "memory-only";
    await c.response(ADMIN + "/session", { method: "DELETE" });
    expect(f).toHaveBeenCalledTimes(1);
    const init = f.mock.calls[0]?.[1] as RequestInit;
    expect(init.credentials).toBe("same-origin");
    expect(new Headers(init.headers).get("X-CSRF-Token")).toBe("memory-only");
  });
  it("latches ambiguous write errors, no retries, no raw body exposure", async () => {
    const f = vi.fn(async () => {
      throw new Error("PRIVATE_UPSTREAM_CREDENTIAL");
    });
    const c = new Api(f);
    await expect(
      c.json("/api/admin/v1/keys", "KeyCreated", {
        method: "POST",
        body: "{}",
      }),
    ).rejects.toMatchObject({ uncertain: true });
    expect(f).toHaveBeenCalledTimes(1);
  });
  it("exact lookup has only original request_id, and never adopts read response header", async () => {
    const f = vi.fn(fixtureFetch);
    const result = await lookupRequest(new Api(f), rid);
    expect(result.lookup.request_id).toBe(rid);
    const url = new URL(String(f.mock.calls[0]![0]), "https://test.invalid");
    expect([...url.searchParams.keys()]).toEqual(["request_id"]);
  });
  it("rejects an old server list instead of guessing the first request", async () => {
    const c = new Api(async () =>
      Response.json({
        data: lookupSample.data,
        next_cursor: null,
        generated_at: now,
        data_complete: true,
      }),
    );
    await expect(lookupRequest(c, rid)).rejects.toThrow();
  });
  it("rejects a valid envelope for another request", async () => {
    const p = structuredClone(lookupSample);
    p.lookup.request_id = "00000000-0000-4000-8000-000000000099";
    const c = new Api(async () => Response.json(p));
    await expect(lookupRequest(c, rid)).rejects.toThrow("关联不一致");
  });
  it("503 lookup is not empty success", async () => {
    await expect(
      lookupRequest(
        new Api(async () => fixtureError("dependency_unavailable")),
        rid,
      ),
    ).rejects.toMatchObject({ status: 503 });
  });
  it("history is scoped to original CR UID and stale / replaced eligibility never authorizes rollback", async () => {
    const f = vi.fn(fixtureFetch);
    const h = await revisions(new Api(f), releaseSample);
    expect(String(f.mock.calls[0]![0])).toContain(
      "cr_uid=" + releaseSample.metadata.uid,
    );
    expect(canRollback(h, h.data[0]!, releaseSample)).toBe(true);
    const other = structuredClone(releaseSample);
    other.metadata.resourceVersion = "421";
    expect(canRollback(h, h.data[0]!, other)).toBe(false);
    expect(
      canRollback(
        { ...h, resource_state: "replaced" },
        h.data[0]!,
        releaseSample,
      ),
    ).toBe(false);
  });
});
function sse(
  parts: string[],
  headers: Record<string, string> = {
    "Content-Type": "text/event-stream",
    "X-Request-ID": rid,
  },
) {
  const encoded = new TextEncoder().encode(parts.join(""));
  let offset = 0;
  return new Response(
    new ReadableStream({
      pull(c) {
        if (offset >= encoded.length) c.close();
        else c.enqueue(encoded.slice(offset, ++offset));
      },
    }),
    { headers },
  );
}
const chunk = (
  content: string,
  finish: string | null = null,
  usage?: unknown,
) =>
  "data: " +
  JSON.stringify({
    id: "chatcmpl-" + rid,
    object: "chat.completion.chunk",
    created: 1,
    model: "model-a",
    choices: [{ index: 0, delta: { content }, finish_reason: finish }],
    ...(usage ? { usage } : {}),
  }) +
  "\r\n\r\n";
const request = {
  model: "model-a",
  messages: [{ role: "user" as const, content: "test" }],
  stream: true,
};
describe("stream safety", () => {
  it("handles byte-split UTF8 and CRLF, cumulative usage and terminal DONE", async () => {
    const f = vi.fn<typeof fetch>(async () =>
      sse([
        chunk("中文"),
        chunk("", "stop", lookupSample.data[0]!.usage),
        "data: [DONE]\r\n\r\n",
      ]),
    );
    const c = new Api(f);
    c.csrf = "admin-must-not-go";
    const hook = { id: vi.fn(), chunk: vi.fn(), usage: vi.fn() };
    await streamChat(
      c,
      "fixture_only_secret",
      request,
      new AbortController().signal,
      hook,
    );
    expect(hook.chunk).toHaveBeenCalledWith("中文");
    expect(hook.usage).toHaveBeenCalledTimes(1);
    expect(hook.id).toHaveBeenCalledWith(rid);
    const init = f.mock.calls[0]?.[1] as RequestInit;
    expect(init.credentials).toBe("omit");
    expect(new Headers(init.headers).has("X-CSRF-Token")).toBe(false);
  });
  it("EOF without DONE is interrupted", async () => {
    await expect(
      streamChat(
        new Api(async () => sse([chunk("partial")])),
        "fixture",
        request,
        new AbortController().signal,
        { id: vi.fn(), chunk: vi.fn(), usage: vi.fn() },
      ),
    ).rejects.toThrow("中断");
  });
  it("DONE without a finished choice is a protocol failure", async () => {
    await expect(
      streamChat(
        new Api(async () => sse(["data: [DONE]\n\n"])),
        "fixture",
        request,
        new AbortController().signal,
        { id: vi.fn(), chunk: vi.fn(), usage: vi.fn() },
      ),
    ).rejects.toThrow();
  });
  it("event:error closes without claiming success", async () => {
    const e = await fixtureError("accounting_unavailable").json();
    await expect(
      streamChat(
        new Api(async () =>
          sse(["event: error\ndata: " + JSON.stringify(e) + "\n\n"]),
        ),
        "fixture",
        request,
        new AbortController().signal,
        { id: vi.fn(), chunk: vi.fn(), usage: vi.fn() },
      ),
    ).rejects.toMatchObject({ code: "accounting_unavailable" });
  });
  it("stop aborts transport without another POST", async () => {
    const f = vi.fn(fixtureFetch),
      controller = new AbortController();
    const promise = streamChat(
      new Api(f),
      "fixture",
      request,
      controller.signal,
      { id: () => controller.abort(), chunk: vi.fn(), usage: vi.fn() },
    );
    await expect(promise).rejects.toThrow();
    expect(f).toHaveBeenCalledTimes(1);
  });
});
describe("component interaction", () => {
  it("creates one Key, shows secret once, then clears it without storage", async () => {
    api.fetcher = fixtureFetch;
    const w = mount(Keys);
    await w.find('[data-testid="create-key"]').trigger("click");
    await flushPromises();
    const inputs = w.findAll("form input");
    expect((inputs[1]!.element as HTMLInputElement).value).toBe("");
    await inputs[0]!.setValue("new fixture");
    await w.find("form select").setValue("utc_day");
    await inputs[1]!.setValue("0");
    await w.find("form").trigger("submit");
    await flushPromises();
    expect(w.find('[data-testid="one-time-secret"]').exists()).toBe(true);
    expect(w.text()).toContain("99999999999999999999999999999999999999");
    const close = w
      .findAll("button")
      .find((b) => b.text().includes("我已保存"))!;
    await close.trigger("click");
    expect(w.find('[data-testid="one-time-secret"]').exists()).toBe(false);
    expect(localStorage.length).toBe(0);
    w.unmount();
  });
  it("unknown Key creation response disables further writes", async () => {
    const f = vi.fn<typeof fetch>(async (path, init) => {
      if (init?.method === "POST") throw new Error("ack lost");
      return fixtureFetch(path, init);
    });
    api.fetcher = f;
    const w = mount(Keys);
    await w.find('[data-testid="create-key"]').trigger("click");
    await flushPromises();
    await w.find("form input").setValue("unknown");
    await w.find("form select").setValue("utc_day");
    await w.find("form").trigger("submit");
    await flushPromises();
    expect(w.text()).toContain("结果未知");
    await w.find("form").trigger("submit");
    await flushPromises();
    expect(
      f.mock.calls.filter(([, init]) => init?.method === "POST"),
    ).toHaveLength(1);
    w.unmount();
  });
  it("models empty, loading and dependency error paths render honestly", async () => {
    let resolve!: (r: Response) => void;
    api.fetcher = () => new Promise((r) => (resolve = r));
    const w = mount(Models);
    await w.vm.$nextTick();
    expect(w.text()).toContain("正在加载");
    resolve(Response.json({ object: "list", data: [] }));
    await flushPromises();
    expect(w.text()).toContain("尚无模型");
    api.fetcher = async () => fixtureError("dependency_unavailable");
    await w.find("button").trigger("click");
    await flushPromises();
    expect(w.find('[role="alert"]').exists()).toBe(true);
    w.unmount();
  });
});
