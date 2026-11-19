import { api, type Api } from "../api/client";
import { checked, checkedEvent, type AR } from "./ar1-contracts";
import type {
  ChatService,
  Session,
  Run,
  StartInput,
  Mode,
  ChatEvent,
} from "./types";

const ROOT = "/api/agent/v1";
const pendingKey = "maas.chat.ar1.pending.v1";
type Pending = {
  kind: "create" | "run";
  operation: string;
  hash: string;
  session?: string;
};
export interface HTTPChatConfig {
  limits: AR["RunLimits"];
  tools: { name: string; revision: string }[];
}
export class ChatHTTPError extends Error {
  constructor(
    public code: string,
    public uncertain = false,
    public status = 0,
  ) {
    super(
      (
        {
          unauthenticated: "登录会话已过期，请重新登录。",
          forbidden: "当前会话没有执行此操作的权限。",
          revision_conflict: "会话已变化，请只读重连后核对。",
          conversation_busy: "当前会话仍有活动运行。",
          capability_unsupported: "该模型未获准支持所选运行模式。",
          run_limit_exceeded: "运行限制超过安装策略，请核对配置。",
          operation_conflict: "同一操作标识对应不同内容，请核对原操作。",
          unknown_write: "提交结果未知，请只读查回原操作。",
          dependency_unavailable: "会话服务暂不可用，请只读重连。",
          not_found: "记录不存在或当前身份不可访问；这不证明原提交未执行。",
          protocol_error: "AR-1 响应关联或格式异常，请只读核对原记录。",
        } as Record<string, string>
      )[code] ?? "会话请求未完成（" + code + "）。",
    );
  }
}
function canonical(value: unknown): string {
  if (Array.isArray(value)) return "[" + value.map(canonical).join(",") + "]";
  if (value && typeof value === "object")
    return (
      "{" +
      Object.entries(value)
        .sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0))
        .map(([k, v]) => JSON.stringify(k) + ":" + canonical(v))
        .join(",") +
      "}"
    );
  return JSON.stringify(value).replace(
    /[<>&\u2028\u2029]/g,
    (c) => "\\u" + c.charCodeAt(0).toString(16).padStart(4, "0"),
  );
}
async function digest(value: unknown) {
  const hash = await crypto.subtle.digest(
    "SHA-256",
    new TextEncoder().encode(canonical(value)),
  );
  return Array.from(new Uint8Array(hash), (b) =>
    b.toString(16).padStart(2, "0"),
  ).join("");
}
function owns(ok: unknown): asserts ok {
  if (!ok) throw new ChatHTTPError("protocol_error");
}
const sidPath = (sid: string) => ROOT + "/sessions/" + encodeURIComponent(sid);
const runPath = (sid: string, rid: string) =>
  sidPath(sid) + "/runs/" + encodeURIComponent(rid);
const textOf = (m: AR["Message"]) =>
  m.parts
    .filter((p) => p.type === "text")
    .map((p) => p.text)
    .join("");
const compare = (a: string, b: string) =>
  BigInt(a) < BigInt(b) ? -1 : BigInt(a) > BigInt(b) ? 1 : 0;

