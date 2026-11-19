<script setup lang="ts">
import { computed, onMounted, onBeforeUnmount, ref, shallowRef } from "vue";
import type { ChatService, Session, Run, Mode, Message } from "../chat/types";
import ChatMarkdown from "../components/ChatMarkdown.vue";
import PanelDialog from "../components/PanelDialog.vue";
const props = defineProps<{
  development?: boolean;
  service?: ChatService;
  http?: boolean;
  controlled?: boolean;
}>();
const activeStates = [
  "accepted",
  "running",
  "waiting_approval",
  "needs_confirmation",
];
const service = shallowRef<ChatService>(),
  sessions = ref<Session[]>([]),
  selected = ref<Session | null>(null),
  draft = ref(""),
  mode = ref<Mode>("chat"),
  model = ref(""),
  busy = ref(false),
  error = ref(""),
  connected = ref(true),
  uncertain = ref(false),
  pendingCommand = ref(""),
  rename = ref(""),
  renaming = ref(false),
  deleting = ref(false),
  editing = ref<string>(),
  initialized = ref(false);
const models = ref<{ id: string; label: string; modes: Mode[] }[]>([]);
let alive = true,
  epoch = 0,
  timer: ReturnType<typeof setTimeout> | undefined;
const currentRun = computed(
    () =>
      selected.value?.runs.find((r) => r.id === selected.value?.activeRunId) ??
      selected.value?.runs.at(-1),
  ),
  running = computed(
    () => !!currentRun.value && activeStates.includes(currentRun.value.state),
  );
