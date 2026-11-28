import { afterEach, it, expect, vi } from "vitest";
import { mount, flushPromises } from "@vue/test-utils";
import Playground from "./pages/Playground.vue";
import { api } from "./api/client";
import {
  fixtureFetch,
  fixtureError,
  lookupSample,
  rid,
  resetFixtures,
} from "./fixtures";
const original = api.fetcher;
let wrapper: ReturnType<typeof mount> | undefined;
afterEach(() => {
  wrapper?.unmount();
  api.fetcher = original;
  resetFixtures();
});
const known = {
  input_tokens: 12,
  output_tokens: 7,
  total_tokens: 19,
  input_cached_tokens: 4,
  reasoning_tokens: 3,
  source: "upstream",
  missing_reason: null,
};
function frame(text: string, finish = false, usage?: unknown) {
  return (
    "data: " +
    JSON.stringify({
      id: "chatcmpl-" + rid,
      object: "chat.completion.chunk",
      created: 1,
      model: "model-a",
      choices: [
        {
          index: 0,
          delta: { content: text },
          finish_reason: finish ? "stop" : null,
        },
      ],
      ...(usage ? { usage } : {}),
    }) +
    "\n\n"
  );
}
for (const mode of ["known", "unknown", "eof", "error", "stop"]) {
  it(
    "single model " +
      mode +
      " projects original request without repeating generation",
    async () => {
      const page = structuredClone(lookupSample),
        calls: { path: string; method: string }[] = [];
      page.data[0]!.status =
        mode === "known" || mode === "unknown"
          ? "succeeded"
          : mode === "stop"
            ? "cancelled"
            : "interrupted";
      if (mode === "known")
        page.data[0]!.usage = known as (typeof page.data)[0]["usage"];
      api.fetcher = async (p, i) => {
        const path = String(p);
        calls.push({ path, method: i?.method ?? "GET" });
        if (path.includes("request_id=")) return Response.json(page);
        if (path !== "/v1/chat/completions") return fixtureFetch(p, i);
        if (mode === "stop") {
          const stream = new ReadableStream<Uint8Array>({
            start(c) {
              c.enqueue(new TextEncoder().encode(frame("partial")));
              i?.signal?.addEventListener(
                "abort",
                () => c.error(new DOMException("Aborted", "AbortError")),
                { once: true },
              );
            },
          });
          return new Response(stream, {
            headers: {
              "Content-Type": "text/event-stream",
              "X-Request-ID": rid,
            },
          });
        }
        const error = await fixtureError("upstream_error").json();
        const ending =
          mode === "eof"
            ? ""
            : mode === "error"
              ? "event: error\ndata: " + JSON.stringify(error) + "\n\n"
              : frame(
                  "complete",
                  true,
                  mode === "known" ? known : page.data[0]!.usage,
                ) + "data: [DONE]\n\n";
        return new Response(frame("partial") + ending, {
          headers: { "Content-Type": "text/event-stream", "X-Request-ID": rid },
        });
      };
      const w = (wrapper = mount(Playground, {
        props: { initialModel: "model-a", inferenceAvailable: true },
      }));
      await flushPromises();
      await w.get('input[type="password"]').setValue("fixture-only-key");
      await w.get("textarea").setValue("replay single model");
      await w.get("form").trigger("submit");
      await flushPromises();
      if (mode === "stop") {
        await w
          .findAll("button")
          .find((b) => b.text() === "停止传输")!
          .trigger("click");
        await flushPromises();
      }
      const state = (w.vm as any).$.setupState;
      expect(state.lookup.lookup.request_id).toBe(rid);
      expect(state.lookup.data).toHaveLength(1);
      expect(state.state).toBe(
        mode === "known" || mode === "unknown"
          ? "completed"
          : mode === "stop"
            ? "stopped"
            : "interrupted",
      );
      expect(
        calls.filter((c) => c.path === "/v1/chat/completions"),
      ).toHaveLength(1);
      expect(calls.filter((c) => c.path.includes("request_id="))).toEqual([
        {
          path: "/api/admin/v1/usage/requests?request_id=" + rid,
          method: "GET",
        },
      ]);
      expect(state.lookup.data[0].usage.total_tokens).toBe(
        mode === "known" ? 19 : null,
      );
      expect(state.lookup.data[0].budget_accounting).toEqual(
        page.data[0]!.budget_accounting,
      ); // readonly authoritative projection, no client settlement
    },
  );
}
it("unavailable playground requests no catalogue or consumption Key and directs to Chat", async () => {
  const f = vi.fn(fixtureFetch);
  api.fetcher = f;
  const w = (wrapper = mount(Playground, {
    props: { initialModel: "model-a", inferenceAvailable: false },
  }));
  await flushPromises();
  expect(w.find('input[type="password"]').exists()).toBe(false);
  expect(w.find("textarea").exists()).toBe(false);
  expect(f).not.toHaveBeenCalled();
  await w
    .findAll("button")
    .find((b) => b.text() === "前往 Chat 工作台")!
    .trigger("click");
  expect(w.emitted("navigate")).toEqual([["chat"]]);
});
