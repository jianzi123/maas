import { describe, it, expect, vi, afterEach } from "vitest";
import { mount, flushPromises } from "@vue/test-utils";
import { Api, api, ADMIN } from "./api/client";
import { streamChat } from "./api/stream";
import { explain } from "./ui";
import { fixtureFetch, fixtureError, rid, resetFixtures } from "./fixtures";
import Releases from "./pages/Releases.vue";
afterEach(() => {
  vi.restoreAllMocks();
  resetFixtures();
});
describe("error and management interactions", () => {
  it("preserves original ID and reset metadata even for a rejected inference", async () => {
    const error = await fixtureError("request_budget_exceeded", 429).json();
    error.error.reset_at = "2026-11-06T00:00:00Z";
    error.error.retry_after_seconds = 9;
    const f = vi.fn<typeof fetch>(async () =>
      Response.json(error, { status: 429, headers: { "X-Request-ID": rid } }),
    );
    const id = vi.fn();
    let caught: unknown;
    try {
      await streamChat(
        new Api(f),
        "fixture",
        {
          model: "model-a",
          stream: true,
          messages: [{ role: "user", content: "test" }],
        },
        new AbortController().signal,
        { id, chunk: vi.fn(), usage: vi.fn() },
      );
    } catch (e) {
      caught = e;
    }
    expect(id).toHaveBeenCalledWith(rid);
    expect(explain(caught)).toContain("2026-11-06");
    expect(explain(caught)).toContain("9 秒");
    expect(f).toHaveBeenCalledTimes(1);
  });
  it("malformed successful write response is unknown, with no repeated write", async () => {
    const f = vi.fn<typeof fetch>(async () =>
      Response.json({ secret: "unexpected_private_body" }),
    );
    await expect(
      new Api(f).json(ADMIN + "/keys", "KeyCreated", {
        method: "POST",
        body: "{}",
      }),
    ).rejects.toMatchObject({ uncertain: true, code: "protocol_error" });
    expect(f).toHaveBeenCalledTimes(1);
  });
  it("rejects protocol-relative destinations before fetching", async () => {
    const f = vi.fn<typeof fetch>();
    await expect(new Api(f).response("//external.invalid")).rejects.toThrow();
    expect(f).not.toHaveBeenCalled();
  });
  it("admin 401 clears the local session through an expiry event", async () => {
    const expired = vi.fn();
    window.addEventListener("maas-session-expired", expired);
    try {
      await expect(
        new Api(async () => fixtureError("unauthenticated", 401)).session(),
      ).rejects.toThrow();
      expect(expired).toHaveBeenCalledTimes(1);
    } finally {
      window.removeEventListener("maas-session-expired", expired);
    }
  });
  it("pause uses the quoted server version, and accepted remains pending", async () => {
    const f = vi.fn(fixtureFetch);
    api.fetcher = f;
    const w = mount(Releases);
    await flushPromises();
    await w.find(".release-card").trigger("click");
    await flushPromises();
    const pause = w.findAll("button").find((x) => x.text() === "暂停发布")!;
    await pause.trigger("click");
    await flushPromises();
    const call = f.mock.calls.find(([, i]) => i?.method === "PUT")!;
    expect(new Headers(call[1]?.headers).get("If-Match")).toBe('"420"');
    expect(JSON.parse(String(call[1]?.body)).spec.lifecycle.desiredState).toBe(
      "Paused",
    );
    expect(w.text()).toContain("202");
    expect(w.text()).toContain("Accepted");
    expect(w.text()).not.toContain("Succeeded");
    w.unmount();
  });
});
