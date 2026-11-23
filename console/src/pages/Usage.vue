<script setup lang="ts">
import { onMounted, onBeforeUnmount, reactive, ref, shallowRef } from "vue";
import { api, ADMIN } from "../api/client";
import type { S } from "../api/contracts";
import { display } from "../domain";
import { explain, statusLabel } from "../ui";
import PanelDialog from "../components/PanelDialog.vue";
import { lookupRequest } from "../api/recovery";
import type { D } from "../api/contracts";

const props = defineProps<{ keyFilter?: string; modelFilter?: string }>();
const emit = defineEmits<{
  navigate: [tab: string, filter?: { key_id: string }];
}>();
const detail = shallowRef<S["RequestRecord"] | null>(null),
  exactId = ref(""),
  exact = shallowRef<D["RequestLookupPage"] | null>(null),
  exactBusy = ref(false);
let exactEpoch = 0;
async function findExact() {
  const mine = ++exactEpoch;
  exactBusy.value = true;
  error.value = "";
  try {
    const page = await lookupRequest(api, exactId.value);
    if (mine !== exactEpoch) return;
    exact.value = page;
    detail.value = page.data[0] ?? null;
  } catch (e) {
    if (mine === exactEpoch) {
      exact.value = null;
      error.value = explain(e);
    }
  } finally {
    if (mine === exactEpoch) exactBusy.value = false;
  }
}
const filter = reactive({
    date_from: "",
    date_to: "",
    model_alias: props.modelFilter ?? "",
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
  detail.value = null;
  exactEpoch++;
  exactBusy.value = false;
  exact.value = null;
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
  exactEpoch++;
});
</script>

