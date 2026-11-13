<script setup lang="ts">
import { onMounted, onBeforeUnmount, reactive, ref, computed } from "vue";
import { api, ADMIN } from "../api/client";
import type { S } from "../api/contracts";
import { usePage, explain, uncertain } from "../ui";
import PanelDialog from "../components/PanelDialog.vue";
import { budgetInput, display } from "../domain";
const { rows, busy, error, cursor, refresh } = usePage((cursor) =>
  api.json<S["KeyPage"]>(
    ADMIN + "/keys" + (cursor ? "?cursor=" + encodeURIComponent(cursor) : ""),
    "KeyPage",
  ),
);
const form = reactive({
    name: "",
    window: "",
    requests: "",
    tokens: "",
    money: "",
    currency: "",
  }),
  secret = ref(""),
  message = ref(""),
  writing = ref(false),
  unknown = ref(false),
  edit = ref<S["Key"] | null>(null),
  revoke = ref<string | null>(null);
const emit = defineEmits<{
  navigate: [tab: string, filter?: { key_id: string }];
}>();
const showEditor = ref(false),
  search = ref(""),
  stateFilter = ref("all"),
  detailId = ref<string | null>(null),
  copied = ref(false);
const filtered = computed(() =>
  rows.value.filter(
    (k) =>
      (stateFilter.value === "all" || k.state === stateFilter.value) &&
      (k.name + " " + k.key_prefix)
        .toLowerCase()
        .includes(search.value.trim().toLowerCase()),
  ),
);
const detail = computed(() => rows.value.find((k) => k.id === detailId.value));
const activeCount = computed(
  () => rows.value.filter((k) => k.state === "active").length,
);
function beginCreate() {
  if (writing.value || unknown.value) return;
  clear();
  copied.value = false;
  showEditor.value = true;
}
function closeEditor() {
  if (writing.value) return;
  showEditor.value = false;
  clear();
}
async function copySecret() {
  const value = secret.value;
  try {
    await navigator.clipboard.writeText(value);
    if (alive && secret.value === value) copied.value = true;
  } catch {
    if (alive) message.value = "复制不可用，请手动保存本次原值。";
  }
}
function createdAt(value: string) {
  return new Date(value).toLocaleString("zh-CN", {
    timeZone: "UTC",
    hour12: false,
  });
}
let alive = true;
function editKey(k: S["Key"]) {
  showEditor.value = true;
  edit.value = k;
  form.name = k.name;
  form.window = k.budget_policy.window_kind;
  form.requests = k.budget_policy.limits.requests ?? "";
  form.tokens = k.budget_policy.limits.tokens ?? "";
  form.money = k.budget_policy.limits.money?.limit_atomic ?? "";
  form.currency = k.budget_policy.limits.money?.currency ?? "";
}
function clear() {
  edit.value = null;
  Object.assign(form, {
    name: "",
    window: "",
    requests: "",
    tokens: "",
    money: "",
    currency: "",
  });
}
async function save() {
  if (!alive || writing.value || unknown.value) return;
  writing.value = true;
  message.value = "";
  secret.value = "";
  try {
    const policy = budgetInput(form);
    if (edit.value) {
      await api.json<S["Key"]>(ADMIN + "/keys/" + edit.value.id, "Key", {
        method: "PATCH",
        body: JSON.stringify({
          expected_revision: edit.value.budget_policy.revision,
          limits: policy.limits,
        }),
      });
      if (!alive) return;
      message.value = "预算已更新。";
    } else {
      const result = await api.json<S["KeyCreated"]>(
        ADMIN + "/keys",
        "KeyCreated",
        {
          method: "POST",
          body: JSON.stringify({ name: form.name, budget_policy: policy }),
        },
      );
      if (!alive) return;
      secret.value = result.secret;
      message.value = "Key 已创建。原值只展示本次，请妥善保存。";
    }
    clear();
    showEditor.value = false;
    await refresh();
  } catch (e) {
    if (!alive) return;
    message.value = explain(e);
    unknown.value = uncertain(e);
  } finally {
    if (alive) writing.value = false;
  }
}
async function confirmRevoke() {
  if (!alive || !revoke.value || writing.value || unknown.value) return;
  writing.value = true;
  try {
    await api.json<S["Key"]>(
      ADMIN + "/keys/" + revoke.value + "/revoke",
      "Key",
      { method: "POST" },
    );
    if (!alive) return;
    revoke.value = null;
    await refresh();
    if (alive) message.value = "Key 已撤销。";
  } catch (e) {
    if (!alive) return;
    message.value = explain(e);
    unknown.value = uncertain(e);
  } finally {
    if (alive) writing.value = false;
  }
}
onMounted(() => refresh());
onBeforeUnmount(() => {
  alive = false;
  secret.value = "";
});
const dimensions = [
  ["requests", "请求数"],
  ["tokens", "Token"],
  ["money_atomic", "金额原子单位"],
] as const;
</script>
<template>
  <div class="title-row">
    <div>
      <p class="eyebrow">ACCESS & BUDGETS</p>
      <h1>平台 Key</h1>
      <p class="muted">管理应用的访问凭证，按 Key 控制预算并查看用量。</p>
    </div>
    <button
      class="primary"
      data-testid="create-key"
      :disabled="writing || unknown"
      @click="beginCreate"
    >
      <span aria-hidden="true">＋ </span>创建新 Key
    </button>
  </div>
  <div class="key-overview">
    <section>
      <span>已加载 Key</span><strong>{{ rows.length }}</strong
      ><small>{{ cursor ? "还有更多，可继续加载" : "当前列表" }}</small>
    </section>
    <section>
      <span>有效</span><strong>{{ activeCount }}</strong
      ><small>可随时修改预算或撤销</small>
    </section>
    <section>
      <span>已撤销</span><strong>{{ rows.length - activeCount }}</strong
      ><small>原值不会再次返回</small>
    </section>
  </div>
  <p v-if="message" role="status" :class="unknown ? 'error' : 'notice'">
    {{ message }}
  </p>
  <section v-if="secret" class="secret panel">
    <div class="title-row">
      <div>
        <span class="badge good">创建成功</span>
        <h2>保存你的新 Key</h2>
        <p class="muted">原值仅本次展示，关闭后无法找回。</p>
      </div>
      <button
        type="button"
        @click="
          secret = '';
          copied = false;
        "
      >
        我已保存，关闭原值
      </button>
    </div>
    <code data-testid="one-time-secret">{{ secret }}</code
    ><button type="button" @click="copySecret">
      {{ copied ? "已复制" : "复制原值" }}
    </button>
  </section>
  <section class="key-list panel">
    <div class="key-toolbar">
      <label class="key-search"
        ><span class="sr-only">搜索 Key</span
        ><input
          v-model="search"
          placeholder="搜索名称或 Key 前缀"
          type="search" /></label
      ><label class="key-filter"
        ><span class="sr-only">Key 状态</span
        ><select v-model="stateFilter">
          <option value="all">全部状态</option>
          <option value="active">有效</option>
          <option value="revoked">已撤销</option>
        </select></label
      ><button :disabled="busy" @click="refresh()">刷新列表</button>
    </div>
    <p v-if="busy" role="status" class="muted">正在加载 Key…</p>
    <p v-if="error" role="alert" class="error">{{ error }}</p>
    <div v-if="!busy && !error && !rows.length" class="empty">
      尚无平台 Key。
      <p>为不同应用创建独立 Key，便于管理预算与用量。</p>
    </div>
    <div v-else-if="!filtered.length && !busy && !error" class="empty">
      没有匹配的 Key。
    </div>
    <div v-if="filtered.length" class="table-scroll">
      <table class="key-table">
        <thead>
          <tr>
            <th>名称 / Key</th>
            <th>状态</th>
            <th>预算上限</th>
            <th>创建时间（UTC）</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="k in filtered" :key="k.id" class="key-row">
            <td data-label="名称 / Key">
              <strong>{{ k.name }}</strong
              ><code>{{ k.key_prefix }}••••</code>
            </td>
            <td data-label="状态">
              <span class="badge" :class="k.state === 'active' ? 'good' : ''">{{
                k.state === "active" ? "有效" : "已撤销"
              }}</span
              ><small v-if="k.budget_state.admission_blocked" class="blocked"
                >准入已阻止</small
              >
            </td>
            <td data-label="预算上限" class="key-limits">
              <span
                >请求
                <b>{{ k.budget_policy.limits.requests ?? "未设置" }}</b></span
              ><span
                >Token
                <b>{{ k.budget_policy.limits.tokens ?? "未设置" }}</b></span
              ><span
                >金额
                <b>{{
                  k.budget_policy.limits.money
                    ? k.budget_policy.limits.money.limit_atomic +
                      " " +
                      k.budget_policy.limits.money.currency +
                      "（原子单位）"
                    : "未设置"
                }}</b></span
              ><small>{{
                k.budget_policy.window_kind === "utc_day"
                  ? "每日重置（UTC）"
                  : "每月重置（UTC）"
              }}</small>
            </td>
            <td data-label="创建时间">{{ createdAt(k.created_at) }}</td>
            <td data-label="操作">
              <div class="key-actions">
                <button @click="detailId = k.id">查看预算</button
                ><button
                  :disabled="writing || unknown || k.state === 'revoked'"
                  @click="editKey(k)"
                >
                  修改预算</button
                ><button @click="emit('navigate', 'usage', { key_id: k.id })">
                  查看用量</button
                ><button
                  class="danger"
                  :disabled="writing || unknown || k.state === 'revoked'"
                  @click="revoke = k.id"
                >
                  撤销
                </button>
              </div>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
    <button v-if="cursor" :disabled="busy" @click="refresh(true)">
      加载更多
    </button>
    <p class="key-footnote">
      仅显示 Key 前缀。预算与用量以服务端为准，筛选仅作用于已加载列表。
    </p>
  </section>
  <PanelDialog
    v-if="showEditor"
    :title="edit ? '修改 Key 预算' : '创建新 Key'"
    :busy="writing"
    @close="closeEditor"
    ><form class="key-form" @submit.prevent="save">
      <label
        >名称<input
          v-model="form.name"
          required
          maxlength="64"
          :disabled="!!edit"
          placeholder="例如：内部应用 / 测试环境" /></label
      ><label
        >UTC 周期<select v-model="form.window" required :disabled="!!edit">
          <option disabled value="">请选择周期</option>
          <option value="utc_day">UTC 日</option>
          <option value="utc_month">UTC 月</option>
        </select></label
      >
      <fieldset>
        <legend>预算限制</legend>
        <p class="muted">
          留空关闭对应维度；0 表示禁止消费。金额按服务端原子单位填写。
        </p>
        <div class="key-budget-fields">
          <label
            >请求数限额<input
              v-model="form.requests"
              inputmode="numeric"
              placeholder="留空关闭此维度" /></label
          ><label
            >Token 限额<input
              v-model="form.tokens"
              inputmode="numeric"
              placeholder="留空关闭此维度" /></label
          ><label
            >金额限额（原子单位）<input
              v-model="form.money"
              inputmode="numeric"
              placeholder="留空关闭此维度" /></label
          ><label
            >币种<input
              v-model="form.currency"
              placeholder="启用金额时必填"
              maxlength="3"
          /></label>
        </div>
      </fieldset>
      <p v-if="unknown" role="alert" class="error">
        原写入结果未知。请刷新并由管理员核对；原值无法通过列表找回，本页面已暂停写入。
      </p>
      <div class="dialog-actions">
        <button type="button" :disabled="writing" @click="closeEditor">
          取消编辑</button
        ><button class="primary" :disabled="writing || unknown">
          {{ writing ? "正在提交…" : edit ? "保存预算" : "创建 Key" }}
        </button>
      </div>
    </form></PanelDialog
  >
  <PanelDialog
    v-if="detail"
    :title="detail.name + ' · 预算明细'"
    @close="detailId = null"
    ><p class="muted">
      {{ detail.budget_state.window_start }} →
      {{ detail.budget_state.window_end }} ·
      {{ detail.budget_state.currency ?? "未启用金额" }}
    </p>
    <p v-if="detail.budget_state.admission_blocked" class="error">
      已阻止准入：{{ detail.budget_state.block_reason }}
    </p>
    <div class="table-scroll">
      <table>
        <thead>
          <tr>
            <th>维度</th>
            <th>已知使用</th>
            <th>在途预留</th>
            <th>未知占用</th>
            <th>可用</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="[field, label] in dimensions" :key="field">
            <th>{{ label }}</th>
            <td>{{ display(detail.budget_state.known_used[field]) }}</td>
            <td>{{ display(detail.budget_state.inflight_reserved[field]) }}</td>
            <td>{{ display(detail.budget_state.uncertainty_held[field]) }}</td>
            <td>
              {{
                field === "money_atomic" && !detail.budget_policy.limits.money
                  ? "已关闭"
                  : field !== "money_atomic" &&
                      detail.budget_policy.limits[field] === null
                    ? "已关闭"
                    : display(detail.budget_state.available[field])
              }}
            </td>
          </tr>
        </tbody>
      </table>
    </div>
    <p class="muted">
      未知占用与已知消费分别保留，不随容量释放而退款。
    </p></PanelDialog
  >
  <PanelDialog
    v-if="revoke"
    title="撤销平台 Key"
    :busy="writing"
    @close="revoke = null"
    ><p>
      确认撤销
      {{
        rows.find((k) => k.id === revoke)?.name
      }}？后续请求将被拒绝，已有请求与占用仍由服务端结算。
    </p>
    <div class="dialog-actions">
      <button :disabled="writing" @click="revoke = null">取消</button
      ><button class="danger" :disabled="writing" @click="confirmRevoke">
        确认撤销
      </button>
    </div></PanelDialog
  >
</template>
