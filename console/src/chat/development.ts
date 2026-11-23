import type {
  ChatService,
  Session,
  Run,
  ChatEvent,
  StartInput,
  Step,
} from "./types";
const key = "maas.chat.development.v1";
const now = () => new Date().toISOString();
type RecordState = {
  sessions: Session[];
  events: Record<string, ChatEvent[]>;
  ready: Record<string, number>;
};
export class DevelopmentChat implements ChatService {
  constructor(private storage: Storage = localStorage) {}
  async models() {
    return [
      {
        id: "dev-text",
        label: "开发文本模型（非真实调用）",
        modes: ["chat", "agent"] as const,
      },
    ].map((m) => ({ ...m, modes: [...m.modes] }));
  }
  private load(): RecordState {
    const raw = this.storage.getItem(key);
    if (!raw) return { sessions: [], events: {}, ready: {} };
    const value = JSON.parse(raw);
    if (!Array.isArray(value.sessions) || !value.events || !value.ready)
      throw Error("开发会话存储损坏，请清空开发数据。");
    return value;
  }
  private save(d: RecordState) {
    this.storage.setItem(key, JSON.stringify(d));
  }
  private session(d: RecordState, id: string) {
    const s = d.sessions.find((x) => x.id === id);
    if (!s) throw Error("会话不存在或已删除。");
    return s;
  }
  async list() {
    return structuredClone(this.load().sessions).sort((a, b) =>
      b.updatedAt.localeCompare(a.updatedAt),
    );
  }
  async create() {
    const d = this.load();
    const s: Session = {
      id: crypto.randomUUID(),
      title: "新会话",
      updatedAt: now(),
      messages: [],
      runs: [],
    };
    d.sessions.push(s);
    this.save(d);
    return structuredClone(s);
  }
  async rename(id: string, title: string) {
    if (!title.trim() || title.length > 80) throw Error("会话名称需为1–80字。");
    const d = this.load();
    this.session(d, id).title = title.trim();
    this.save(d);
  }
  async remove(id: string) {
    const d = this.load(),
      s = this.session(d, id);
    if (s.runs.some((r) => ["running", "waiting_approval"].includes(r.state)))
      throw Error("请先停止运行，再删除会话。");
    for (const r of s.runs) {
      delete d.events[r.id];
      delete d.ready[r.id];
    }
    d.sessions = d.sessions.filter((s) => s.id !== id);
    this.save(d);
  }
  async clear() {
    this.storage.removeItem(key);
  }
  async read(id: string) {
    return structuredClone(this.session(this.load(), id));
  }
  private append(
    d: RecordState,
    run: Run,
    type: ChatEvent["type"],
    fields: Partial<ChatEvent> = {},
  ) {
    const events = (d.events[run.id] ??= []);
    const e = { ...fields, seq: events.length + 1, runId: run.id, type };
    events.push(e);
    return e;
  }
  async start(i: StartInput) {
    if (!i.content.trim() || i.content.length > 8192 || !i.model)
      throw Error("请选择模型并输入消息（最多8192字）。");
    const d = this.load(),
      s = this.session(d, i.sessionId);
    const duplicate = s.runs.find((r) => r.commandId === i.commandId);
    if (duplicate) return structuredClone(duplicate);
    if (s.runs.some((r) => ["running", "waiting_approval"].includes(r.state)))
      throw Error("当前会话已有运行，请停止或等待完成。");
    if (i.replaces && !s.messages.some((m) => m.id === i.replaces))
      throw Error("原消息不存在。");
    const assistantId = crypto.randomUUID(),
      run: Run = {
        id: crypto.randomUUID(),
        commandId: i.commandId,
        mode: i.mode,
        model: i.model,
        state: "running",
        assistantId,
        cursor: 0,
        steps: [],
        usage: { tokens: null, reason: "开发模型未提供计量" },
      };
    s.messages.push(
      {
        id: crypto.randomUUID(),
        role: "user",
        content: i.content,
        replaces: i.replaces,
        createdAt: now(),
        runId: run.id,
      },
      {
        id: assistantId,
        role: "assistant",
        content: "",
        runId: run.id,
        requestId: "dev-" + crypto.randomUUID(),
        createdAt: now(),
      },
    );
    s.runs.push(run);
    s.updatedAt = now();
    if (s.title === "新会话") s.title = i.content.slice(0, 25);
    const step: Step = {
      id: crypto.randomUUID(),
      label: "读取会话上下文",
      state: "completed",
      output:
        "含 " +
        s.messages.filter((m) => m.role === "user").length +
        " 轮消息（开发适配）",
    };
    this.append(d, run, "step", { step });
    if (i.mode === "agent") {
      const callId = crypto.randomUUID();
      this.append(d, run, "approval", {
        step: {
          id: crypto.randomUUID(),
          callId,
          label: "text_length · 纯计算工具",
          state: "waiting_approval",
          input: JSON.stringify({ text: i.content }),
        },
      });
    } else
      this.answer(
        d,
        run,
        i.content,
        s.messages.filter((m) => m.role === "user").length,
      );
    d.ready[run.id] = Date.now();
    this.save(d);
    return structuredClone(run);
  }
  private answer(d: RecordState, r: Run, text: string, turn: number) {
    const answer = text.includes("/error")
      ? ""
      : "### 开发模型回复\n\n这是第 **" +
        turn +
        "** 轮对话。已收到：\n\n" +
        text +
        '\n\n```ts\nconst mode = "controlled-demo";\n```\n\n> 当前内容由开发适配生成，未调用真实模型。';
    for (let offset = 0; offset < answer.length; offset += 12)
      this.append(d, r, "delta", { text: answer.slice(offset, offset + 12) });
    if (text.includes("/error"))
      this.append(d, r, "failed", {
        text: "开发模型模拟上游失败；未自动重新生成。",
      });
    else {
      this.append(d, r, "usage", { tokens: null });
      this.append(d, r, "completed");
    }
  }
  async events(id: string, runId: string, after: number | string) {
    if (typeof after !== "number") throw Error("开发游标格式错误。");
    const d = this.load(),
      s = this.session(d, id),
      r = s.runs.find((r) => r.id === runId);
    if (!r) throw Error("运行不存在。");
    const ready = Math.floor((Date.now() - (d.ready[runId] ?? 0)) / 80) + 1;
    const available = (d.events[runId] ?? []).slice(0, Math.max(0, ready));
    // A read materializes already recorded demo events. It never calls a model/tool or restarts a run.
    for (const e of available.filter((e) => BigInt(e.seq) > BigInt(r.cursor))) {
      if (e.type === "delta")
        s.messages.find((m) => m.id === r.assistantId)!.content += e.text ?? "";
      if (e.step) {
        const old = r.steps.findIndex((x) => x.id === e.step!.id);
        if (old < 0) r.steps.push(e.step);
        else r.steps[old] = e.step;
      }
      if (e.type === "approval") r.state = "waiting_approval";
      if (e.type === "usage")
        r.usage = {
          tokens: e.tokens ?? null,
          reason: e.tokens == null ? "开发模型未提供计量" : null,
        };
      if (["completed", "cancelled", "failed"].includes(e.type))
        r.state = e.type as Run["state"];
      if (e.type === "failed") r.error = e.text;
      r.cursor = e.seq;
    }
    this.save(d);
    return {
      events: structuredClone(
        available.filter((e) => BigInt(e.seq) > BigInt(after)),
      ),
      snapshot: structuredClone(s),
    };
  }
  async cancel(id: string, runId: string) {
    const d = this.load(),
      s = this.session(d, id),
      r = s.runs.find((r) => r.id === runId);
    if (!r) throw Error("运行不存在。");
    if (!["running", "waiting_approval"].includes(r.state)) return;
    d.events[r.id] = (d.events[r.id] ?? []).slice(0, Number(r.cursor));
    this.append(d, r, "cancelled");
    d.ready[r.id] = 0;
    this.save(d);
  }
  async approve(id: string, runId: string, callId: string, allow: boolean) {
    const d = this.load(),
      s = this.session(d, id),
      r = s.runs.find((r) => r.id === runId);
    if (!r || r.state !== "waiting_approval")
      throw Error("批准已失效，请重读运行。");
    const step = r.steps.find(
      (s) => s.callId === callId && s.state === "waiting_approval",
    );
    if (!step) throw Error("工具身份不匹配。");
    const result = {
      ...step,
      state: allow ? "completed" : "denied",
      output: allow
        ? JSON.stringify({
            characters: [...JSON.parse(step.input!).text].length,
          })
        : "用户拒绝",
    };
    this.append(d, r, "step", { step: result });
    r.state = "running"; // Consume the approval once; events expose the eventual terminal state.
    if (allow) {
      this.answer(
        d,
        r,
        "工具计算已完成",
        s.messages.filter((m) => m.role === "user").length,
      );
    } else this.append(d, r, "cancelled");
    d.ready[r.id] = Date.now() - Number(r.cursor) * 80;
    this.save(d);
  }
}