<template>
  <div class="title-row">
    <div>
      <p class="eyebrow">REQUESTS & USAGE</p>
      <h1>请求与用量</h1>
      <p class="muted">定位每一次请求，理解已知用量与仍保留的未知占用。</p>
    </div>
    <button :disabled="busy" @click="load()">刷新数据</button>
  </div>
  <div class="tabs" role="tablist" aria-label="用量视图">
    <button
      v-for="[value, label] in [
        ['requests', '请求明细'],
        ['summary', '用量汇总'],
      ]"
      :key="value"
      role="tab"
      :aria-selected="kind === value"
      :class="{ active: kind === value }"
      @click="
        kind = value;
        changeKind();
      "
    >
      {{ label }}
    </button>
  </div>
  <label class="sr-only"
    >查询类型<select v-model="kind" aria-label="查询类型" @change="changeKind">
      <option value="requests">请求明细</option>
      <option value="summary">用量汇总</option>
    </select></label
  >
  <form class="panel query-panel" @submit.prevent="load()">
    <div class="toolbar">
      <label
        >模型别名<input
          v-model="filter.model_alias"
          placeholder="全部模型" /></label
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
            :value="v"
          >
            {{ statusLabel(v) }}
          </option>
        </select></label
      ><button class="primary" :disabled="busy">查询</button>
    </div>
    <p v-if="filter.key_id" class="filter-chip">
      按 Key 查询：{{ filter.key_id }}
      <button
        type="button"
        class="quiet"
        @click="
          filter.key_id = '';
          load();
        "
      >
        清除
      </button>
    </p>
    <details>
      <summary>高级查询 · UTC 日期 / 精确 ID</summary>
      <div class="form-grid">
        <label
          >UTC 起始日期（含）<input
            v-model="filter.date_from"
            type="date" /></label
        ><label
          >UTC 结束日期（不含）<input
            v-model="filter.date_to"
            type="date" /></label
        ><label>来源 UUID<input v-model="filter.source_id" /></label
        ><label>Key UUID<input v-model="filter.key_id" /></label>
      </div>
      <div class="toolbar">
        <label class="search-field"
          >原请求 ID<input
            v-model="exactId"
            placeholder="可信的原 request_id" /></label
        ><button
          type="button"
          :disabled="exactBusy || !exactId"
          @click="findExact"
        >
          {{ exactBusy ? "回查中…" : "精确回查" }}
        </button>
      </div>
    </details>
  </form>
  <p v-if="busy" role="status">正在查询…</p>
  <p v-if="error" role="alert" class="error">
    {{ error }} <button :disabled="busy" @click="load()">重新查询列表</button>
  </p>
  <div v-if="at" class="info-strip">
    观察时间 {{ at }} · {{ complete ? "本次查询数据完整" : "本次查询数据不完整"
    }}<span
      >已加载 {{ kind === "requests" ? rows.length : summary.length }} 条{{
        cursor ? " · 还有更多分页" : ""
      }}</span
    >
  </div>
  <p v-if="exact" class="notice">
    原请求查询：{{ exact.lookup.resolution }} · 容量
    {{ exact.lookup.capacity.state }}；容量回收不代表退款。
  </p>
  <div
    v-if="
      !busy && !error && !(kind === 'requests' ? rows.length : summary.length)
    "
    class="empty"
  >
    <h2>
      {{ kind === "requests" ? "当前筛选没有请求。" : "当前筛选没有汇总。" }}
    </h2>
    <p>调整筛选或完成一次获准调用后刷新。聚合暂缺不能证明请求不存在。</p>
    <button @click="emit('navigate', 'play')">前往在线试用 →</button>
  </div>
  <div
    v-if="kind === 'requests' && rows.length"
    class="panel table-scroll request-inventory"
  >
    <table class="request-table">
      <thead>
        <tr>
          <th>请求 / 模型</th>
          <th>时间 / 来源</th>
          <th>结果</th>
          <th>Token</th>
          <th>计量</th>
          <th>操作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="r in rows" :key="r.request_id" data-testid="request-row">
          <td data-label="模型 / 原请求">
            <strong>{{ r.model_alias }}</strong
            ><small class="cell-sub mono">{{ r.request_id }}</small>
          </td>
          <td>
            {{ r.received_at
            }}<small class="cell-sub">{{
              r.source_type === "external" ? "外部 API" : "私有推理"
            }}</small>
          </td>
          <td>
            <span
              class="badge"
              :class="r.status === 'succeeded' ? 'good' : 'warn'"
              >{{ statusLabel(r.status) }}</span
            >
          </td>
          <td data-label="Token">{{ display(r.usage.total_tokens) }}</td>
          <td data-label="计量">
            {{ r.metering_state === "complete" ? "计量完整" : "计量待确认"
            }}<small class="cell-sub">{{
              r.usage.missing_reason ?? "已返回用量"
            }}</small>
          </td>
          <td data-label="操作">
            <button @click="detail = r">请求详情</button>
          </td>
        </tr>
      </tbody>
    </table>
  </div>
  <div v-if="kind === 'summary'" class="summary-grid">
    <article v-for="(s, i) in summary" :key="i" class="panel">
      <div class="title-row">
        <h2>{{ s.model_alias }}</h2>
        <span class="badge">{{ s.currency ?? "币种未知" }}</span>
      </div>
      <p class="caption">
        {{ s.quota_date }} · 价格版本 {{ s.price_version ?? "未知" }}
      </p>
      <div class="review-grid">
        <div>
          <small>准入请求</small><strong>{{ s.admitted_total }}</strong>
        </div>
        <div>
          <small>已知 Token</small><strong>{{ s.total_tokens_known }}</strong>
        </div>
        <div>
          <small>缺失 Token 请求</small
          ><strong>{{ s.missing_token_requests }}</strong>
        </div>
        <div>
          <small>未知 Token 占用</small
          ><strong>{{ s.token_uncertainty_held }}</strong>
        </div>
      </div>
      <p>
        已知费用（原子单位）{{ display(s.cost_known_atomic) }} · 未知金额占用
        {{ display(s.money_uncertainty_held_atomic) }}
      </p>
      <p>
        成功 {{ s.succeeded }} · 进行中 {{ s.in_progress }} · 失败
        {{ s.failed }} · 取消 {{ s.cancelled }} · 超时 {{ s.timed_out }} · 断流
        {{ s.interrupted }}
      </p>
      <details>
        <summary>归属与覆盖详情</summary>
        <p>{{ s.source_type }} / {{ s.source_id }} · Key {{ s.key_id }}</p>
        <p>缺失费用请求 {{ s.missing_cost_requests }}</p>
      </details>
    </article>
  </div>
  <button v-if="cursor" :disabled="busy" @click="load(true)">加载更多</button>
  <p class="caption">
    不同来源、币种、价格版本分别呈现。当前分页不代表全站总量，已知部分用量不代表总量完整。
  </p>
  <PanelDialog v-if="detail" title="请求详情" drawer @close="detail = null">
    <span class="badge">{{ statusLabel(detail.status) }}</span>
    <h3>{{ detail.model_alias }}</h3>
    <code>{{ detail.request_id }}</code>
    <dl>
      <dt>接收时间</dt>
      <dd>{{ detail.received_at }}</dd>
      <dt>固定来源</dt>
      <dd>{{ detail.source_type }} / {{ detail.source_id }}</dd>
      <dt>Key ID</dt>
      <dd>{{ detail.key_id }}</dd>
      <dt>Token 输入</dt>
      <dd>{{ display(detail.usage.input_tokens) }}</dd>
      <dt>Token 输出</dt>
      <dd>{{ display(detail.usage.output_tokens) }}</dd>
      <dt>Token 总量</dt>
      <dd>{{ display(detail.usage.total_tokens) }}</dd>
      <dt>提交 / 计量</dt>
      <dd>{{ detail.submission_state }} / {{ detail.metering_state }}</dd>
      <dt>缺失原因</dt>
      <dd>{{ detail.usage.missing_reason ?? "未报告缺失" }}</dd>
      <dt>错误码</dt>
      <dd>{{ detail.error_code ?? "无" }}</dd>
      <dt>Token 预留 / 未知占用</dt>
      <dd>
        {{ display(detail.budget_accounting?.token?.reserved) }} /
        {{ display(detail.budget_accounting?.token?.unknown_held) }}
      </dd>
      <dt>金额预留 / 未知占用</dt>
      <dd>
        {{ display(detail.budget_accounting?.money?.reserved) }} /
        {{ display(detail.budget_accounting?.money?.unknown_held) }} 原子单位
      </dd>
      <dt>金额</dt>
      <dd>
        {{ display(detail.budget_accounting?.cost_actual_atomic) }} 原子单位 ·
        {{ detail.budget_accounting?.currency ?? "未知币种" }}
      </dd>
    </dl>
    <button
      @click="
        filter.key_id = detail.key_id;
        detail = null;
        load();
      "
    >
      查看此 Key 用量
    </button>
    <details class="technical-detail">
      <summary>预算、价格与活动修订快照</summary>
      <pre>{{
        JSON.stringify(
          {
            reservation_plan: detail.reservation_plan,
            budget_accounting: detail.budget_accounting,
            invocation_binding: detail.invocation_binding,
          },
          null,
          2,
        )
      }}</pre>
    </details>
  </PanelDialog>
</template>
