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
  expect(w.text()).toContain("会话服务未启用");
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

it("late list completion for A cannot abort the active event stream for B", async () => {
  const makeSession = (id: string) => ({
    id,
    title: id,
    updatedAt: "2026-11-19T00:00:00Z",
    messages: [],
    runs: [
      {
        id: id + "-run",
        commandId: id + "-command",
        model: "dev",
        mode: "chat" as const,
        state: "running" as const,
        assistantId: id + "-assistant",
        cursor: 0,
        steps: [],
        usage: { tokens: null, reason: null },
      },
    ],
  });
  const a = makeSession("A"),
    b = makeSession("B");
  let releaseList!: (value: (typeof a)[]) => void;
  const lateList = new Promise<(typeof a)[]>((resolve) => {
    releaseList = resolve;
  });
  let releaseB!: (value: { events: []; snapshot: typeof b }) => void;
  const activeB = new Promise<{ events: []; snapshot: typeof b }>((resolve) => {
    releaseB = resolve;
  });
  let listCalls = 0;
  const stopEvents = vi.fn();
  const service = {
    models: async () => [{ id: "dev", label: "dev", modes: ["chat" as const] }],
    list: async () => (++listCalls === 2 ? lateList : [a, b]),
    read: async (id: string) => (id === "A" ? a : b),
    events: async (id: string) =>
      id === "A" ? { events: [], snapshot: a } : activeB,
    stopEvents,
    create: async () => a,
    start: async () => a.runs[0]!,
    rename: async () => {},
    remove: async () => {},
    cancel: async () => {},
    approve: async () => {},
    clear: async () => {},
  };
  w = mount(ChatWorkspace, { props: { service } });
  await flushPromises();
  await w.findAll(".chat-session")[0]!.trigger("click");
  await flushPromises();
  expect(listCalls).toBe(2);
  await w.findAll(".chat-session")[1]!.trigger("click");
  await flushPromises();
  const before = stopEvents.mock.calls.length;
  releaseList([a, b]);
  await flushPromises();
  expect(w.get("h1").text()).toBe("B");
  expect(stopEvents.mock.calls.length).toBe(before);
  w.unmount();
  w = undefined;
  releaseB({ events: [], snapshot: b });
  await flushPromises();
});

it("a text-only model explains unsupported Agent mode and cannot dispatch", async () => {
  class TextOnly extends DevelopmentChat {
    override async models() {
      return [{ id: "dev-text", label: "仅文本", modes: ["chat" as const] }];
    }
  }
  const service = new TextOnly(),
    start = vi.spyOn(service, "start");
  w = mount(ChatWorkspace, { props: { service } });
  await flushPromises();
  await w
    .findAll("button")
    .find((b) => b.text() === "＋ 新建会话")!
    .trigger("click");
  await flushPromises();
  await w.get("textarea").setValue("不能作为工具请求发送");
  await w.findAll("select")[0]!.setValue("agent");
  expect(w.text()).toContain("没有支持所选模式的获准模型");
  const send = w.get("form.chat-composer button.primary");
  expect(send.attributes("disabled")).toBeDefined();
  await w.get("form.chat-composer").trigger("submit");
  expect(start).not.toHaveBeenCalled();
});

it("bounded snapshot recovery exposes a read-only reconnect without regenerating", async () => {
  const service = new DevelopmentChat();
  const start = vi.spyOn(service, "start");
  const read = vi.spyOn(service, "read");
  w = mount(ChatWorkspace, { props: { service } });
  await flushPromises();
  await w
    .findAll("button")
    .find((b) => b.text() === "＋ 新建会话")!
    .trigger("click");
  await flushPromises();
  read.mockRejectedValueOnce(
    Error("会话持续变化，已停止自动恢复。请稍后只读重连。"),
  );
  await w.get("textarea").setValue("同一条生成");
  await w.get("form.chat-composer").trigger("submit");
  await flushPromises();
  expect(start).toHaveBeenCalledTimes(1);
  expect(w.text()).toContain("已停止自动恢复");
  await w
    .findAll("button")
    .find((b) => b.text() === "只读重连")!
    .trigger("click");
  await flushPromises();
  expect(start).toHaveBeenCalledTimes(1);
  expect(w.findAll("button").some((b) => b.text() === "只读重连")).toBe(false);
  expect(w.text()).not.toContain("已停止自动恢复");
});

it("failed first read reconnects its target rather than the previously selected session", async () => {
  const service = new DevelopmentChat();
  const a = await service.create(),
    b = await service.create();
  const read = vi.spyOn(service, "read");
  const start = vi.spyOn(service, "start");
  w = mount(ChatWorkspace, { props: { service } });
  await flushPromises();
  read.mockRejectedValueOnce(Error("会话持续变化"));
  const rows = w.findAll(".chat-session");
  await rows[1]!.trigger("click");
  await flushPromises();
  const target = read.mock.calls.at(-1)![0];
  expect([a.id, b.id]).toContain(target);
  await w
    .findAll("button")
    .find((x) => x.text() === "只读重连")!
    .trigger("click");
  await flushPromises();
  expect(read.mock.calls.at(-1)![0]).toBe(target);
  expect(w.findAll("button").some((x) => x.text() === "只读重连")).toBe(false);
  expect(start).not.toHaveBeenCalled();
});