// Same-origin application session only. No inference key or provider credential.
export class HTTPChat implements ChatService {
  private caps?: AR["Capabilities"];
  private snapshots = new Map<string, Session>();
  private approvals = new Map<string, AR["Approval"]>();
  private controller?: AbortController;
  constructor(
    private config: HTTPChatConfig,
    private client: Api = api,
    private storage: Storage = sessionStorage,
  ) {
    if (!config || !config.limits) throw Error("Chat 缺少明确的安装运行限制。");
    checked("RunLimits", config.limits);
    if (
      !Array.isArray(config.tools) ||
      config.tools.length > 16 ||
      config.tools.some(
        (t) =>
          !t || typeof t.name !== "string" || typeof t.revision !== "string",
      )
    )
      throw Error("Chat 运行配置缺少明确工具版本。");
  }
  private pending(): Pending | null {
    const raw = this.storage.getItem(pendingKey);
    if (!raw) return null;
    const p = JSON.parse(raw) as Pending;
    if (
      !["create", "run"].includes(p.kind) ||
      !/^[0-9a-f-]{36}$/.test(p.operation) ||
      !/^[0-9a-f]{64}$/.test(p.hash) ||
      (p.kind === "run" && !/^[0-9a-f-]{36}$/.test(p.session ?? ""))
    )
      throw Error("原操作标识损坏，请保留现场核对。");
    return p;
  }
  hasPending() {
    return !!this.pending();
  }
  private guard() {
    if (this.hasPending()) throw new ChatHTTPError("unknown_write", true);
  }
  private async response(path: string, init: RequestInit = {}) {
    const write = !!init.method && init.method !== "GET";
    const headers = new Headers(init.headers);
    if (write) {
      headers.set("Content-Type", "application/json");
      headers.set("X-CSRF-Token", this.client.csrf);
    }
    let r: Response;
    try {
      r = await this.client.fetcher(path, {
        ...init,
        headers,
        credentials: "same-origin",
        cache: "no-store",
        redirect: "error",
      });
    } catch (e) {
      if (init.signal?.aborted) throw e;
      throw new ChatHTTPError(
        write ? "unknown_write" : "dependency_unavailable",
        write,
      );
    }
    if (r.status === 401)
      window.dispatchEvent(new Event("maas-session-expired"));
    if (!r.ok) {
      let code = "protocol_error";
      try {
        const v = checked("Error", await r.json());
        owns(v.error.http_request_id === r.headers.get("X-Request-ID"));
        code = v.error.code;
      } catch {
        /* Never render arbitrary error bodies. */
      }
      throw new ChatHTTPError(
        code,
        write && (r.status >= 500 || code === "protocol_error"),
        r.status,
      );
    }
    return r;
  }
  private async json<K extends keyof AR>(
    path: string,
    schema: K,
    init: RequestInit = {},
  ): Promise<AR[K]> {
    const r = await this.response(path, init);
    try {
      const value = checked(schema, await r.json());
      if (schema === "Snapshot") {
        const s = value as AR["Snapshot"];
        owns(r.headers.get("ETag") === '"' + s.conversation.revision + '"');
      }
      return value;
    } catch {
      throw new ChatHTTPError(
        "protocol_error",
        !!init.method && init.method !== "GET",
        r.status,
      );
    }
  }
  async models() {
    this.caps = await this.json(ROOT + "/capabilities", "Capabilities");
    return this.caps.model_modes.map((m) => ({
      id: m.model_alias,
      label:
        m.model_alias +
        (m.approval_state === "controlled"
          ? "（受控模型）"
          : m.approval_state === "pending"
            ? "（待批准）"
            : ""),
      modes: (m.approval_state === "pending"
        ? []
        : m.tools_protocol === "tools-v1"
          ? ["chat", "agent"]
          : ["chat"]) as Mode[],
    }));
  }
  private async pages<
    K extends "ConversationPage" | "MessagePage" | "StepPage" | "ToolCallPage",
  >(
    path: string,
    schema: K,
    cursor: string | null = null,
  ): Promise<AR[K]["data"]> {
    const out: unknown[] = [],
      seen = new Set<string>();
    do {
      const query = new URLSearchParams({
        page_size: "100",
        ...(cursor ? { cursor } : {}),
      });
      const page = await this.json(path + "?" + query, schema);
      out.push(...page.data);
      cursor = page.next_cursor;
      if (cursor) {
        owns(!seen.has(cursor));
        seen.add(cursor);
      }
      if (out.length > 20000)
        throw Error("历史数据超出本页读取上限，请缩小查询范围。");
    } while (cursor);
    return out as AR[K]["data"];
  }
  async list() {
    const rows = await this.pages(ROOT + "/sessions", "ConversationPage");
    return rows.map((s) => ({
      id: s.id,
      title: s.title,
      updatedAt: s.updated_at,
      revision: s.revision,
      activeRunId: s.active_run_id,
      messages: [],
      runs: [],
    }));
  }
  async create(model?: string) {
    this.guard();
    owns(
      this.caps?.model_modes.some(
        (m) => m.model_alias === model && m.approval_state !== "pending",
      ),
    );
    const payload = {
      client_operation_id: crypto.randomUUID(),
      title: "新会话",
      model_alias: model!,
    };
    const p: Pending = {
      kind: "create",
      operation: payload.client_operation_id,
      hash: await digest(payload),
    };
    this.storage.setItem(pendingKey, JSON.stringify(p));
    let acknowledged = false;
    try {
      const s = await this.json(ROOT + "/sessions", "Conversation", {
        method: "POST",
        body: JSON.stringify(payload),
      });
      acknowledged = true;
      const command = await this.json(
        ROOT + "/session-creation-commands/" + p.operation,
        "SessionCreationCommand",
      );
      owns(
        command.client_operation_id === p.operation &&
          command.request_sha256 === p.hash &&
          command.session_id === s.id,
      );
      const restored = await this.read(s.id);
      this.storage.removeItem(pendingKey);
      return restored;
    } catch (e) {
      if (
        !acknowledged &&
        e instanceof ChatHTTPError &&
        !e.uncertain &&
        e.status >= 400 &&
        e.status < 500
      )
        this.storage.removeItem(pendingKey);
      throw e;
    }
  }
  async recover() {
    const p = this.pending();
    if (!p) return null;
    const value =
      p.kind === "create"
        ? await this.json(
            ROOT + "/session-creation-commands/" + p.operation,
            "SessionCreationCommand",
          )
        : await this.json(
            sidPath(p.session!) + "/commands/" + p.operation,
            "Command",
          );
    owns(
      value.client_operation_id === p.operation &&
        value.request_sha256 === p.hash &&
        (p.kind !== "run" || value.session_id === p.session),
    );
    if (value.state !== "accepted" || ("run_id" in value && !value.run_id))
      throw new ChatHTTPError("unknown_write", true);
    const s = await this.read(value.session_id);
    if ("run_id" in value)
      owns(
        s.runs.some(
          (r) => r.id === value.run_id && r.commandId === p.operation,
        ),
      );
    this.storage.removeItem(pendingKey);
    return s;
  }
  private projectRun(r: AR["Run"], messages: AR["Message"][]): Run {
    return {
      id: r.id,
      commandId: r.client_operation_id,
      model: r.model_alias,
      mode: r.mode,
      state: r.state,
      assistantId:
        [...messages]
          .reverse()
          .find((m) => m.run_id === r.id && m.role === "assistant")?.id ?? "",
      cursor: r.resume_cursor,
      sequence: r.last_event_seq,
      cancelRequested: r.cancel_requested,
      childRequestIds: r.child_request_ids,
      usageGroups: r.usage_groups,
      aggregationComplete: r.aggregation_complete,
      usage: {
        tokens: null,
        reason: r.aggregation_complete
          ? "按原子请求及币种／价表展示权威用量分组。"
          : "用量尚不完整；已知小计不代表完整总量。",
      },
      steps: [],
      approvals: [],
      error: r.reason ?? undefined,
    };
  }
  private async replay(sid: string, rid: string) {
    const out: AR["SessionEvent"][] = [];
    let cursor: string | null = null;
    do {
      const page: AR["EventPage"] = await this.json(
        runPath(sid, rid) +
          "/events?" +
          new URLSearchParams({
            page_size: "100",
            ...(cursor ? { after: cursor } : {}),
          }),
        "EventPage",
      );
      for (const e of page.data) {
        const v = checkedEvent(e);
        owns(
          v.session_id === sid &&
            v.run_id === rid &&
            BigInt(v.seq) === BigInt(out.at(-1)?.seq ?? "0") + 1n,
        );
        out.push(v);
      }
      owns(!page.next_cursor || page.next_cursor === out.at(-1)?.cursor);
      cursor = page.next_cursor;
      if (out.length > 20000) throw Error("事件历史超出读取上限。");
    } while (cursor);
    return out;
  }
  async read(id: string): Promise<Session> {
    const wire = await this.json(sidPath(id), "Snapshot");
    owns(
      wire.conversation.id === id &&
        wire.runs.every((r) => r.session_id === id),
    );
    const messages = [
      ...wire.messages,
      ...(wire.messages_next_cursor
        ? await this.pages(
            sidPath(id) + "/messages",
            "MessagePage",
            wire.messages_next_cursor,
          )
        : []),
    ];
    owns(
      messages.every((m) => m.session_id === id) &&
        new Set(messages.map((m) => m.id)).size === messages.length,
    );
    messages.sort((a, b) => compare(a.position, b.position));
    const runs = wire.runs.map((r) => this.projectRun(r, messages));
    const current = wire.conversation.active_run_id
      ? runs.find((r) => r.id === wire.conversation.active_run_id)
      : runs.at(-1);
    if (wire.conversation.active_run_id) owns(current);
    if (current) {
      const raw = wire.runs.find((r) => r.id === current.id)!;
      owns(
        wire.event_run_id === raw.id &&
          wire.last_event_seq === raw.last_event_seq &&
          wire.resume_cursor === raw.resume_cursor,
      );
      const steps = await this.pages(
        runPath(id, current.id) + "/steps",
        "StepPage",
      );
      const calls = await this.pages(
        runPath(id, current.id) + "/tool-calls",
        "ToolCallPage",
      );
      owns(
        steps.every((s) => s.run_id === current.id) &&
          calls.every((c) => c.run_id === current.id),
      );
      current.steps = [
        ...steps.map((s) => ({
          id: s.id,
          label: "步骤 " + s.index + " · " + s.protocol_revision,
          state: s.state,
          output: s.child_request_id
            ? "原请求：" + s.child_request_id
            : undefined,
        })),
        ...calls.map((c) => ({
          id: c.id,
          callId: c.id,
          label: c.name + "@" + c.tool_revision,
          state: c.state,
          input: JSON.stringify(c.arguments, null, 2),
          output: c.result
            ? JSON.stringify(c.result.result, null, 2)
            : undefined,
        })),
      ];
      if (current.state === "waiting_approval") {
        for (const e of await this.replay(id, current.id)) {
          if (
            BigInt(e.seq) <= BigInt(raw.last_event_seq) &&
            ["approval.required", "approval.resolved"].includes(e.type)
          ) {
            const a = checked("Approval", e.data);
            owns(a.run_id === current.id);
            this.approvals.set(a.id, a);
          }
        }
        for (const approval of this.approvals.values()) {
          if (approval.run_id !== current.id || approval.state !== "pending")
            continue;
          const a = await this.json(
            runPath(id, current.id) + "/approvals/" + approval.id,
            "Approval",
          );
          owns(
            a.id === approval.id &&
              a.call_id === approval.call_id &&
              a.run_id === current.id,
          );
          this.approvals.set(a.id, a);
          if (a.state === "pending")
            current.approvals!.push({
              id: a.id,
              callId: a.call_id,
              tool: a.tool_name,
              revision: a.tool_revision,
              argsHash: a.args_sha256,
              policyRevision: a.policy_revision,
              expiresAt: a.expires_at,
              state: a.state,
              input: JSON.stringify(a.arguments, null, 2),
            });
        }
      }
    }
    const result: Session = {
      id,
      title: wire.conversation.title,
      revision: wire.conversation.revision,
      activeRunId: wire.conversation.active_run_id,
      updatedAt: wire.conversation.updated_at,
      messages: messages.map((m) => ({
        id: m.id,
        role: m.role,
        content:
          textOf(m) ||
          m.parts
            .filter((p) => p.type !== "text")
            .map((p) =>
              p.type === "tool_call"
                ? "工具调用：" + p.name
                : p.type === "tool_result"
                  ? JSON.stringify(p.result, null, 2)
                  : "",
            )
            .join("\n"),
        runId: m.run_id ?? undefined,
        replaces: m.supersedes_message_id ?? undefined,
        createdAt: m.created_at,
      })),
      runs,
    };
    const old = this.snapshots.get(id);
    if (old?.revision && BigInt(old.revision) > BigInt(result.revision!))
      return structuredClone(old);
    this.snapshots.set(id, result);
    return structuredClone(result);
  }
  async start(i: StartInput) {
    this.guard();
    owns(
      this.caps?.model_modes.some(
        (m) =>
          m.model_alias === i.model &&
          m.approval_state !== "pending" &&
          (i.mode === "chat" || m.tools_protocol === "tools-v1"),
      ),
    );
    if (
      i.mode === "agent" &&
      !this.config.tools.every((t) =>
        this.caps!.tools.some(
          (a) => a.name === t.name && a.revision === t.revision,
        ),
      )
    )
      throw new ChatHTTPError("capability_unsupported");
    const s = this.snapshots.get(i.sessionId) ?? (await this.read(i.sessionId));
    const operation = i.operation ?? (i.replaces ? "edit" : "send");
    const payload = checked("RunCreate", {
      client_operation_id: i.commandId,
      mode: i.mode,
      operation,
      text: operation === "regenerate" ? null : i.content,
      referenced_message_id: i.replaces ?? null,
      model_alias: i.model,
      limits: {
        ...this.config.limits,
        ...(i.mode === "chat" ? { max_model_calls: 1 } : {}),
      },
      tools: i.mode === "chat" ? [] : this.config.tools,
    });
    const p: Pending = {
      kind: "run",
      operation: i.commandId,
      session: i.sessionId,
      hash: await digest(payload),
    };
    this.storage.setItem(pendingKey, JSON.stringify(p));
    try {
      const v = await this.json(sidPath(i.sessionId) + "/runs", "RunAccepted", {
        method: "POST",
        headers: { "If-Match": '"' + s.revision + '"' },
        body: JSON.stringify(payload),
      });
      owns(
        v.conversation.id === i.sessionId &&
          v.run.session_id === i.sessionId &&
          v.run.client_operation_id === i.commandId &&
          v.operation.session_id === i.sessionId &&
          v.operation.client_operation_id === i.commandId &&
          v.operation.request_sha256 === p.hash &&
          v.operation.run_id === v.run.id &&
          v.input_message.session_id === i.sessionId &&
          v.resume_cursor === v.run.resume_cursor,
      );
      this.storage.removeItem(pendingKey);
      return this.projectRun(v.run, [v.input_message]);
    } catch (e) {
      if (
        e instanceof ChatHTTPError &&
        !e.uncertain &&
        e.status >= 400 &&
        e.status < 500
      )
        this.storage.removeItem(pendingKey);
      throw e;
    }
  }
  stopEvents() {
    this.controller?.abort();
    this.controller = undefined;
  }
  async events(sid: string, rid: string, after: number | string) {
    owns(typeof after === "string");
    const previous = this.snapshots.get(sid),
      original = previous?.runs.find((r) => r.id === rid);
    owns(previous && original && original.cursor === after);
    this.stopEvents();
    const controller = (this.controller = new AbortController());
    const timer = setTimeout(() => controller.abort(), 1200);
    const events: AR["SessionEvent"][] = [];
    const messages = new Map(previous.messages.map((m) => [m.id, m.content]));
    let reader: ReadableStreamDefaultReader<Uint8Array> | undefined;
    try {
      const r = await this.response(
        runPath(sid, rid) + "/events/stream?" + new URLSearchParams({ after }),
        { signal: controller.signal },
      );
      owns(
        r.headers.get("Content-Type")?.startsWith("text/event-stream") &&
          r.body,
      );
      reader = r.body.getReader();
      const decoder = new TextDecoder("utf-8", { fatal: true });
      let buffer = "",
        done = false;
      while (!done && !events.length) {
        const chunk = await reader.read();
        done = chunk.done ?? false;
        buffer += decoder.decode(chunk.value, { stream: !done });
        if (buffer.length > 1048576) throw new ChatHTTPError("protocol_error");
        buffer = buffer.replace(/\r\n/g, "\n");
        let boundary: number;
        while ((boundary = buffer.indexOf("\n\n")) >= 0) {
          const block = buffer.slice(0, boundary);
          buffer = buffer.slice(boundary + 2);
          const lines = block
            .split("\n")
            .filter((l) => l && !l.startsWith(":"));
          if (!lines.length) continue;
          const field = (name: string) =>
            lines
              .filter((l) => l.startsWith(name + ":"))
              .map((l) => l.slice(name.length + 1).replace(/^ /, ""));
          const ids = field("id"),
            types = field("event"),
            data = field("data");
          owns(ids.length === 1 && types.length === 1 && data.length > 0);
          const e = checkedEvent(JSON.parse(data.join("\n")));
          owns(
            e.session_id === sid &&
              e.run_id === rid &&
              e.cursor === ids[0] &&
              e.type === types[0] &&
              BigInt(e.seq) ===
                BigInt(events.at(-1)?.seq ?? original.sequence ?? "0") + 1n,
          );
          if (e.type === "message.created") {
            const m = checked("Message", e.data);
            owns(
              m.session_id === sid && m.run_id === rid && !messages.has(m.id),
            );
            messages.set(m.id, textOf(m));
          }
          if (e.type === "message.delta") {
            const d = e.data as {
              message_id: string;
              offset: string;
              text: string;
            };
            const text = messages.get(d.message_id);
            owns(
              text !== undefined &&
                BigInt(d.offset) ===
                  BigInt(new TextEncoder().encode(text).length),
            );
            messages.set(d.message_id, text + d.text);
          }
          if (e.type === "message.committed") {
            const m = checked("Message", e.data);
            owns(
              m.session_id === sid && m.run_id === rid && messages.has(m.id),
            );
            messages.set(m.id, textOf(m));
          }
          events.push(e);
        }
      }
      if (done && buffer.trim()) throw new ChatHTTPError("protocol_error");
    } catch (e) {
      if (e instanceof ChatHTTPError && e.status === 410)
        return { events: [], snapshot: await this.read(sid) };
      if (!controller.signal.aborted) throw e;
    } finally {
      clearTimeout(timer);
      await reader?.cancel().catch(() => {});
      if (this.controller === controller) this.controller = undefined;
    }
    const snapshot = await this.read(sid),
      current = snapshot.runs.find((r) => r.id === rid);
    owns(
      current &&
        BigInt(current.sequence ?? "0") >=
          BigInt(events.at(-1)?.seq ?? original.sequence ?? "0"),
    );
    return {
      events: events.map((e) => ({
        seq: e.seq,
        runId: e.run_id,
        type: "sync" as ChatEvent["type"],
      })),
      snapshot,
    };
  }
  async cancel(sid: string, rid: string) {
    const r = await this.json(runPath(sid, rid) + "/cancel", "Run", {
      method: "POST",
      body: "{}",
    });
    owns(r.session_id === sid && r.id === rid);
  }
  async approve(sid: string, rid: string, callId: string, allow: boolean) {
    const a = [...this.approvals.values()].find(
      (a) => a.run_id === rid && a.call_id === callId && a.state === "pending",
    );
    owns(a && Date.parse(a.expires_at) > Date.now());
    const current = await this.json(
      runPath(sid, rid) + "/approvals/" + a.id,
      "Approval",
    );
    owns(
      current.id === a.id &&
        current.call_id === callId &&
        current.run_id === rid &&
        current.state === "pending" &&
        current.args_sha256 === a.args_sha256 &&
        current.policy_revision === a.policy_revision &&
        current.tool_revision === a.tool_revision,
    );
    const d = {
      decision_id: crypto.randomUUID(),
      decision: allow ? "allow" : "deny",
      args_sha256: a.args_sha256,
      tool_revision: a.tool_revision,
      policy_revision: a.policy_revision,
    };
    // Never automatically retry an unknown decision; read the original approval.
    this.approvals.delete(a.id);
    const reply = await this.json(
      runPath(sid, rid) + "/approvals/" + a.id + "/decision",
      "Approval",
      { method: "POST", body: JSON.stringify(d) },
    );
    owns(reply.id === a.id && reply.run_id === rid && reply.call_id === callId);
  }
  async rename(id: string, title: string) {
    this.guard();
    const s = this.snapshots.get(id) ?? (await this.read(id));
    const r = await this.json(sidPath(id), "Conversation", {
      method: "PATCH",
      headers: { "If-Match": '"' + s.revision + '"' },
      body: JSON.stringify({ title }),
    });
    owns(r.id === id);
  }
  async remove(id: string) {
    this.guard();
    const s = this.snapshots.get(id) ?? (await this.read(id));
    await this.response(sidPath(id), {
      method: "DELETE",
      headers: { "If-Match": '"' + s.revision + '"' },
    });
    this.snapshots.delete(id);
  }
  async clear(): Promise<void> {
    throw Error("服务端历史不提供浏览器一键清空。");
  }
  dispose() {
    this.stopEvents();
    this.snapshots.clear();
    this.approvals.clear();
  }
}
