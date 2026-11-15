import { afterEach, expect, it, vi } from "vitest";
import { mount, flushPromises } from "@vue/test-utils";
import Releases from "./pages/Releases.vue";
import { api } from "./api/client";
import { fixtureFetch, releaseSample, resetFixtures } from "./fixtures";
import type { S } from "./api/contracts";
const original = api.fetcher;
const mounted: ReturnType<typeof mount>[] = [];
afterEach(() => {
  mounted.splice(0).forEach((w) => w.unmount());
  api.fetcher = original;
  vi.restoreAllMocks();
  resetFixtures();
});
const state = (w: ReturnType<typeof mount>) => (w.vm as any).$.setupState;
const button = (w: ReturnType<typeof mount>, name: string) =>
  w.findAll("button").find((b) => b.text() === name)!;
async function open() {
  const w = mount(Releases);
  mounted.push(w);
  await flushPromises();
  await w.find(".release-card").trigger("click");
  await flushPromises();
  return w;
}
for (const [before, after, action] of [
  ["Published", "Published", "Update"],
  ["Published", "Paused", "Pause"],
  ["Paused", "Published", "Resume"],
  ["Paused", "Paused", "Update"],
] as const)
  it(`JSON save ${before} to ${after} associates ${action}`, async () => {
    const current = structuredClone(releaseSample);
    current.spec.lifecycle.desiredState = before;
    api.fetcher = async (p, i) => {
      const r = await fixtureFetch(p, i);
      if (String(p).endsWith(current.metadata.name) && !i?.method)
        return Response.json(current);
      if (i?.method === "PUT") {
        const ack = await r.json();
        ack.operation.action = action;
        ack.resource.spec.lifecycle.desiredState = after;
        return Response.json(ack, { status: 202 });
      }
      return r;
    };
    const w = await open();
    await button(w, "编辑配置").trigger("click");
    const input = JSON.parse(state(w).editor);
    input.spec.lifecycle.desiredState = after;
    await w.find("textarea").setValue(JSON.stringify(input));
    await w.find("form").trigger("submit");
    await flushPromises();
    expect(state(w).unknown).toBe(false);
    expect(state(w).operation.action).toBe(action);
  });
it("Update ACK cannot acknowledge a real Pause transition", async () => {
  api.fetcher = async (p, i) => {
    const r = await fixtureFetch(p, i);
    if (i?.method === "PUT") {
      const ack = await r.json();
      ack.operation.action = "Update";
      return Response.json(ack, { status: 202 });
    }
    return r;
  };
  const w = await open();
  await button(w, "暂停发布").trigger("click");
  await flushPromises();
  expect(state(w).unknown).toBe(true);
  expect(state(w).operation).toBeNull();
});
for (const action of ["Rollback", "Delete"] as const)
  it(`${action} with null resource retains exact original operation`, async () => {
    let op: S["ReleaseOperation"] | undefined;
    let writes = 0;
    api.fetcher = async (p, i) => {
      if (String(p).includes("/release-operations/")) return Response.json(op);
      const r = await fixtureFetch(p, i);
      if (
        (i?.method === "POST" && String(p).endsWith("/rollback")) ||
        i?.method === "DELETE"
      ) {
        writes++;
        const ack = await r.json();
        op = ack.operation;
        ack.resource = null;
        return Response.json(ack, { status: 202 });
      }
      return r;
    };
    const w = await open();
    if (action === "Rollback") {
      await button(w, "读取保留修订").trigger("click");
      await flushPromises();
      await button(w, "回滚到此修订").trigger("click");
    } else {
      await button(w, "下线并清理").trigger("click");
      await button(w, "确认下线").trigger("click");
    }
    await flushPromises();
    const id = state(w).operation.id;
    expect(state(w).unknown).toBe(false);
    expect(state(w).needsRead).toBe(true);
    await button(w, "查询原操作").trigger("click");
    await flushPromises();
    expect(state(w).operation.id).toBe(id);
    expect(writes).toBe(1);
  });
for (const withResource of [false, true])
  it(`Unknown ACK locks replay even with resource=${withResource}`, async () => {
    let op: S["ReleaseOperation"];
    let writes = 0;
    api.fetcher = async (p, i) => {
      if (String(p).includes("/release-operations/")) return Response.json(op!);
      const r = await fixtureFetch(p, i);
      if (i?.method === "PUT") {
        writes++;
        const ack = await r.json();
        ack.operation.state = "Unknown";
        op = ack.operation;
        if (!withResource) ack.resource = null;
        else ack.resource.spec.modelAlias = "unconfirmed";
        return Response.json(ack, { status: 202 });
      }
      return r;
    };
    const w = await open();
    await button(w, "暂停发布").trigger("click");
    await flushPromises();
    expect(state(w).unknown).toBe(true);
    expect(state(w).selected.spec.modelAlias).toBe(
      releaseSample.spec.modelAlias,
    );
    const id = state(w).operation.id;
    await state(w).mutate("pause");
    await button(w, "查询原操作").trigger("click");
    await flushPromises();
    expect(state(w).unknown).toBe(true);
    expect(state(w).operation.id).toBe(id);
    expect(writes).toBe(1);
  });