const title = computed(() => selected.value?.title ?? "开始新的对话");
const modelAllowed = computed(() =>
  models.value.some(
    (m) => m.id === model.value && m.modes.includes(mode.value),
  ),
);
function messageContent(m: Message) {
  if (m.content) return m.content;
  const state = selected.value?.runs.find((r) => r.id === m.runId)?.state;
  return state &&
    [
      "completed",
      "failed",
      "cancelled",
      "limit_reached",
      "needs_confirmation",
    ].includes(state)
    ? "本次运行未返回文本。"
    : "等待响应…";
}
function report(e: unknown) {
  error.value = e instanceof Error ? e.message : "操作未完成，请重读会话。";
}
async function refreshList() {
  if (!service.value) return;
  const rows = await service.value.list();
  if (alive) sessions.value = rows;
}
function stopPolling() {
  clearTimeout(timer);
  timer = undefined;
  service.value?.stopEvents?.();
}
function schedule(run: Run, mine: number, id: string) {
  if (!alive || mine !== epoch || selected.value?.id !== id) return;
  stopPolling();
  if (
    !connected.value ||
    !["accepted", "running", "waiting_approval"].includes(run.state)
  )
    return;
  timer = setTimeout(
    () => void poll(id, run.id, run.cursor, mine, run.sequence),
    160,
  );
}
async function poll(
  id: string,
  runId: string,
  cursor: number | string,
  mine: number,
  sequence?: string,
) {
  if (!service.value || !alive || mine !== epoch || !connected.value) return;
  try {
    const page = await service.value.events(id, runId, cursor);
    if (!alive || mine !== epoch) return;
    const r = page.snapshot.runs.find((r) => r.id === runId);
    if (
      !r ||
      page.snapshot.id !== id ||
      page.events.some((e) => e.runId !== runId) ||
      page.events.some(
        (e, i) =>
          BigInt(e.seq) <=
            BigInt(sequence ?? (typeof cursor === "number" ? cursor : "0")) ||
          (i > 0 && BigInt(e.seq) <= BigInt(page.events[i - 1]!.seq)),
      )
    )
      throw Error("事件归属或顺序不一致，请只读重连。");
    selected.value = page.snapshot;
    await refreshList();
    schedule(r, mine, id);
  } catch (e) {
    if (mine === epoch && alive) {
      report(e);
      connected.value = false;
    }
  }
}
async function open(id: string) {
  if (!service.value) return;
  const mine = ++epoch;
  stopPolling();
  busy.value = true;
  error.value = "";
  draft.value = "";
  editing.value = undefined;
  try {
    const s = await service.value.read(id);
    if (!alive || mine !== epoch) return;
    if (s.id !== id) throw Error("会话归属不一致。");
    selected.value = s;
    location.hash = "chat/" + encodeURIComponent(id);
    const r = s.runs.find((r) => r.id === s.activeRunId) ?? s.runs.at(-1);
    if (r) {
      mode.value = r.mode;
      model.value = r.model;
    }
    if (pendingCommand.value) {
      const original = s.runs.find((r) => r.commandId === pendingCommand.value);
      if (original) {
        pendingCommand.value = "";
        uncertain.value = false;
      }
    }
    if (r && ["accepted", "running", "waiting_approval"].includes(r.state))
      void poll(id, r.id, r.cursor, mine, r.sequence);
  } catch (e) {
    if (mine === epoch) report(e);
  } finally {
    if (alive && mine === epoch) busy.value = false;
  }
}
async function create() {
  if (!service.value || busy.value) return;
  busy.value = true;
  try {
    const s = await service.value.create(model.value);
    await refreshList();
    await open(s.id);
  } catch (e) {
    report(e);
    uncertain.value = service.value?.hasPending?.() ?? uncertain.value;
  } finally {
    busy.value = false;
  }
}
async function send(
  replaces?: string,
  content?: string,
  operation?: "send" | "edit" | "regenerate",
) {
  if (
    !service.value ||
    !selected.value ||
    busy.value ||
    running.value ||
    uncertain.value ||
    !models.value.some(
      (m) => m.id === model.value && m.modes.includes(mode.value),
    ) ||
    !(content ?? draft.value).trim()
  )
    return;
  const id = selected.value.id,
    commandId = crypto.randomUUID(),
    text = content ?? draft.value;
  busy.value = true;
  error.value = "";
  pendingCommand.value = commandId;
  try {
    const run = await service.value.start({
      sessionId: id,
      commandId,
      content: text,
      model: model.value,
      mode: mode.value,
      replaces: replaces ?? editing.value,
      operation: operation ?? (editing.value ? "edit" : "send"),
    });
    if (!alive) return;
    if (run.commandId !== commandId) throw Error("提交关联不一致");
    pendingCommand.value = "";
    draft.value = "";
    editing.value = undefined;
    await open(id);
  } catch (e) {
    if (alive) {
      uncertain.value =
        service.value?.hasPending?.() ??
        !(
          e &&
          typeof e === "object" &&
          "uncertain" in e &&
          e.uncertain === false
        );
      report(e);
    }
  } finally {
    if (alive) busy.value = false;
  }
}
async function cancel() {
  if (!service.value || !selected.value || !currentRun.value || busy.value)
    return;
  busy.value = true;
  try {
    await service.value.cancel(selected.value.id, currentRun.value.id);
    await open(selected.value.id);
  } catch (e) {
    report(e);
  } finally {
    busy.value = false;
  }
}
async function approval(allow: boolean, callId?: string) {
  const r = currentRun.value,
    s = selected.value,
    step = r?.steps.find((s) => s.state === "waiting_approval"),
    originalCall = callId ?? step?.callId;
  if (!service.value || !s || !r || !originalCall || busy.value) return;
  busy.value = true;
  try {
    await service.value.approve(s.id, r.id, originalCall, allow);
    await open(s.id);
  } catch (e) {
    report(e);
  } finally {
    busy.value = false;
  }
}
async function saveTitle() {
  if (!service.value || !selected.value) return;
  busy.value = true;
  try {
    await service.value.rename(selected.value.id, rename.value);
    renaming.value = false;
    await refreshList();
    await open(selected.value.id);
  } catch (e) {
    report(e);
  } finally {
    busy.value = false;
  }
}
async function remove() {
  if (!service.value || !selected.value || running.value) return;
  busy.value = true;
  try {
    await service.value.remove(selected.value.id);
    epoch++;
    stopPolling();
    selected.value = null;
    location.hash = "chat";
    deleting.value = false;
    await refreshList();
  } catch (e) {
    report(e);
  } finally {
    busy.value = false;
  }
}
async function clear() {
  if (!service.value || running.value) return;
  await service.value.clear();
  epoch++;
  stopPolling();
  sessions.value = [];
  selected.value = null;
  location.hash = "chat";
  uncertain.value = false;
  pendingCommand.value = "";
}
function disconnect() {
  epoch++;
  connected.value = false;
  stopPolling();
}
async function reconnect() {
  connected.value = true;
  try {
    const restored = await service.value?.recover?.();
    if (restored) {
      uncertain.value = false;
      pendingCommand.value = "";
      await refreshList();
      await open(restored.id);
    } else if (selected.value) await open(selected.value.id);
    if (service.value?.hasPending) uncertain.value = service.value.hasPending();
  } catch (e) {
    report(e);
    uncertain.value = service.value?.hasPending?.() ?? uncertain.value;
    connected.value = false;
  }
}
function editMessage(id: string, text: string) {
  editing.value = id;
  draft.value = text;
}
function regenerate(messageId: string) {
  const s = selected.value;
  if (!s) return;
  const at = s.messages.findIndex((m) => m.id === messageId);
  const user = s.messages
    .slice(0, at)
    .reverse()
    .find((m) => m.role === "user");
  if (user) void send(messageId, user.content, "regenerate");
}
onMounted(async () => {
  try {
    if (props.service) service.value = props.service;
    else if (props.development) {
      const { DevelopmentChat } = await import("../chat/development");
      service.value = new DevelopmentChat();
    } else if (props.http) {
      const { HTTPChat } = await import("../chat/http");
      service.value = new HTTPChat(
        JSON.parse(import.meta.env.VITE_CHAT_AR1_CONFIG || "null"),
      );
    }
    if (service.value) {
      uncertain.value = service.value.hasPending?.() ?? false;
      models.value = await service.value.models();
      model.value = models.value[0]?.id ?? "";
      await refreshList();
      const id = decodeURIComponent(
        location.hash.startsWith("#chat/") ? location.hash.slice(6) : "",
      );
      if (uncertain.value && service.value.recover) await reconnect();
      else if (id) await open(id);
    }
  } catch (e) {
    report(e);
  } finally {
    initialized.value = true;
  }
});
onBeforeUnmount(() => {
  alive = false;
  epoch++;
  stopPolling();
  draft.value = "";
  service.value?.dispose?.();
});
</script>
<template>
  <section class="chat-workbench">
    <aside class="chat-history">
      <div class="chat-history-heading">
        <h2>会话</h2>
        <button
          class="primary"
          :disabled="!service || busy || uncertain || !model"
          @click="create"
        >
          ＋ 新建会话
        </button>
      </div>
      <p v-if="!sessions.length" class="muted">暂无会话</p>
      <button
        v-for="s in sessions"
        :key="s.id"
        class="chat-session"
        :disabled="busy"
        :class="{ chosen: selected?.id === s.id }"
        @click="open(s.id)"
      >
        <strong>{{ s.title }}</strong
        ><small>{{ new Date(s.updatedAt).toLocaleString() }}</small></button
      ><button
        v-if="development"
        class="quiet"
        :disabled="running"
        @click="clear"
      >
        清空开发会话数据
      </button>
    </aside>
    <div class="chat-main">
      <div class="title-row">
        <div>
          <p class="eyebrow">CHAT WORKSPACE</p>
          <h1>{{ title }}</h1>
        </div>
        <div class="actions">
          <button
            v-if="selected"
            :disabled="busy"
            @click="
              rename = selected.title;
              renaming = true;
            "
          >
            重命名</button
          ><button
            v-if="selected"
            class="danger"
            :disabled="busy || running"
            @click="deleting = true"
          >
            删除会话
          </button>
        </div>
      </div>
      <div v-if="development" class="notice">
        开发适配 ·
        会话与消息仅保存到此浏览器本地，可清空。无真实模型、Go会话服务或真实Token计量。请勿输入凭证或敏感内容。
      </div>
      <div v-else-if="controlled" class="notice">
        本地受控联调 · 会话和事件由 Go
        持久保存，模型为受控适配，工具是真实安全实现；测试用量不代表供应商账单。
      </div>
      <div v-else-if="initialized && !service" class="notice">
        Chat 会话服务未启用，请核对安装配置。现有在线试用和管理功能仍可使用。
      </div>
      <p v-if="error" role="alert" class="error">{{ error }}</p>
      <div v-if="uncertain" class="notice">
        提交结果未知，请只读查回原创建／运行操作，禁止再次生成。<button
          @click="reconnect"
        >
          核对原会话
        </button>
      </div>
      <div class="chat-controls">
        <label
          >运行模式<select v-model="mode" :disabled="running || busy">
            <option value="chat">普通 Chat</option>
            <option value="agent">Agent</option>
          </select></label
        ><label
          >模型<select v-model="model" :disabled="running || busy">
            <option
              v-for="m in models"
              :key="m.id"
              :value="m.id"
              :disabled="!m.modes.includes(mode)"
            >
              {{ m.label }}
            </option>
          </select></label
        ><button v-if="connected && running" @click="disconnect">
          断开事件连接</button
        ><button v-if="!connected" @click="reconnect">只读重连</button
        ><span v-if="currentRun" class="badge">{{ currentRun.state }}</span>
        <span v-if="currentRun?.cancelRequested" class="badge"
          >取消已请求 · 等待实际终止</span
        >
      </div>
      <p v-if="initialized && service && !modelAllowed" class="notice">
        当前没有支持所选模式的获准模型，请核对模型能力或选择其他模式。
      </p>
      <div class="chat-timeline" aria-live="polite">
        <div v-if="!selected" class="empty">
          <h2>有什么可以帮你？</h2>
          <p>新建会话，开始多轮对话或查看 Agent 执行过程。</p>
        </div>
        <article
          v-for="m in selected?.messages"
          :key="m.id"
          class="chat-message"
          :class="m.role"
        >
          <div class="chat-message-meta">
            <strong>{{
              m.role === "user" ? "你" : m.role === "tool" ? "工具" : "助手"
            }}</strong
            ><small>{{ m.createdAt }}</small>
          </div>
          <pre v-if="m.role === 'tool'">{{ m.content }}</pre>
          <ChatMarkdown v-else :content="messageContent(m)" /><small
            v-if="m.replaces"
            >修订关联：{{ m.replaces }}</small
          >
          <details v-if="m.requestId">
            <summary>原请求 / 计量关联</summary>
            <code>{{ m.requestId }}</code>
            <p>
              运行 {{ m.runId }} ·
              {{ selected?.runs.find((r) => r.id === m.runId)?.state }}
            </p>
            <p>
              Token：{{
                selected?.runs.find((r) => r.id === m.runId)?.usage.tokens ??
                "未知 / 不可获取"
              }}
            </p>
            <p>
              {{ selected?.runs.find((r) => r.id === m.runId)?.usage.reason }}
            </p>
          </details>
          <div class="actions">
            <button
              v-if="m.role === 'user'"
              :disabled="busy || running || uncertain"
              @click="editMessage(m.id, m.content)"
            >
              编辑为新消息</button
            ><button
              v-if="m.role === 'assistant'"
              :disabled="busy || running || uncertain"
              @click="regenerate(m.id)"
            >
              重新生成（新运行）
            </button>
          </div>
        </article>
      </div>
      <section v-if="currentRun?.mode === 'agent'" class="panel agent-trace">
        <h2>Agent 运行步骤</h2>
        <p>
          {{
            development ? "开发纯计算工具演示；" : ""
          }}工具输入和结果按不可信数据展示。
        </p>
        <article v-for="step in currentRun.steps" :key="step.id">
          <strong>{{ step.label }}</strong
          ><span class="badge">{{ step.state }}</span>
          <details open>
            <summary>工具输入 / 结果</summary>
            <pre>{{ step.input }}</pre>
            <pre>{{ step.output ?? "等待结果" }}</pre>
          </details>
        </article>
        <div v-if="currentRun.state === 'waiting_approval'" class="notice">
          <strong>等待批准</strong>
          <p>批准只适用于此运行及此工具调用。</p>
          <template v-if="currentRun.approvals">
            <article
              v-for="a in currentRun.approvals"
              :key="a.id"
              class="approval-card"
            >
              <strong>{{ a.tool }}@{{ a.revision }}</strong>
              <pre>{{ a.input }}</pre>
              <p>
                参数摘要：<code>{{ a.argsHash }}</code>
              </p>
              <p>批准有效期：{{ a.expiresAt }}</p>
              <button
                :disabled="busy || Date.parse(a.expiresAt) <= Date.now()"
                @click="approval(true, a.callId)"
              >
                批准此次工具
              </button>
              <button
                :disabled="busy || Date.parse(a.expiresAt) <= Date.now()"
                @click="approval(false, a.callId)"
              >
                拒绝
              </button>
            </article>
            <p v-if="!currentRun.approvals.length">
              批准状态已变化，请只读重连核对。
            </p>
          </template>
          <template v-else>
            <button :disabled="busy" @click="approval(true)">
              批准此次工具
            </button>
            <button :disabled="busy" @click="approval(false)">拒绝</button>
          </template>
        </div>
      </section>
      <div v-if="currentRun?.state === 'needs_confirmation'" class="notice">
        原模型请求或工具结果尚不确定，执行已隔离。请核对原请求／工具记录；此处不提供重新执行未知操作。
      </div>
      <details
        v-for="r in selected?.runs.filter((r) => r.childRequestIds)"
        :key="r.id"
        class="panel chat-usage"
        :open="r.id === currentRun?.id"
      >
        <summary>原请求 / 计量关联 · {{ r.state }}</summary>
        <p>
          运行 <code>{{ r.id }}</code>
        </p>
        <ul>
          <li v-for="id in r.childRequestIds" :key="id">
            <code>{{ id }}</code>
          </li>
        </ul>
        <p>
          {{
            r.aggregationComplete
              ? "权威投影完整"
              : "投影尚不完整，已知小计不代表总量"
          }}
          · {{ r.usage.reason }}
        </p>
        <p v-if="!r.usageGroups?.length">Token / 金额：未知 / 不可获取</p>
        <article
          v-for="g in r.usageGroups"
          :key="g.currency + '/' + g.price_version"
        >
          <p>{{ g.currency }} · 价表 {{ g.price_version }}</p>
          <p>
            Token 已知：{{ g.known_tokens }} · 在途：{{ g.inflight_tokens }} ·
            保留：{{ g.held_tokens }}
          </p>
          <p>
            金额（原子单位）已知：{{ g.known_money_atomic }} · 在途：{{
              g.inflight_money_atomic
            }}
            · 保留：{{ g.held_money_atomic }}
          </p>
        </article>
      </details>
      <div v-if="currentRun?.error" role="alert" class="error">
        {{ currentRun.error }}
      </div>
      <form class="chat-composer" @submit.prevent="send()">
        <p v-if="editing">
          将创建关联原消息的新修订；原消息与消费记录保留。<button
            type="button"
            @click="
              editing = undefined;
              draft = '';
            "
          >
            取消编辑
          </button>
        </p>
        <label
          >消息<textarea
            v-model="draft"
            rows="3"
            maxlength="8192"
            :disabled="!selected || running || busy || uncertain"
            placeholder="输入消息，支持 Markdown；Enter 换行"
          ></textarea>
        </label>
        <div class="title-row">
          <small
            >历史恢复仅查询原运行，不自动重发生成。{{
              !connected ? "事件连接已断开。" : ""
            }}</small
          >
          <div class="actions">
            <button
              type="button"
              class="danger"
              :disabled="!running || busy || currentRun?.cancelRequested"
              @click="cancel"
            >
              停止运行</button
            ><button
              class="primary"
              :disabled="
                !service ||
                !selected ||
                busy ||
                running ||
                uncertain ||
                !draft.trim() ||
                !modelAllowed
              "
            >
              发送消息
            </button>
          </div>
        </div>
      </form>
    </div>
    <PanelDialog
      v-if="renaming"
      title="重命名会话"
      :busy="busy"
      @close="renaming = false"
      ><form @submit.prevent="saveTitle">
        <label>会话名称<input v-model="rename" required maxlength="80" /></label
        ><button class="primary" :disabled="busy">保存名称</button>
      </form></PanelDialog
    ><PanelDialog
      v-if="deleting"
      title="删除会话"
      :busy="busy"
      @close="deleting = false"
      ><p>删除此会话及其本地开发历史？</p>
      <button class="danger" :disabled="busy" @click="remove">
        确认删除会话
      </button></PanelDialog
    >
  </section>
</template>
