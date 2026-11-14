// MAAS-17 fixes: actual consumers/components with synthetic Response/jsdom.
import { afterEach, expect, it } from "vitest";
import { mount, flushPromises } from "@vue/test-utils";
import Releases from "./pages/Releases.vue";
import Usage from "./pages/Usage.vue";
import { api } from "./api/client";
import {
  fixtureFetch,
  fixtureError,
  resetFixtures,
  releaseSample,
} from "./fixtures";
const original = api.fetcher;
const mounted: ReturnType<typeof mount>[] = [];
afterEach(() => {
  mounted.splice(0).forEach((w) => w.unmount());
  api.fetcher = original;
  resetFixtures();
});
const state = (w: ReturnType<typeof mount>) => (w.vm as any).$.setupState;
const button = (w: ReturnType<typeof mount>, name: string) =>
  w.findAll("button").find((b) => b.text() === name)!;
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((r) => {
    resolve = r;
  });
  return { promise, resolve };
}
async function unknownOperation(
  outcome: string,
  reread?: () => Promise<Response>,
) {
  let op: any;
  let writes = 0;
  let resourceReads = 0;
  const queries: string[] = [];
  api.fetcher = async (p, i) => {
    if (String(p).includes("/release-operations/")) {
      queries.push(String(p));
      if (outcome === "404") return fixtureError("not_found", 404);
      if (outcome === "503") return fixtureError("dependency_unavailable", 503);
      const next = {
        ...op,
        state: ["Succeeded", "Failed", "Running", "Unknown"].includes(outcome)
          ? outcome
          : "Succeeded",
      };
      if (outcome === "wrong-id")
        next.id = "00000000-0000-4000-8000-000000000099";
      if (outcome === "wrong-uid")
        next.cr_uid = "00000000-0000-4000-8000-000000000099";
      if (outcome === "wrong-name") next.name = "unrelated-model";
      if (outcome === "wrong-namespace") next.namespace = "unrelated";
      if (outcome === "wrong-action") next.action = "Delete";
      return Response.json(next);
    }
    if (!i?.method && String(p).endsWith("/" + releaseSample.metadata.name)) {
      if (++resourceReads > 1 && reread) return reread();
    }
    const response = await fixtureFetch(p, i);
    if (i?.method === "PUT") {
      writes++;
      const ack = await response.json();
      ack.operation.state = "Unknown";
      ack.resource = null;
      op = structuredClone(ack.operation);
      return Response.json(ack, { status: 202 });
    }
    return response;
  };
  const w = mount(Releases);
  mounted.push(w);
  await flushPromises();
  await w.find(".release-card").trigger("click");
  await flushPromises();
  await button(w, "暂停发布").trigger("click");
  await flushPromises();
  expect(state(w).unknown).toBe(true);
  return { w, writes: () => writes, op: () => op, queries };
}
for (const outcome of ["Succeeded", "Failed"]) {
  it(`FE-O1: ${outcome} resolves only after rereading the original CR, without replay`, async () => {
    const pending = deferred<Response>();
    const { w, writes, queries, op } = await unknownOperation(
      outcome,
      () => pending.promise,
    );
    await button(w, "查询原操作").trigger("click");
    await flushPromises();
    expect(state(w).unknown).toBe(true);
    expect(state(w).needsRead).toBe(true);
    expect(w.text()).not.toContain("写入结果未知。");
    expect(button(w, "编辑配置").attributes("disabled")).toBeDefined();
    await state(w).mutate("pause");
    await button(w, "重读当前 CR").trigger("click");
    await flushPromises();
    expect(state(w).unknown).toBe(true);
    pending.resolve(Response.json(releaseSample));
    await flushPromises();
    expect(state(w).unknown).toBe(false);
    expect(state(w).needsRead).toBe(false);
    expect(w.text()).not.toContain("写入结果未知。");
    expect(button(w, "编辑配置").attributes("disabled")).toBeUndefined();
    expect(queries).toEqual(["/api/admin/v1/release-operations/" + op().id]);
    expect(writes()).toBe(1);
  });
}
for (const outcome of [
  "Unknown",
  "Running",
  "404",
  "503",
  "wrong-id",
  "wrong-uid",
  "wrong-name",
  "wrong-namespace",
  "wrong-action",
]) {
  it(`FE-O1: ${outcome} cannot unlock via a current CR or replay`, async () => {
    const { w, writes } = await unknownOperation(outcome);
    await button(w, "查询原操作").trigger("click");
    await flushPromises();
    await button(w, "重读当前 CR").trigger("click");
    await flushPromises();
    await state(w).mutate("resume");
    expect(state(w).unknown).toBe(true);
    expect(button(w, "新建外部 API CR").attributes("disabled")).toBeDefined();
    expect(writes()).toBe(1);
  });
}
for (const invalid of ["503", "replaced-uid", "missing-version"]) {
  it(`FE-O1: terminal operation plus ${invalid} CR read remains locked`, async () => {
    const { w, writes } = await unknownOperation("Succeeded", async () => {
      if (invalid === "503") return fixtureError("dependency_unavailable", 503);
      const r = structuredClone(releaseSample);
      if (invalid === "replaced-uid")
        r.metadata.uid = "00000000-0000-4000-8000-000000000099";
      else delete r.metadata.resourceVersion;
      return Response.json(r);
    });
    await button(w, "查询原操作").trigger("click");
    await flushPromises();
    await button(w, "重读当前 CR").trigger("click");
    await flushPromises();
    expect(state(w).unknown).toBe(true);
    expect(writes()).toBe(1);
  });
}
async function openUsage(kind: string) {
  const w = mount(Usage);
  mounted.push(w);
  await flushPromises();
  if (kind === "summary") {
    await w.find('select[aria-label="查询类型"]').setValue(kind);
    await flushPromises();
  }
  return w;
}
for (const kind of ["requests", "summary"]) {
  it(`FE-U1: ${kind} clears a failed filter and recovers without claiming zero or losing unknowns`, async () => {
    let failing = false;
    api.fetcher = async (p, i) => {
      if (failing) return fixtureError("dependency_unavailable", 503);
      const response = await fixtureFetch(p, i);
      const page = await response.json();
      if (String(p).includes("model_alias=model-b")) {
        page.data.forEach((row: any) => {
          row.model_alias = "model-b";
        });
      }
      return Response.json(page);
    };
    const w = await openUsage(kind);
    expect(w.findAll("article")).toHaveLength(1);
    failing = true;
    const alias = w
      .findAll("label")
      .find((l) => l.text() === "模型别名")!
      .find("input");
    await alias.setValue("model-b");
    await w.find("form").trigger("submit");
    await flushPromises();
    expect(w.findAll("article")).toHaveLength(0);
    expect(w.text()).not.toContain("本次查询数据完整");
    expect(w.find(".empty").exists()).toBe(false);
    expect(w.find('[role="alert"]').exists()).toBe(true);
    failing = false;
    await w.find("form").trigger("submit");
    await flushPromises();
    expect(w.find("article").text()).toContain("model-b");
    expect(w.text()).toContain("本次查询数据完整");
    if (kind === "requests") expect(w.text()).toContain("未知 / 不可获取");
    else expect(w.text()).toContain("140");
  });
  it(`FE-U1: ${kind} page failure discards completeness and cursor; next query restarts`, async () => {
    const queries: string[] = [];
    api.fetcher = async (p, i) => {
      queries.push(String(p));
      if (String(p).includes("cursor="))
        return fixtureError("dependency_unavailable", 503);
      const response = await fixtureFetch(p, i);
      const page = await response.json();
      page.next_cursor = "synthetic-page-2";
      return Response.json(page);
    };
    const w = await openUsage(kind);
    await button(w, "加载更多").trigger("click");
    await flushPromises();
    expect(w.findAll("article")).toHaveLength(0);
    expect(w.text()).not.toContain("本次查询数据完整");
    expect(w.text()).not.toContain("加载更多");
    await w.find("form").trigger("submit");
    await flushPromises();
    expect(queries.at(-1)).not.toContain("cursor=");
    expect(w.findAll("article")).toHaveLength(1);
  });
}
it("FE-U1: a late page cannot replace a newer successful filter", async () => {
  const pending = deferred<Response>();
  api.fetcher = async (p, i) => {
    if (String(p).includes("model_alias=old")) return pending.promise;
    const response = await fixtureFetch(p, i);
    const page = await response.json();
    if (String(p).includes("model_alias=new"))
      page.data.forEach((row: any) => {
        row.model_alias = "new";
      });
    return Response.json(page);
  };
  const w = await openUsage("requests");
  const alias = w
    .findAll("label")
    .find((l) => l.text() === "模型别名")!
    .find("input");
  await alias.setValue("old");
  await w.find("form").trigger("submit");
  await alias.setValue("new");
  await w.find("form").trigger("submit");
  await flushPromises();
  pending.resolve(fixtureError("dependency_unavailable", 503));
  await flushPromises();
  expect(w.find("article").text()).toContain("new");
  expect(w.find('[role="alert"]').exists()).toBe(false);
  expect(w.text()).toContain("本次查询数据完整");
});

