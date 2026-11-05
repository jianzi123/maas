import { afterEach, expect, it, vi } from "vitest";
import { flushPromises, mount } from "@vue/test-utils";
import { api } from "./api/client";
import { assertReleaseAccepted } from "./api/recovery";
import { validate, type S } from "./api/contracts";
import {
  fixtureFetch,
  lookupSample,
  releaseSample,
  resetFixtures,
  rid,
} from "./fixtures";
import Playground from "./pages/Playground.vue";
import Releases from "./pages/Releases.vue";

const other = "00000000-0000-4000-8000-000000000022";
const mounted: ReturnType<typeof mount>[] = [];
const original = api.fetcher;
afterEach(() => {
  mounted.splice(0).forEach((w) => w.unmount());
  api.fetcher = original;
  vi.restoreAllMocks();
  resetFixtures();
});
const state = (w: ReturnType<typeof mount>) => (w.vm as any).$.setupState;
const button = (w: ReturnType<typeof mount>, text: string) =>
  w.findAll("button").find((b) => b.text() === text)!;
function deferred<T>() {
  let resolve!: (v: T) => void, reject!: (e: Error) => void;
  const promise = new Promise<T>((a, b) => {
    resolve = a;
    reject = b;
  });
  return { promise, resolve, reject };
}
function stream(id: string) {
  return new Response(
    `data: ${JSON.stringify({ id: "chatcmpl-" + id, object: "chat.completion.chunk", created: 1, model: "model-a", choices: [{ index: 0, delta: {}, finish_reason: "stop" }] })}\n\ndata: [DONE]\n\n`,
    { headers: { "Content-Type": "text/event-stream", "X-Request-ID": id } },
  );
}
async function playground() {
  const w = mount(Playground);
  mounted.push(w);
  await flushPromises();
  await w.find("select").setValue("model-a");
  await w.find("textarea").setValue("synthetic");
  return w;
}
async function release() {
  const w = mount(Releases);
  mounted.push(w);
  await flushPromises();
  await w.find(".release-card").trigger("click");
  await flushPromises();
  return w;
}
for (const outcome of ["result", "error"] as const)
  it(`late A ${outcome} and finally leave B lookup/loading intact`, async () => {
    const a = deferred<Response>(),
      b = deferred<Response>();
    let posts = 0,
      reads = 0;
    api.fetcher = async (p, i) => {
      if (String(p) === "/v1/chat/completions")
        return stream(++posts === 1 ? rid : other);
      if (String(p).includes("request_id=")) {
        reads++;
        return String(p).endsWith(rid) ? a.promise : b.promise;
      }
      return fixtureFetch(p, i);
    };
    const w = await playground();
    await w.find("form").trigger("submit");
    await flushPromises();
    await w.find("form").trigger("submit");
    await flushPromises();
    expect(reads).toBe(2);
    expect(state(w).looking).toBe(true);
    if (outcome === "error") a.reject(new Error("old failed"));
    else a.resolve(Response.json(lookupSample));
    await flushPromises();
    expect(state(w).lookup).toBeNull();
    expect(state(w).message).toBe("");
    expect(state(w).looking).toBe(true);
    const page = structuredClone(lookupSample);
    page.lookup.request_id = other;
    page.data.forEach((x) => (x.request_id = other));
    b.resolve(Response.json(page));
    await flushPromises();
    expect(state(w).lookup.lookup.request_id).toBe(other);
    expect(state(w).looking).toBe(false);
  });
