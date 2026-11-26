<script setup lang="ts">
import { computed, onMounted, onBeforeUnmount, ref, shallowRef } from "vue";
import { api, ADMIN } from "../api/client";
import type { S, D } from "../api/contracts";
import { streamChat } from "../api/stream";
import { lookupRequest } from "../api/recovery";
import { display } from "../domain";
import { explain, statusLabel } from "../ui";
const props = withDefaults(
  defineProps<{ initialModel?: string; inferenceAvailable?: boolean }>(),
  { inferenceAvailable: true },
);
const emit = defineEmits<{ navigate: [tab: string] }>();
const models = ref<S["AdminModel"][]>([]),
  model = ref(props.initialModel ?? ""),
  key = ref(""),
  prompt = ref(""),
  maxTokens = ref<number | undefined>(),
  submittedPrompt = ref(""),
  showExample = ref(false),
  output = ref(""),
  state = ref("idle"),
  id = ref(""),
  message = ref(""),
  usage = shallowRef<S["Usage"] | null>(null),
  lookup = shallowRef<D["RequestLookupPage"] | null>(null),
  looking = ref(false);
let controller: AbortController | undefined,
  alive = true,
  requestEpoch = 0,
  lookupEpoch = 0;
const selected = computed(() => models.value.find((m) => m.id === model.value));
async function loadModels() {
  try {
    const result = (
      await api.json<S["AdminModelList"]>(ADMIN + "/models", "AdminModelList")
    ).data;
    if (alive) models.value = result;
  } catch (e) {
    if (alive) message.value = explain(e);
  }
}
async function recover() {
  if (!id.value || looking.value) return;
  const requestId = id.value,
    generation = requestEpoch,
    mine = ++lookupEpoch;
  const current = () =>
    alive &&
    generation === requestEpoch &&
    mine === lookupEpoch &&
    id.value === requestId;
  looking.value = true;
  try {
    const page = await lookupRequest(api, requestId);
    if (current()) lookup.value = page;
  } catch (e) {
    if (current()) message.value = "回查未完成：" + explain(e);
  } finally {
    if (current()) looking.value = false;
  }
}
async function send() {
  if (props.inferenceAvailable === false) return;
  if (!alive || state.value === "streaming" || !selected.value?.callable)
    return;
  const generation = ++requestEpoch;
  const active = () => alive && generation === requestEpoch;
  lookupEpoch++;
  looking.value = false;
  controller = new AbortController();
  submittedPrompt.value = prompt.value;
  state.value = "streaming";
  output.value = "";
  id.value = "";
  usage.value = null;
  lookup.value = null;
  message.value = "";
  const current = controller;
  try {
    await streamChat(
      api,
      key.value,
      {
        model: model.value,
        messages: [{ role: "user", content: prompt.value }],
        stream: true,
        ...(maxTokens.value ? { max_tokens: maxTokens.value } : {}),
      },
      current.signal,
      {
        id: (v) => {
          if (active()) id.value = v;
        },
        chunk: (v) => {
          if (active()) output.value += v;
        },
        usage: (v) => {
          if (active()) usage.value = v;
        },
      },
    );
    if (active()) state.value = "completed";
  } catch (e) {
    if (active()) {
      state.value = current.signal.aborted ? "stopped" : "interrupted";
      message.value = current.signal.aborted
        ? "已停止浏览器传输；上游生成和费用状态待核验。"
        : explain(e);
    }
  } finally {
    if (active()) {
      controller = undefined;
      if (id.value) await recover();
      else if (state.value !== "completed")
        message.value += " 未收到可信原请求 ID，结果未知。";
    }
  }
}
function stop() {
  controller?.abort();
}
onMounted(() => {
  if (props.inferenceAvailable) void loadModels();
});
onBeforeUnmount(() => {
  alive = false;
  requestEpoch++;
  lookupEpoch++;
  controller?.abort();
  key.value = "";
  prompt.value = "";
  output.value = "";
});
</script>
<template>
  <div class="title-row">
    <div>
      <p class="eyebrow">PLAYGROUND</p>
      <h1>在线试用</h1>
      <p class="muted">通过统一调用入口进行流式试用。</p>
    </div>
    <span class="badge" :class="state === 'streaming' ? 'good' : ''">{{
      statusLabel(state)
    }}</span>
  </div>
  <div v-if="props.inferenceAvailable === false" class="notice">
    当前安装未启用此在线试用入口。请使用 Chat
    工作台查看已配置模型、对话和原请求用量。<button
      @click="emit('navigate', 'chat')"
    >
      前往 Chat 工作台
    </button>
  </div>
  <form
    v-if="props.inferenceAvailable"
    class="play-workspace"
    @submit.prevent="send"
  >
    <section class="panel invocation-settings">
      <h2>调用设置</h2>
      <p class="caption">选择模型与本次调用凭证</p>
      <label
        >模型<select v-model="model" required :disabled="state === 'streaming'">
          <option disabled value="">选择模型</option>
          <option
            v-for="m in models"
            :key="m.id"
            :value="m.id"
            :disabled="
              !m.callable ||
              !m.capabilities.streaming ||
              !m.capabilities.protocols.includes('chat_completions')
            "
          >
            {{ m.display_name }} · {{ m.callable ? "可调用" : "未开放" }}
          </option>
        </select></label
      ><button
        type="button"
        :disabled="state === 'streaming'"
        @click="loadModels"
      >
        刷新模型</button
      ><label
        >消费 Key<input
          v-model="key"
          type="password"
          autocomplete="off"
          required
          :disabled="state === 'streaming'" /></label
      ><small>仅保留在本页内存，离开页面即清除。</small
      ><label
        >最大输出 Token<input
          v-model.number="maxTokens"
          type="number"
          min="1"
          :max="selected?.capabilities.verified_max_output_tokens ?? 4096"
          placeholder="使用服务端上限内默认值"
          :disabled="state === 'streaming'"
      /></label>
      <div class="chips">
        <span class="chip">{{
          selected?.source_type === "external"
            ? "外部 API"
            : selected
              ? "私有推理"
              : "尚未选择来源"
        }}</span
        ><span class="chip">固定来源</span>
      </div>
      <button type="button" class="quiet" @click="showExample = !showExample">
        查看请求示例
      </button>
      <pre v-if="showExample">