for (const kind of ["content", "same-finish", "conflicting-finish"]) {
  it(`FE-S1: ${kind} after finish is rejected before content publication with original R retained`, async () => {
    const { Api } = await import("./api/client");
    const { streamChat } = await import("./api/stream");
    const { rid } = await import("./fixtures");
    const published: string[] = [],
      ids: string[] = [];
    let posts = 0;
    const chunk = (delta: object, reason: string | null) =>
      "data: " +
      JSON.stringify({
        id: "chatcmpl-" + rid,
        object: "chat.completion.chunk",
        created: 1,
        model: "model-a",
        choices: [{ index: 0, delta, finish_reason: reason }],
      }) +
      "\n\n";
    const suffix =
      kind === "content"
        ? chunk({ content: "ILLEGAL" }, null)
        : chunk({}, kind === "same-finish" ? "stop" : "length");
    const client = new Api(async () => {
      posts++;
      return new Response(chunk({}, "stop") + suffix + "data: [DONE]\n\n", {
        headers: { "Content-Type": "text/event-stream", "X-Request-ID": rid },
      });
    });
    await expect(
      streamChat(
        client,
        "synthetic",
        {
          model: "model-a",
          messages: [{ role: "user", content: "synthetic" }],
          stream: true,
        },
        new AbortController().signal,
        {
          id: (v) => ids.push(v),
          chunk: (v) => published.push(v),
          usage: () => {},
        },
      ),
    ).rejects.toMatchObject({ code: "protocol_error" });
    expect(published).toEqual([]);
    expect(ids).toEqual([rid]);
    expect(posts).toBe(1);
  });
}