it("rollback followed by edit/save uses acknowledged spec and original edit version", async () => {
  const submitted: RequestInit[] = [];
  api.fetcher = async (p, i) => {
    const response = await fixtureFetch(p, i);
    if (i?.method === "POST" && String(p).endsWith("/rollback")) {
      const ack = await response.json();
      ack.resource.spec.source.externalAPI.upstreamModel =
        "acknowledged-rollback-model";
      ack.resource.metadata.resourceVersion = "421";
      return Response.json(ack, { status: 202 });
    }
    if (i?.method === "PUT") submitted.push(i);
    return response;
  };
  const w = await release();
  await button(w, "编辑配置").trigger("click");
  await w.find("textarea").setValue(
    JSON.stringify({
      ...JSON.parse(state(w).editor),
      spec: { ...releaseSample.spec, modelAlias: "discard-old-draft" },
    }),
  );
  await button(w, "读取保留修订").trigger("click");
  await flushPromises();
  await button(w, "回滚到此修订").trigger("click");
  await flushPromises();
  await button(w, "编辑配置").trigger("click");
  await w.find("form").trigger("submit");
  await flushPromises();
  expect(submitted).toHaveLength(1);
  expect(new Headers(submitted[0].headers).get("If-Match")).toBe('"421"');
  const input = JSON.parse(String(submitted[0].body));
  expect(input.spec.source.externalAPI.upstreamModel).toBe(
    "acknowledged-rollback-model",
  );
  expect(input.spec.modelAlias).toBe(releaseSample.spec.modelAlias);
});
it("stale editor baseline cannot be rebased onto a newer selected resource", async () => {
  api.fetcher = vi.fn(fixtureFetch);
  const w = await release();
  await button(w, "编辑配置").trigger("click");
  state(w).selected = {
    ...state(w).selected,
    metadata: { ...state(w).selected.metadata, resourceVersion: "999" },
  };
  await w.find("form").trigger("submit");
  await flushPromises();
  expect(w.text()).toContain("编辑基线已变化");
  expect(
    vi.mocked(api.fetcher).mock.calls.filter(([, i]) => i?.method === "PUT"),
  ).toHaveLength(0);
});
for (const outcome of ["error", "result"] as const)
  it(`late operation ${outcome}/finally cannot alter a newer pending lookup`, async () => {
    const a = deferred<Response>(),
      b = deferred<Response>();
    let first: S["ReleaseOperation"],
      second: S["ReleaseOperation"],
      puts = 0,
      reads = 0;
    api.fetcher = async (p, i) => {
      if (String(p).includes("/release-operations/"))
        return ++reads === 1 ? a.promise : b.promise;
      const r = await fixtureFetch(p, i);
      if (i?.method === "PUT") {
        const ack = await r.json();
        ack.operation.id = ++puts === 1 ? rid : other;
        ack.resource.spec.lifecycle.desiredState = JSON.parse(
          String(i.body),
        ).spec.lifecycle.desiredState;
        if (puts === 1) first = ack.operation;
        else second = ack.operation;
        return Response.json(ack, { status: 202 });
      }
      return r;
    };
    const w = await release();
    await button(w, "暂停发布").trigger("click");
    await flushPromises();
    await button(w, "查询原操作").trigger("click");
    await flushPromises();
    await button(w, "恢复发布").trigger("click");
    await flushPromises();
    await button(w, "查询原操作").trigger("click");
    await flushPromises();
    const message = state(w).message;
    if (outcome === "error") a.reject(new Error("old failed"));
    else a.resolve(Response.json(first!));
    await flushPromises();
    expect(state(w).operation.id).toBe(other);
    expect(state(w).message).toBe(message);
    expect(state(w).operationReading).toBe(true);
    b.resolve(Response.json(second!));
    await flushPromises();
    expect(state(w).operationReading).toBe(false);
  });
for (const mismatch of [
  "uid",
  "action",
  "namespace",
  "generation",
  "resource-uid",
] as const)
  it(`schema-valid ${mismatch} ACK stays uncertain and never replays`, async () => {
    const f = vi.fn<typeof fetch>(async (p, i) => {
      const r = await fixtureFetch(p, i);
      if (i?.method !== "PUT") return r;
      const ack = await r.json();
      if (mismatch === "uid") {
        ack.operation.cr_uid = other;
        ack.resource.metadata.uid = other;
      }
      if (mismatch === "action") ack.operation.action = "Delete";
      if (mismatch === "namespace") ack.operation.namespace = "other-ns";
      if (mismatch === "generation") ack.operation.requested_generation++;
      if (mismatch === "resource-uid") ack.resource.metadata.uid = other;
      validate("ReleaseAccepted", ack);
      return Response.json(ack, { status: 202 });
    });
    api.fetcher = f;
    const w = await release();
    await button(w, "暂停发布").trigger("click");
    await flushPromises();
    expect(state(w).unknown).toBe(true);
    expect(state(w).selected.metadata.uid).toBe(releaseSample.metadata.uid);
    expect(state(w).operation).toBeNull();
    await state(w).mutate("pause");
    expect(f.mock.calls.filter(([, i]) => i?.method === "PUT")).toHaveLength(1);
  });
it("create ACK must match the new input and its own resource UID", async () => {
  const accepted = await (
    await fixtureFetch("/api/admin/v1/model-releases", {
      method: "POST",
      body: "{}",
    })
  ).json();
  expect(() =>
    assertReleaseAccepted(accepted, {
      namespace: "different",
      name: accepted.operation.name,
      action: "Create",
    }),
  ).toThrow();
});
it("unmount invalidates a pending operation lookup", async () => {
  const pending = deferred<Response>();
  let op: S["ReleaseOperation"];
  api.fetcher = async (p, i) => {
    if (String(p).includes("/release-operations/")) return pending.promise;
    const r = await fixtureFetch(p, i);
    if (i?.method === "PUT") {
      const ack = await r.json();
      op = ack.operation;
      return Response.json(ack, { status: 202 });
    }
    return r;
  };
  const w = await release();
  await button(w, "暂停发布").trigger("click");
  await flushPromises();
  await button(w, "查询原操作").trigger("click");
  await flushPromises();
  const s = state(w),
    message = s.message;
  w.unmount();
  pending.resolve(Response.json({ ...op!, state: "Succeeded" }));
  await flushPromises();
  expect(s.operation.state).toBe("Accepted");
  expect(s.message).toBe(message);
});
it("an ACK without resource requires rereading before another edit/write", async () => {
  const f = vi.fn<typeof fetch>(async (p, i) => {
    const r = await fixtureFetch(p, i);
    if (i?.method === "PUT") {
      const ack = await r.json();
      ack.resource = null;
      return Response.json(ack, { status: 202 });
    }
    return r;
  });
  api.fetcher = f;
  const w = await release();
  await button(w, "暂停发布").trigger("click");
  await flushPromises();
  expect(state(w).needsRead).toBe(true);
  await button(w, "编辑配置").trigger("click");
  expect(state(w).editing).toBe(false);
  await state(w).mutate("pause");
  expect(f.mock.calls.filter(([, i]) => i?.method === "PUT")).toHaveLength(1);
});
