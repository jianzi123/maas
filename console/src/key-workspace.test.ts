import { it, expect, afterEach, vi } from "vitest";
import { mount, flushPromises } from "@vue/test-utils";
import { api } from "./api/client";
import {
  fixtureFetch,
  keySample,
  resetFixtures,
  releaseSample,
} from "./fixtures";
import Keys from "./pages/Keys.vue";
import Releases from "./pages/Releases.vue";
let current: ReturnType<typeof mount> | undefined;
const original = api.fetcher;
afterEach(() => {
  current?.unmount();
  api.fetcher = original;
  resetFixtures();
  vi.restoreAllMocks();
});
it("Key inventory searches metadata and links usage with ID only", async () => {
  api.fetcher = fixtureFetch;
  const w = (current = mount(Keys));
  await flushPromises();
  expect(w.find("form").exists()).toBe(false);
  await w.find("input[type=search]").setValue("missing");
  expect(w.text()).toContain("没有匹配的 Key");
  await w.find("input[type=search]").setValue("");
  await w
    .findAll("button")
    .find((b) => b.text() === "查看用量")!
    .trigger("click");
  expect(w.emitted("navigate")).toEqual([["usage", { key_id: keySample.id }]]);
});
it("cancelled create dialog clears draft and keeps explicit budget period unselected", async () => {
  api.fetcher = fixtureFetch;
  const w = (current = mount(Keys));
  await flushPromises();
  await w.get("[data-testid=create-key]").trigger("click");
  await w.get("form input").setValue("discard me");
  await w
    .findAll("button")
    .find((b) => b.text() === "取消编辑")!
    .trigger("click");
  expect(w.find("form").exists()).toBe(false);
  await w.get("[data-testid=create-key]").trigger("click");
  expect((w.get("form input").element as HTMLInputElement).value).toBe("");
  expect((w.get("form select").element as HTMLSelectElement).value).toBe("");
});
const button = (w: ReturnType<typeof mount>, name: string) =>
  w.findAll("button").find((b) => b.text() === name)!;
it("JSON edit derives Pause then Resume from the desired state rather than assuming Update", async () => {
  api.fetcher = fixtureFetch;
  const w = (current = mount(Releases));
  await flushPromises();
  await w.get(".release-card").trigger("click");
  await flushPromises();
  for (const [desired, expected] of [
    ["Paused", "Pause"],
    ["Published", "Resume"],
  ]) {
    await button(w, "编辑配置").trigger("click");
    const input = JSON.parse(
      (w.get("textarea").element as HTMLTextAreaElement).value,
    );
    input.spec.lifecycle.desiredState = desired;
    await w.get("textarea").setValue(JSON.stringify(input));
    await w.get("form").trigger("submit");
    await flushPromises();
    expect((w.vm as any).$.setupState.operation.action).toBe(expected);
    expect((w.vm as any).$.setupState.unknown).toBe(false);
  }
});
it("schema-valid Update ACK cannot acknowledge a Pause intent", async () => {
  api.fetcher = async (p, i) => {
    const r = await fixtureFetch(p, i);
    if (i?.method === "PUT") {
      const body = await r.json();
      body.operation.action = "Update";
      return Response.json(body, { status: 202 });
    }
    return r;
  };
  const w = (current = mount(Releases));
  await flushPromises();
  await w.get(".release-card").trigger("click");
  await flushPromises();
  await button(w, "暂停发布").trigger("click");
  await flushPromises();
  expect((w.vm as any).$.setupState.unknown).toBe(true);
  expect((w.vm as any).$.setupState.selected.metadata.uid).toBe(
    releaseSample.metadata.uid,
  );
  expect(w.text()).toContain("结果未知");
});
