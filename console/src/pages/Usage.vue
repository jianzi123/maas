<script setup lang="ts">
import { onMounted, onBeforeUnmount, reactive, ref, shallowRef } from "vue";
import { api, ADMIN } from "../api/client";
import type { S } from "../api/contracts";
import { display } from "../domain";
import { explain } from "../ui";
const props = defineProps<{ keyFilter?: string }>();
const filter = reactive({
    date_from: "",
    date_to: "",
    model_alias: "",
    source_id: "",
    key_id: props.keyFilter ?? "",
    status: "",
  }),
  kind = ref("requests"),
  rows = shallowRef<S["RequestRecord"][]>([]),
  summary = shallowRef<S["SummaryRow"][]>([]),
  cursor = ref<string | null>(null),
  busy = ref(false),
  error = ref(""),
  at = ref(""),
  complete = ref(false);
let applied = "",
  epoch = 0;
function clearResults() {
  rows.value = [];
  summary.value = [];
  cursor.value = null;
  at.value = "";
  complete.value = false;
  applied = "";
}
async function load(more = false) {
  const mine = ++epoch;
  busy.value = true;
  error.value = "";
  if (!more) clearResults();
  complete.value = false;
  try {
    const q = new URLSearchParams();
    if (more) {
      for (const [k, v] of new URLSearchParams(applied)) q.set(k, v);
    } else {
      if (!!filter.date_from !== !!filter.date_to)
        throw new Error(
          "请同时填写起止日期，或全部留空使用服务端默认 UTC 窗口。",
        );
      if (filter.date_from) {
        const days =
          (Date.parse(filter.date_to) - Date.parse(filter.date_from)) /
          86400000;
        if (days <= 0 || days > 31)
          throw new Error("UTC 区间需大于 0 且不超过 31 天。");
      }
      for (const [k, v] of Object.entries(filter))
        if (v && (k !== "status" || kind.value === "requests")) q.set(k, v);
    }
    if (more && cursor.value) q.set("cursor", cursor.value);
    const selectedKind = kind.value;
    const page = await api.json<S["RequestPage"] | S["SummaryPage"]>(
      ADMIN + "/usage/" + selectedKind + "?" + q,
      selectedKind === "requests" ? "RequestPage" : "SummaryPage",
    );
    if (mine !== epoch) return;
    if (selectedKind === "requests")
      rows.value = more
        ? [...rows.value, ...(page.data as S["RequestRecord"][])]
        : (page.data as S["RequestRecord"][]);
    else
      summary.value = more
        ? [...summary.value, ...(page.data as S["SummaryRow"][])]
        : (page.data as S["SummaryRow"][]);
    cursor.value = page.next_cursor;
    at.value = page.generated_at;
    complete.value = page.data_complete;
    q.delete("cursor");
    applied = q.toString();
  } catch (e) {
    if (mine === epoch) {
      clearResults();
      error.value = explain(e);
    }
  } finally {
    if (mine === epoch) busy.value = false;
  }
}
function changeKind() {
  epoch++;
  cursor.value = null;
  rows.value = [];
  summary.value = [];
  void load();
}
onMounted(() => load());
onBeforeUnmount(() => {
  epoch++;
});
</script>
<template>
  <div class="title-row">
    <div>
      <p class="eyebrow">USAGE & REQUESTS</p>
      <h1>请求与用量</h1>
      <p class="muted">按原始来源和价格快照查看，未知用量保留未知。</p>
    </div>
    <select
      v-model="kind"
      aria-label="查询类型"
      :disabled="busy"
      @change="changeKind"
    >
      <option value="requests">请求明细</option>
      <option value="summary">用量汇总</option>
    </select>
  </div>
  <form class="panel form-grid" @submit.prevent="load()">
    <label
      >UTC 起始日期（含）<input v-model="filter.date_from" type="date" /></label
    ><label
      >UTC 结束日期（不含）<input v-model="filter.date_to" type="date" /></label
    ><label>模型别名<input v-model="filter.model_alias" /></label
    ><label>来源 UUID<input v-model="filter.source_id" /></label
    ><label>Key UUID<input v-model="filter.key_id" /></label
    ><label v-if="kind === 'requests'"
      >请求状态<select v-model="filter.status">
        <option value="">全部</option>
        <option
          v-for="v in [
            'in_progress',
            'succeeded',
            'failed',
            'cancelled',
            'timed_out',
            'interrupted',
          ]"
          :key="v"
        >
          {{ v }}
        </option>
      </select></label
    ><button class="primary" :disabled="busy">查询</button>
  </form>
  <p v-if="busy" role="status">正在查询…</p>
  <p v-if="error" role="alert" class="error">{{ error }}</p>
  <p v-if="at" class="muted">
    数据观察时间：{{ at }} ·
    {{ complete ? "本次查询数据完整" : "本次查询数据不完整" }}
  </p>
  <p
    v-if="kind === 'requests' && !busy && !rows.length && !error"
    class="empty"
  >
    当前筛选没有请求。
  </p>
  <article
    v-for="r in kind === 'requests' ? rows : []"
    :key="r.request_id"
    class="panel"
  >
    <div class="title-row">
      <h2>{{ r.model_alias }}</h2>
      <span class="badge">{{ r.status }}</span>
    </div>
    <p>
      <code>{{ r.request_id }}</code>
    </p>
    <p>
      {{ r.source_type }} / {{ r.source_id }} · Key {{ r.key_id }} ·
      {{ r.received_at }}
    </p>
    <p>
      Token 输入 {{ display(r.usage.input_tokens) }} / 输出
      {{ display(r.usage.output_tokens) }} / 总量
      {{ display(r.usage.total_tokens) }}
    </p>
    <p>
      usage {{ r.usage.source }} / {{ r.usage.missing_reason ?? "完整" }} · 提交
      {{ r.submission_state }} · 计量 {{ r.metering_state }} · 错误
      {{ r.error_code ?? "无" }}
    </p>
    <details>
      <summary>预算、价格与活动修订快照</summary>
      <pre>{{
        JSON.stringify(
          {
            reservation_plan: r.reservation_plan,
            budget_accounting: r.budget_accounting,
            invocation_binding: r.invocation_binding,
          },
          null,
          2,
        )
      }}</pre>
    </details>
  </article>
  <p
    v-if="kind === 'summary' && !busy && !summary.length && !error"
    class="empty"
  >
    当前筛选没有汇总。
  </p>
  <article
    v-for="(s, i) in kind === 'summary' ? summary : []"
    :key="i"
    class="panel"
  >
    <h2>{{ s.model_alias }} · {{ s.quota_date }}</h2>
    <p>{{ s.source_type }} / {{ s.source_id }} · Key {{ s.key_id }}</p>
    <p>
      请求 {{ s.admitted_total }} · 成功 {{ s.succeeded }} · 进行中
      {{ s.in_progress }} · 失败 {{ s.failed }} · 取消 {{ s.cancelled }} · 超时
      {{ s.timed_out }} · 断流 {{ s.interrupted }}
    </p>
    <p>
      已知 Token {{ s.total_tokens_known }} · 缺失 Token 请求
      {{ s.missing_token_requests }} · 未知 Token 占用
      {{ s.token_uncertainty_held }}
    </p>
    <p>
      币种 {{ s.currency ?? "未知" }} · 价格版本
      {{ s.price_version ?? "未知" }} · 已知费用（原子单位）{{
        display(s.cost_known_atomic)
      }}
      · 未知金额占用 {{ display(s.money_uncertainty_held_atomic) }} ·
      缺失费用请求 {{ s.missing_cost_requests }}
    </p>
  </article>
  <button v-if="cursor" :disabled="busy" @click="load(true)">加载更多</button>
  <p class="muted">
    不同来源、币种、价格版本分别呈现。已知部分用量不代表总量完整。
  </p>
</template>
