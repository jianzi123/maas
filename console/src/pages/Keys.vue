<script setup lang="ts">
import { onMounted, onBeforeUnmount, reactive, ref } from "vue";
import { api, ADMIN } from "../api/client";
import type { S } from "../api/contracts";
import { usePage, explain, uncertain } from "../ui";
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
let alive = true;
function editKey(k: S["Key"]) {
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
      <p class="muted">明确设置三维预算，原值仅在创建时返回一次。</p>
    </div>
    <button :disabled="busy" @click="refresh()">刷新列表</button>
  </div>
  <p v-if="message" role="status" :class="unknown ? 'error' : 'notice'">
    {{ message }}
  </p>
  <div v-if="secret" class="secret panel">
    <strong>原值仅本次展示</strong
    ><code data-testid="one-time-secret">{{ secret }}</code
    ><button @click="secret = ''">我已保存，关闭原值</button>
  </div>
  <form class="panel form-grid" @submit.prevent="save">
    <h2>{{ edit ? "修改显式预算" : "创建新 Key" }}</h2>
    <label
      >名称<input
        v-model="form.name"
        required
        maxlength="64"
        :disabled="!!edit" /></label
    ><label
      >UTC 周期<select v-model="form.window" required :disabled="!!edit">
        <option disabled value="">请选择周期</option>
        <option value="utc_day">UTC 日</option>
        <option value="utc_month">UTC 月</option>
      </select></label
    ><label
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
    <p class="muted full">
      留空关闭对应维度；0
      表示禁止消费。金额按服务端原子单位展示，不推测汇率或小数精度。
    </p>
    <button class="primary" :disabled="writing || unknown">
      {{ edit ? "保存预算" : "创建 Key" }}</button
    ><button v-if="edit" type="button" @click="clear">取消编辑</button>
    <p v-if="unknown" class="full">
      原写入结果未知。请刷新并由管理员核对；创建原值无法通过列表找回。本页面已暂停写入。
    </p>
  </form>
  <p v-if="busy" role="status">正在加载 Key…</p>
  <p v-if="error" role="alert" class="error">{{ error }}</p>
  <p v-if="!busy && !error && !rows.length" class="empty">尚无平台 Key。</p>
  <article v-for="k in rows" :key="k.id" class="panel">
    <div class="title-row">
      <h2>
        {{ k.name }} <code>{{ k.key_prefix }}…</code>
      </h2>
      <span class="badge" :class="k.state === 'active' ? 'good' : ''">{{
        k.state === "active" ? "有效" : "已撤销"
      }}</span>
    </div>
    <p class="muted">
      {{ k.budget_state.window_start }} → {{ k.budget_state.window_end }} ·
      {{ k.budget_state.currency ?? "未启用金额" }} · 策略
      {{ k.budget_policy.revision }}
    </p>
    <p v-if="k.budget_state.admission_blocked" class="error">
      已阻止准入：{{ k.budget_state.block_reason }}
    </p>
    <div class="table-scroll">
      <table>
        <thead>
          <tr>
            <th>维度</th>
            <th>限额</th>
            <th>已知使用</th>
            <th>在途预留</th>
            <th>未知占用</th>
            <th>可用</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="[field, label] in dimensions" :key="field">
            <th>{{ label }}</th>
            <td>
              {{
                field === "money_atomic"
                  ? (k.budget_policy.limits.money?.limit_atomic ?? "已关闭")
                  : (k.budget_policy.limits[field] ?? "已关闭")
              }}
            </td>
            <td>{{ display(k.budget_state.known_used[field]) }}</td>
            <td>{{ display(k.budget_state.inflight_reserved[field]) }}</td>
            <td>{{ display(k.budget_state.uncertainty_held[field]) }}</td>
            <td>
              {{
                field === "money_atomic" && !k.budget_policy.limits.money
                  ? "已关闭"
                  : field !== "money_atomic" &&
                      k.budget_policy.limits[field] === null
                    ? "已关闭"
                    : display(k.budget_state.available[field])
              }}
            </td>
          </tr>
        </tbody>
      </table>
    </div>
    <div class="actions">
      <button
        :disabled="writing || unknown || k.state === 'revoked'"
        @click="editKey(k)"
      >
        修改预算</button
      ><button
        class="danger"
        :disabled="writing || unknown || k.state === 'revoked'"
        @click="revoke = k.id"
      >
        撤销
      </button>
    </div>
    <div v-if="revoke === k.id" class="notice">
      <p>
        确认撤销 {{ k.name }}？后续请求将被拒绝，已有请求与占用仍由服务端结算。
      </p>
      <button class="danger" :disabled="writing" @click="confirmRevoke">
        确认撤销</button
      ><button @click="revoke = null">取消</button>
    </div>
  </article>
  <button v-if="cursor" :disabled="busy" @click="refresh(true)">
    加载更多
  </button>
</template>
