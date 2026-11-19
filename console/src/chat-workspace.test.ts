import { afterEach, it, expect, vi } from "vitest";
import { mount, flushPromises } from "@vue/test-utils";
import ChatWorkspace from "./pages/ChatWorkspace.vue";
import { DevelopmentChat } from "./chat/development";
import type { StartInput } from "./chat/types";
let w: ReturnType<typeof mount> | undefined;
afterEach(() => {
  w?.unmount();
  localStorage.clear();
  location.hash = "";
  vi.restoreAllMocks();
});
it("without a service it cannot create or generate, and makes no network request", async () => {
  const fetcher = vi.spyOn(globalThis, "fetch");
  w = mount(ChatWorkspace);
  await flushPromises();
  expect(w.text()).toContain("共享契约尚待");
  expect(
    w
      .findAll("button")
      .find((b) => b.text() === "＋ 新建会话")!
      .attributes("disabled"),
  ).toBeDefined();
  expect(fetcher).not.toHaveBeenCalled();
});
it("unknown submit ACK locks replay and recovers only the original command", async () => {
  class LostACK extends DevelopmentChat {
    calls = 0;
    override async start(i: StartInput): Promise<never> {
      this.calls++;
      await super.start(i);
      throw Error("模拟ACK丢失");
    }
  }
  const service = new LostACK();
  w = mount(ChatWorkspace, { props: { service } });
  await flushPromises();
  await w
    .findAll("button")
    .find((b) => b.text() === "＋ 新建会话")!
    .trigger("click");
  await flushPromises();
  await w.get("textarea").setValue("test");
  await w.get("form.chat-composer").trigger("submit");
  await flushPromises();
  expect(w.text()).toContain("提交结果未知");
  await w.get("form.chat-composer").trigger("submit");
  expect(service.calls).toBe(1);
  await w
    .findAll("button")
    .find((b) => b.text() === "核对原会话")!
    .trigger("click");
  await flushPromises();
  expect(service.calls).toBe(1);
  expect((await service.list())[0]!.runs).toHaveLength(1);
  expect((w.vm as any).$.setupState.uncertain).toBe(false);
});
it("denied approval cannot be accepted again before event replay", async () => {
  const service = new DevelopmentChat(),
    s = await service.create(),
    r = await service.start({
      sessionId: s.id,
      commandId: crypto.randomUUID(),
      content: "test",
      model: "dev-text",
      mode: "agent",
    });
  vi.spyOn(Date, "now").mockReturnValue(Date.now() + 10000);
  const page = await service.events(s.id, r.id, 0),
    call = page.snapshot.runs[0]!.steps.find((s) => s.callId)!.callId!;
  await service.approve(s.id, r.id, call, false);
  await expect(service.approve(s.id, r.id, call, true)).rejects.toThrow("失效");
});
