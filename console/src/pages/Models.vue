<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { api, ADMIN } from "../api/client";
import type { S } from "../api/contracts";
import { usePage, statusLabel } from "../ui";
import PanelDialog from "../components/PanelDialog.vue";
const emit = defineEmits<{
  navigate: [tab: string, filter?: { model_alias: string }];
}>();
const { rows, busy, error, refresh } = usePage(() =>
  api.json<S["AdminModelList"]>(ADMIN + "/models", "AdminModelList"),
);
const search = ref(""),
  source = ref("all"),
  detail = ref<S["AdminModel"] | null>(null);
const filtered = computed(() =>
  rows.value.filter(
    (m) =>
      (source.value === "all" || m.source_type === source.value) &&
      (m.id + " " + m.display_name)
        .toLowerCase()
        .includes(search.value.trim().toLowerCase()),
  ),
);
onMounted(() => refresh());
</script>
<template>
  <div class="title-row">
    <div>
      <p class="eyebrow">MODEL CATALOG</p>
      <h1>模型目录</h1>
      <p class="muted">发现已接入模型，确认能力与状态，再开始调用。</p>
    </div>
    <button class="primary" @click="emit('navigate', 'releases')">
      ＋ 接入模型
    </button>
  </div>
  <div class="info-strip">
    模型来源固定 · 可调用状态由服务端确认。<button
      class="quiet"
      @click="emit('navigate', 'releases')"
    >
      管理发布 →
    </button>
  </div>
  <div class="toolbar">
    <label class="search-field"
      ><span class="sr-only">搜索模型</span
      ><input v-model="search" type="search" placeholder="搜索模型名称或别名"
    /></label>
    <div class="segmented" aria-label="模型来源">
      <button
        v-for="[value, label] in [
          ['all', '全部'],
          ['external', '外部 API'],
          ['internal', '私有推理'],
        ]"
        :key="value"
        :aria-pressed="source === value"
        :class="{ active: source === value }"
        @click="source = value"
      >
        {{ label }}
      </button>
    </div>
    <button :disabled="busy" @click="refresh()">刷新目录</button>
  </div>
  <p class="caption">
    筛选当前已加载的 {{ rows.length }} 个模型 · 匹配 {{ filtered.length }} 个
  </p>
  <p v-if="busy" role="status" class="empty">正在加载模型…</p>
  <p v-if="error" role="alert" class="error">
    {{ error }} <button @click="refresh()">重新查询</button>
  </p>
  <div v-if="!busy && !error && !filtered.length" class="empty">
    <h2>{{ rows.length ? "没有匹配的模型" : "尚无模型" }}</h2>
    <p>调整搜索条件，或先提交获准的模型配置。</p>
    <button
      @click="
        search = '';
        source = 'all';
      "
    >
      清除筛选</button
    ><button @click="emit('navigate', 'releases')">接入并发布模型</button>
  </div>
  <div v-if="!busy && !error" class="card-grid">
    <article v-for="m in filtered" :key="m.id" class="panel model-card">
      <div class="title-row">
        <span class="model-icon">{{ m.display_name.slice(0, 1) }}</span
        ><span class="badge" :class="m.callable ? 'good' : 'warn'">{{
          m.callable ? "可调用" : "未开放"
        }}</span>
      </div>
      <h2>{{ m.display_name }}</h2>
      <p class="model-alias">{{ m.id }}</p>
      <div class="chips">
        <span class="chip">{{
          m.source_type === "external" ? "外部 API" : "私有推理"
        }}</span
        ><span class="chip">{{
          m.capabilities.streaming ? "支持流式" : "流式不可用"
        }}</span
        ><span
          v-for="protocol in m.capabilities.protocols"
          :key="protocol"
          class="chip"
          >{{ protocol === "chat_completions" ? "文本对话" : protocol }}</span
        >
      </div>
      <div class="model-facts">
        <div>
          <small>用量证据</small
          ><strong>{{
            m.capabilities.usage_available === "verified"
              ? "已核验"
              : m.capabilities.usage_available === "unavailable"
                ? "不可获取"
                : "待确认"
          }}</strong>
        </div>
        <div>
          <small>硬预算能力</small
          ><strong>{{ statusLabel(m.capabilities.hard_budget_status) }}</strong>
        </div>
        <div>
          <small>当前活动版本</small
          ><strong>{{ m.release_binding ? "已有活动绑定" : "待生效" }}</strong>
        </div>
        <div>
          <small>最大输出</small
          ><strong
            >{{ m.capabilities.verified_max_output_tokens }} Token</strong
          >
        </div>
      </div>
      <p v-if="!m.callable" class="caption">
        {{
          m.capabilities.budget_unavailable_reason ||
          "发布尚未开放，请到发布详情核对依赖与验证。"
        }}
      </p>
      <div class="actions">
        <button
          :disabled="!m.callable"
          @click="emit('navigate', 'play', { model_alias: m.id })"
        >
          在线试用</button
        ><button @click="detail = m">查看详情</button>
      </div>
    </article>
  </div>
  <section class="onboarding">
    <h2>开始使用模型服务</h2>
    <div class="card-grid">
      <button class="panel" @click="emit('navigate', 'releases')">
        <b>01　接入并发布模型</b
        ><span>选择来源与获准配置，跟踪发布进度 →</span></button
      ><button class="panel" @click="emit('navigate', 'keys')">
        <b>02　创建调用凭证</b
        ><span>显式配置预算，完整 Key 仅显示一次 →</span></button
      ><button class="panel" @click="emit('navigate', 'usage')">
        <b>03　调用后查看记录</b><span>按原请求追踪结果与实际用量 →</span>
      </button>
    </div>
  </section>
  <PanelDialog
    v-if="detail"
    :title="detail.display_name"
    drawer
    @close="detail = null"
  >
    <span class="badge" :class="detail.callable ? 'good' : 'warn'">{{
      detail.callable ? "可调用" : "未开放"
    }}</span>
    <dl>
      <dt>模型别名</dt>
      <dd>{{ detail.id }}</dd>
      <dt>来源</dt>
      <dd>{{ detail.source_type }} / {{ detail.source_id }}</dd>
      <dt>健康检查</dt>
      <dd>
        {{ statusLabel(detail.check_state) }} ·
        {{ detail.checked_at ?? "尚无检查时间" }}
      </dd>
      <dt>目录修订</dt>
      <dd>{{ detail.config_revision }}</dd>
      <dt>活动修订</dt>
      <dd>{{ detail.release_binding?.release_revision ?? "尚无活动绑定" }}</dd>
      <dt>预算说明</dt>
      <dd>
        {{
          detail.capabilities.budget_unavailable_reason ?? "以实际准入结果为准"
        }}
      </dd>
    </dl>
    <p class="notice">
      健康检查与预算准入分别判断，目录展示不保证下一次请求获准。
    </p>
    <div class="actions">
      <button
        :disabled="!detail.callable"
        class="primary"
        @click="emit('navigate', 'play', { model_alias: detail.id })"
      >
        在线试用</button
      ><button
        @click="emit('navigate', 'releases', { model_alias: detail.id })"
      >
        查看发布
      </button>
    </div>
  </PanelDialog>
</template>
