<script setup lang="ts">
import { computed, ref } from "vue";
import { validate, type S } from "../api/contracts";
const props = defineProps<{
  modelValue: string;
  busy?: boolean;
  existing?: boolean;
}>();
const emit = defineEmits<{ "update:modelValue": [value: string] }>();
const step = ref(0);
const steps = ["基本信息", "模型来源", "批准引用", "生命周期", "确认提交"];
const draft = computed(() => {
  try {
    return JSON.parse(props.modelValue) as Record<string, any>;
  } catch {
    return null;
  }
});
const schemaError = computed(() => {
  try {
    validate<S["ReleaseReleaseInput"]>(
      "ReleaseReleaseInput",
      JSON.parse(props.modelValue),
    );
    return "";
  } catch {
    return "尚未通过完整 Schema 校验，请补齐获准引用与参数；高级 JSON 可查看和编辑全部字段。";
  }
});
const labels: Record<string, string> = {
  name: "名称",
  namespace: "命名空间",
  modelAlias: "模型别名",
  type: "来源类型",
  provider: "供应商",
  upstreamModel: "上游模型",
  protocol: "推理协议",
  key: "Secret 键名",
  revision: "不可变版本",
  desiredState: "期望状态",
  strategy: "更新策略",
  drainTimeoutSeconds: "排空超时（秒）",
  progressDeadlineSeconds: "进度截止（秒）",
  retainedRevisions: "保留修订数",
  retainUserData: "保留用户数据",
  engine: "推理引擎",
  workload: "工作负载",
  pvcName: "权重 PVC",
  path: "权重相对路径",
  sha256: "权重 SHA256",
  modelRevision: "权重版本",
  image: "镜像 digest",
  groups: "完整组数",
  podsPerGroup: "每组 Pod 数",
  gpusPerPod: "每 Pod GPU 数",
  gpuResourceName: "GPU 资源名",
  cpuPerPod: "每 Pod CPU",
  memoryPerPod: "每 Pod 内存",
  tensorParallelSize: "张量并行",
  pipelineParallelSize: "流水线并行",
  startupTimeoutSeconds: "启动超时（秒）",
};
const groupNames: Record<string, string> = {
  endpointRef: "批准端点",
  credentialSecretRef: "凭证 Secret 引用",
  gatewayRef: "网关",
  capabilityProfileRef: "能力 profile",
  pricePolicyRef: "价格策略",
  intakePolicyRef: "准入策略",
  runtimeProfileRef: "运行时 profile",
  placementProfileRef: "放置 profile",
};
type Field = { path: string; label: string; value: string | number | boolean };
function flatten(obj: Record<string, any>, base: string): Field[] {
  return Object.entries(obj).flatMap(([k, v]) => {
    const path = base ? base + "." + k : k;
    if (v && typeof v === "object") return flatten(v, path);
    const parent = path.split(".").at(-2) ?? "";
    return [
      {
        path,
        label:
          (groupNames[parent] ? groupNames[parent] + " · " : "") +
          (labels[k] ?? k),
        value: v,
      },
    ];
  });
}
const fields = computed(() => {
  const d = draft.value;
  if (!d) return [];
  if (step.value === 0)
    return [
      ...flatten(d.metadata ?? {}, "metadata"),
      {
        path: "spec.modelAlias",
        label: "模型别名",
        value: d.spec?.modelAlias ?? "",
      },
    ];
  if (step.value === 1) return flatten(d.spec?.source ?? {}, "spec.source");
  if (step.value === 2)
    return [
      ...flatten(d.spec?.gatewayRef ?? {}, "spec.gatewayRef"),
      ...flatten(d.spec?.businessRefs ?? {}, "spec.businessRefs"),
    ];
  if (step.value === 3)
    return flatten(d.spec?.lifecycle ?? {}, "spec.lifecycle");
  return [];
});
function update(field: Field, event: Event) {
  const input = event.target as HTMLInputElement;
  const value =
    typeof field.value === "boolean"
      ? input.checked
      : typeof field.value === "number"
        ? input.value === ""
          ? 0
          : Number(input.value)
        : input.value;
  const d = JSON.parse(props.modelValue);
  const parts = field.path.split(".");
  let target = d;
  for (const part of parts.slice(0, -1)) target = target[part];
  target[parts.at(-1)!] = value;
  emit("update:modelValue", JSON.stringify(d, null, 2));
}
function fixed(f: Field) {
  return (
    [
      "type",
      "protocol",
      "engine",
      "workload",
      "gpuResourceName",
      "pipelineParallelSize",
      "retainUserData",
    ].includes(f.path.split(".").at(-1)!) ||
    (props.existing && f.path.startsWith("metadata."))
  );
}
</script>
<template>
  <div class="steps" aria-label="发布配置步骤">
    <button
      v-for="(label, i) in steps"
      :key="label"
      type="button"
      :class="{ active: step === i }"
      :aria-current="step === i ? 'step' : undefined"
      @click="step = i"
    >
      {{ i + 1 }} {{ label }}
    </button>
  </div>
  <p class="caption">
    所有配置引用必须经过批准。这里只填写 Secret 名称与键名，禁止填写凭证正文。
  </p>
  <div v-if="draft" class="form-grid release-fields">
    <label v-for="f in fields" :key="f.path"
      >{{ f.label }}
      <select
        v-if="f.path.endsWith('desiredState')"
        :value="f.value"
        :disabled="busy"
        @change="update(f, $event)"
      >
        <option>Published</option>
        <option>Paused</option>
      </select>
      <select
        v-else-if="f.path.endsWith('strategy')"
        :value="f.value"
        :disabled="busy"
        @change="update(f, $event)"
      >
        <option>BlueGreen</option>
        <option>Recreate</option>
      </select>
      <input
        v-else-if="typeof f.value === 'boolean'"
        type="checkbox"
        :checked="f.value"
        :disabled="busy || fixed(f)"
        @change="update(f, $event)"
      />
      <input
        v-else
        :value="f.value"
        :type="typeof f.value === 'number' ? 'number' : 'text'"
        :disabled="busy || fixed(f)"
        :data-field="f.path"
        @input="update(f, $event)"
      />
    </label>
  </div>
  <div v-if="step === 4 && draft" class="review-grid">
    <div>
      <small>发布模型</small
      ><strong>{{ draft.spec?.modelAlias || "尚未填写" }}</strong>
    </div>
    <div>
      <small>来源</small><strong>{{ draft.spec?.source?.type }}</strong>
    </div>
    <div>
      <small>配置归属</small
      ><strong
        >{{ draft.metadata?.namespace }} / {{ draft.metadata?.name }}</strong
      >
    </div>
    <div><small>提交后</small><strong>仅代表受理，等待网关与验证</strong></div>
  </div>
  <p v-if="schemaError" class="notice" role="status">{{ schemaError }}</p>
  <p v-else class="notice">
    完整结构校验已通过；引用授权、预算及实际发布仍由服务端核验。
  </p>
  <details class="advanced-editor">
    <summary>高级 JSON · 全部 Schema 字段</summary>
    <label
      >ModelRelease JSON<textarea
        :value="modelValue"
        class="code-editor"
        rows="20"
        spellcheck="false"
        :disabled="busy"
        @input="
          emit(
            'update:modelValue',
            ($event.target as HTMLTextAreaElement).value,
          )
        "
      ></textarea>
    </label>
  </details>
  <div class="dialog-actions">
    <button v-if="step > 0" type="button" @click="step--">上一步</button
    ><button v-if="step < 4" type="button" class="primary" @click="step++">
      下一步</button
    ><button v-else class="primary" :disabled="busy || !!schemaError">
      校验并提交配置
    </button>
  </div>
</template>
