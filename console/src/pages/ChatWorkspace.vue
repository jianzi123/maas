<script setup lang="ts">
import { computed, onMounted, onBeforeUnmount, ref, shallowRef } from "vue";
import type { ChatService, Session, Run, Mode } from "../chat/types";
import ChatMarkdown from "../components/ChatMarkdown.vue";
import PanelDialog from "../components/PanelDialog.vue";
const props = defineProps<{ development?: boolean; service?: ChatService }>();
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
const currentRun = computed(() => selected.value?.runs.at(-1)),
  running = computed(
    () =>
      !!currentRun.value &&
      ["running", "waiting_approval"].includes(currentRun.value.state),
  );
const title = computed(() => selected.value?.title ?? "开始新的对话");
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
}
function schedule(run: Run, mine: number, id: string) {
  stopPolling();
  if (
    !connected.value ||
    !["running", "waiting_approval"].includes(run.state) ||
    run.state === "waiting_approval"
  )
    return;
  timer = setTimeout(() => void poll(id, run.id, run.cursor, mine), 160);
}
async function poll(id: string, runId: string, cursor: number, mine: number) {
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
          e.seq <= cursor || (i > 0 && e.seq <= page.events[i - 1]!.seq),
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
    const r = s.runs.at(-1);
    if (pendingCommand.value) {
      const original = s.runs.find((r) => r.commandId === pendingCommand.value);
      if (original) {
        pendingCommand.value = "";
        uncertain.value = false;
      }
    }
    if (r) await poll(id, r.id, r.cursor, mine);
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
    const s = await service.value.create();
    await refreshList();
    await open(s.id);
  } catch (e) {
    report(e);
  } finally {
    busy.value = false;
  }
}
async function send(replaces?: string, content?: string) {
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
    });
    if (!alive) return;
    if (run.commandId !== commandId) throw Error("提交关联不一致");
    pendingCommand.value = "";
    draft.value = "";
    editing.value = undefined;
    await open(id);
  } catch (e) {
    if (alive) {
      uncertain.value = true;
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
async function approval(allow: boolean) {
  const r = currentRun.value,
    s = selected.value,
    step = r?.steps.find((s) => s.state === "waiting_approval");
  if (!service.value || !s || !r || !step?.callId || busy.value) return;
  busy.value = true;
  try {
    await service.value.approve(s.id, r.id, step.callId, allow);
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
  connected.value = false;
  stopPolling();
}
async function reconnect() {
  connected.value = true;
  if (selected.value) await open(selected.value.id);
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
  if (user) void send(messageId, user.content);
}
onMounted(async () => {
  try {
    if (props.service) service.value = props.service;
    else if (props.development) {
      const { DevelopmentChat } = await import("../chat/development");
      service.value = new DevelopmentChat();
    }
    if (service.value) {
      models.value = await service.value.models();
      model.value = models.value[0]?.id ?? "";
      await refreshList();
      const id = decodeURIComponent(
        location.hash.startsWith("#chat/") ? location.hash.slice(6) : "",
      );
      if (id && sessions.value.some((s) => s.id === id)) await open(id);
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
});
</script>
<template>
  <section class="chat-workbench">
    <aside class="chat-history">
      <div class="chat-history-heading">
        <h2>会话</h2>
        <button class="primary" :disabled="!service || busy" @click="create">
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
      <div v-else-if="initialized && !service" class="notice">
        Chat会话/运行服务正在接线；共享契约尚待MAAS-2/20收敛。现有在线试用和管理功能仍可使用。
      </div>
      <p v-if="error" role="alert" class="error">{{ error }}</p>
      <div v-if="uncertain" class="notice">
        提交结果未知，请只读重连原会话核对原操作，禁止再次生成。<button
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
      </div>
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
            <strong>{{ m.role === "user" ? "你" : "助手" }}</strong
            ><small>{{ m.createdAt }}</small>
          </div>
          <ChatMarkdown :content="m.content || '等待响应…'" /><small
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
        <p>开发纯计算工具演示；输入和输出按不可信数据展示。</p>
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
          <button :disabled="busy" @click="approval(true)">批准此次工具</button
          ><button :disabled="busy" @click="approval(false)">拒绝</button>
        </div>
      </section>
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
              :disabled="!running || busy"
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
                !draft.trim()
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