POST /v1/chat/completions
{ "model": "{{ model || "模型别名" }}", "messages": […], "stream": true }</pre>
      <p class="caption">消费 Key 只用于本次试用；不会保存对话到浏览器存储。</p>
    </section>
    <div class="conversation-column">
      <section class="panel answer conversation-pane">
        <div class="conversation-heading">
          <span class="model-icon">◈</span>
          <div>
            <strong>{{ selected?.display_name || "开始一次模型试用" }}</strong>
            <p class="caption">
              {{
                selected?.callable
                  ? "模型已开放，实际准入以服务端为准"
                  : "选择可调用模型后发送"
              }}
            </p>
          </div>
        </div>
        <div v-if="submittedPrompt" class="message-bubble user-message">
          <small>你</small>
          <p>{{ submittedPrompt }}</p>
        </div>
        <div class="message-bubble assistant-message">
          <small>模型回复</small>
          <pre aria-live="polite">{{ output || "响应将在这里逐步显示。" }}</pre>
        </div>
      </section>
      <div class="panel composer">
        <label
          >消息<textarea
            v-model="prompt"
            required
            maxlength="8192"
            rows="3"
            :disabled="state === 'streaming'"
            placeholder="输入一条消息…"
          ></textarea>
        </label>
        <div class="actions">
          <button
            class="primary"
            :disabled="
              state === 'streaming' || !prompt.trim() || !selected?.callable
            "
          >
            发送请求</button
          ><button
            type="button"
            class="danger"
            :disabled="state !== 'streaming'"
            @click="stop"
          >
            停止传输
          </button>
        </div>
      </div>
    </div>
  </form>
  <p v-if="message" role="alert" class="notice">{{ message }}</p>
  <section v-if="props.inferenceAvailable || id" class="panel">
    <h2>本次请求结果</h2>
    <details>
      <summary>技术状态代码</summary>
      <code>{{ state }}</code>
    </details>
    <p class="caption">停止后继续核对原请求，传输结果与账务状态分别呈现。</p>
    <p>传输状态：{{ statusLabel(state) }} · 实际生成停止：未核验</p>
    <p>
      原请求 ID：<code>{{ id || "尚未获取" }}</code>
    </p>
    <p>
      流中 Token：{{ display(usage?.total_tokens) }} ·
      {{ usage?.missing_reason ?? "未报告缺失原因" }}
    </p>
    <button
      :disabled="!id || looking || state === 'streaming'"
      @click="recover"
    >
      {{ looking ? "回查中…" : "回查原请求" }}</button
    ><template v-if="lookup"
      ><p>
        精确查询：{{ lookup.lookup.resolution }} · 请求终态：{{
          lookup.data[0]?.status ?? "未知"
        }}
        · 容量：{{ lookup.lookup.capacity.state }}
      </p>
      <p>
        Token：{{ display(lookup.data[0]?.usage.total_tokens) }} · 计量：{{
          lookup.data[0]?.metering_state ?? "未知"
        }}
      </p>
      <p>容量观察时间：{{ lookup.lookup.capacity.checked_at }}</p>
      <details>
        <summary>原请求预算与修订快照</summary>
        <p>技术传输状态：{{ state }}</p>
        <pre>{{
          JSON.stringify(
            {
              accounting: lookup.data[0]?.budget_accounting,
              binding: lookup.data[0]?.invocation_binding,
            },
            null,
            2,
          )
        }}</pre>
      </details></template
    >
    <p class="muted">
      容量释放不表示退款、生成停止或未知用量已结清。精确回查使用 v0.4.2
      草案适配，旧服务不兼容时保留未知。
    </p>
  </section>
</template>
