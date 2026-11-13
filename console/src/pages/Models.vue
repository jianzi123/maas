<script setup lang="ts">
import { onMounted } from "vue";
import { api, ADMIN } from "../api/client";
import type { S } from "../api/contracts";
import { usePage } from "../ui";
const emit = defineEmits<{
  navigate: [tab: string, filter?: { model_alias: string }];
}>();
const { rows, busy, error, refresh } = usePage(() =>
  api.json<S["AdminModelList"]>(ADMIN + "/models", "AdminModelList"),
);
onMounted(() => refresh());
</script>
<template>
  <div class="title-row">
    <div>
      <p class="eyebrow">MODEL CATALOG</p>
      <h1>模型目录</h1>
      <p class="muted">每个模型固定来源，查看实际可调用状态。</p>
    </div>
    <button :disabled="busy" @click="refresh()">刷新目录</button>
  </div>
  <p v-if="busy" role="status">正在加载模型…</p>
  <p v-if="error" role="alert" class="error">{{ error }}</p>
  <div v-if="!busy && !error && !rows.length" class="empty">
    尚无模型。请先提交获准发布配置。
  </div>
  <div class="card-grid">
    <article v-for="m in rows" :key="m.id" class="panel model-card">
      <div class="title-row">
        <span class="model-icon">◈</span
        ><span class="badge" :class="m.callable ? 'good' : 'warn'">{{
          m.callable ? "可调用" : "未开放"
        }}</span>
      </div>
      <h2>{{ m.display_name }}</h2>
      <code>{{ m.id }}</code>
      <dl>
        <dt>来源</dt>
        <dd>
          {{ m.source_type === "external" ? "外部 API" : "内网推理" }} ·
          {{ m.source_id }}
        </dd>
        <dt>健康检查</dt>
        <dd>{{ m.check_state }} / {{ m.checked_at ?? "尚无检查时间" }}</dd>
        <dt>硬预算能力</dt>
        <dd>
          {{ m.capabilities.hard_budget_status
          }}<small>{{ m.capabilities.budget_unavailable_reason }}</small>
        </dd>
        <dt>Token 用量</dt>
        <dd>
          {{
            m.capabilities.usage_available === "verified"
              ? "上游可获取"
              : "未知 / 不可获取"
          }}
        </dd>
        <dt>目录绑定修订</dt>
        <dd class="mono">
          {{ m.release_binding?.release_revision ?? "尚无活动绑定" }}
        </dd>
      </dl>
      <div class="actions">
        <button @click="emit('navigate', 'play', { model_alias: m.id })">
          在线试用</button
        ><button @click="emit('navigate', 'releases')">查看发布</button>
      </div>
    </article>
  </div>
</template>
