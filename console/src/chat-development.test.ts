import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { DevelopmentChat } from "./chat/development";
import { renderMarkdown } from "./chat/render";
import type { StartInput } from "./chat/types";
const start = (
  sessionId: string,
  extra: Partial<StartInput> = {},
): StartInput => ({
  sessionId,
  commandId: crypto.randomUUID(),
  content: "你好",
  model: "dev-text",
  mode: "chat",
  ...extra,
});
beforeEach(() => {
  localStorage.clear();
  vi.useFakeTimers();
  vi.setSystemTime(new Date("2026-11-19T00:00:00Z"));
});
afterEach(() => {
  vi.useRealTimers();
  localStorage.clear();
});
it("persists multi-turn history, rename, edit lineage and deletes without credentials", async () => {
  const api = new DevelopmentChat(),
    s = await api.create();
  await api.rename(s.id, "持久会话");
  const a = await api.start(start(s.id));
  vi.advanceTimersByTime(10000);
  const page = await api.events(s.id, a.id, 0);
  expect(page.snapshot.runs[0]!.state).toBe("completed");
  const original = page.snapshot.messages[0]!;
  const b = await api.start(
    start(s.id, { content: "修改", replaces: original.id }),
  );
  vi.advanceTimersByTime(10000);
  await api.events(s.id, b.id, 0);
  const restored = await new DevelopmentChat().read(s.id);
  expect(restored.title).toBe("持久会话");
  expect(restored.messages).toHaveLength(4);
  expect(restored.messages[2]!.replaces).toBe(original.id);
  expect(restored.messages[0]!.content).toBe("你好");
  expect(restored.messages[3]!.content).toContain("第 **2**");
  expect(restored.runs[1]!.usage.tokens).toBeNull();
  await api.remove(s.id);
  expect(await api.list()).toEqual([]);
});
it("same command ID is idempotent, concurrent sends refused, replay never duplicates deltas", async () => {
  const api = new DevelopmentChat(),
    s = await api.create(),
    input = start(s.id);
  const a = await api.start(input);
  expect((await api.start(input)).id).toBe(a.id);
  await expect(api.start(start(s.id))).rejects.toThrow("已有运行");
  vi.advanceTimersByTime(10000);
  const first = await api.events(s.id, a.id, 0),
    again = await api.events(s.id, a.id, 0);
  expect(again.snapshot.messages).toEqual(first.snapshot.messages);
  expect(
    (await api.events(s.id, a.id, first.snapshot.runs[0]!.cursor)).events,
  ).toHaveLength(0);
});
it("read-only reconnect after a new adapter restores running stream without starting again", async () => {
  const api = new DevelopmentChat(),
    s = await api.create(),
    r = await api.start(start(s.id));
  vi.advanceTimersByTime(200);
  const part = await api.events(s.id, r.id, 0);
  const cursor = part.snapshot.runs[0]!.cursor;
  vi.advanceTimersByTime(10000);
  const restored = await new DevelopmentChat().events(s.id, r.id, cursor);
  expect(restored.snapshot.runs).toHaveLength(1);
  expect(restored.snapshot.messages).toHaveLength(2);
  expect(restored.events.every((e) => e.seq > cursor)).toBe(true);
  expect(restored.snapshot.runs[0]!.state).toBe("completed");
});
it("cancel prevents future scheduled answer, including after refresh", async () => {
  const api = new DevelopmentChat(),
    s = await api.create(),
    r = await api.start(start(s.id));
  await api.events(s.id, r.id, 0);
  await expect(api.remove(s.id)).rejects.toThrow("停止");
  await api.cancel(s.id, r.id);
  vi.advanceTimersByTime(10000);
  const page = await new DevelopmentChat().events(s.id, r.id, 0);
  expect(page.snapshot.runs[0]!.state).toBe("cancelled");
  expect(page.events.some((e) => e.type === "completed")).toBe(false);
});
it("Agent waits for exact tool approval, runs pure computation once and rejects reused approval", async () => {
  const api = new DevelopmentChat(),
    s = await api.create(),
    r = await api.start(start(s.id, { mode: "agent", content: "😀a" }));
  vi.advanceTimersByTime(1000);
  const waiting = await api.events(s.id, r.id, 0),
    step = waiting.snapshot.runs[0]!.steps.find((s) => s.callId)!;
  expect(waiting.snapshot.runs[0]!.state).toBe("waiting_approval");
  await expect(api.approve(s.id, r.id, "other", true)).rejects.toThrow("身份");
  await api.approve(s.id, r.id, step.callId!, true);
  vi.advanceTimersByTime(10000);
  const done = await api.events(s.id, r.id, 0);
  expect(done.snapshot.runs[0]!.steps.find((s) => s.callId)?.output).toBe(
    '{"characters":2}',
  );
  await expect(api.approve(s.id, r.id, step.callId!, true)).rejects.toThrow(
    "失效",
  );
});
it("upstream failure is visible, usage unknown and not automatically rerun", async () => {
  const api = new DevelopmentChat(),
    s = await api.create(),
    r = await api.start(start(s.id, { content: "/error" }));
  vi.advanceTimersByTime(1000);
  const page = await api.events(s.id, r.id, 0);
  expect(page.snapshot.runs).toHaveLength(1);
  expect(page.snapshot.runs[0]!.state).toBe("failed");
  expect(page.snapshot.runs[0]!.error).toContain("未自动");
  expect(page.snapshot.runs[0]!.usage.tokens).toBeNull();
});
it("renders Markdown and code while stripping tool-output HTML attacks", () => {
  const html = renderMarkdown(
    '**重点**\n\n```js\nalert(1)\n```\n\n<script>alert(1)</script><img src=x onerror=alert(1)><a href="javascript:alert(1)">bad</a>',
  );
  expect(html).toContain("<strong>重点</strong>");
  expect(html).toContain("<code");
  expect(html).not.toMatch(/<script|<img|onerror|href="javascript:/i);
});
