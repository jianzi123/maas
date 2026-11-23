import { afterEach, expect, it } from "vitest";
import { flushPromises, mount } from "@vue/test-utils";
import Usage from "./pages/Usage.vue";
import { api } from "./api/client";
import { fixtureError, fixtureFetch, resetFixtures, rid } from "./fixtures";
const original = api.fetcher,
  mounted: ReturnType<typeof mount>[] = [];
afterEach(() => {
  mounted.splice(0).forEach((w) => w.unmount());
  api.fetcher = original;
  resetFixtures();
});
const button = (w: ReturnType<typeof mount>, name: string) =>
  w.findAll("button").find((b) => b.text() === name)!;
const idB = "00000000-0000-4000-8000-000000000022";
function deferred() {
  let resolve!: (r: Response) => void;
  const promise = new Promise<Response>((r) => (resolve = r));
  return { promise, resolve };
}
for (const success of [true, false])
  for (const invalidation of ["refresh", "list-query", "view-change"]) {
    it(`UI16-U2 ${invalidation}, late A ${success ? "success" : "503"} cannot replace B or clear B busy`, async () => {
      const a = deferred(),
        b = deferred(),
        calls: { path: string; method: string }[] = [];
      api.fetcher = async (p, i) => {
        const path = String(p);
        calls.push({ path, method: i?.method ?? "GET" });
        if (path.includes("request_id="))
          return path.endsWith(rid) ? a.promise : b.promise;
        return fixtureFetch(p, i);
      };
      const w = mount(Usage);
      mounted.push(w);
      await flushPromises();
      await w.get('input[placeholder="可信的原 request_id"]').setValue(rid);
      await button(w, "精确回查").trigger("click");
      await flushPromises();
      expect(button(w, "回查中…").attributes("disabled")).toBeDefined();
      if (invalidation === "refresh")
        await button(w, "刷新数据").trigger("click");
      else if (invalidation === "list-query")
        await w.get("form").trigger("submit");
      else await w.get('[role="tab"][aria-selected="false"]').trigger("click");
      await flushPromises();
      expect(button(w, "精确回查").attributes("disabled")).toBeUndefined();
      await w.get('input[placeholder="可信的原 request_id"]').setValue(idB);
      await button(w, "精确回查").trigger("click");
      await flushPromises();
      expect(
        calls
          .filter((c) => c.path.includes("request_id="))
          .map((c) =>
            new URL(c.path, "https://test.invalid").searchParams.get(
              "request_id",
            ),
          ),
      ).toEqual([rid, idB]);
      a.resolve(
        success
          ? await fixtureFetch("/api/admin/v1/usage/requests?request_id=" + rid)
          : fixtureError("dependency_unavailable", 503),
      );
      await flushPromises();
      const state = (w.vm as any).$.setupState;
      expect(state.exactBusy).toBe(true);
      expect(state.exact).toBeNull();
      expect(state.detail).toBeNull();
      expect(state.error).toBe("");
      expect(button(w, "回查中…").attributes("disabled")).toBeDefined();
      b.resolve(
        await fixtureFetch("/api/admin/v1/usage/requests?request_id=" + idB),
      );
      await flushPromises();
      expect(state.exact.lookup.request_id).toBe(idB);
      expect(state.detail.request_id).toBe(idB);
      expect(state.exactBusy).toBe(false);
      expect(button(w, "精确回查").attributes("disabled")).toBeUndefined();
      expect(calls.every((c) => c.method === "GET")).toBe(true);
      expect(calls.filter((c) => c.path.includes("request_id="))).toHaveLength(
        2,
      );
    });
  }
