<script setup lang="ts">
import { onMounted, onBeforeUnmount, ref, shallowRef } from "vue";
import { api, ADMIN } from "../api/client";
import { validate, type S, type D } from "../api/contracts";
import {
  revisions,
  releasePath,
  canRollback,
  assertReleaseAccepted,
} from "../api/recovery";
import { callableLabel } from "../domain";
import { usePage, explain, uncertain } from "../ui";
const { rows, busy, error, cursor, refresh } = usePage((cursor) =>
  api.json<S["ReleaseList"]>(
    ADMIN +
      "/model-releases" +
      (cursor ? "?cursor=" + encodeURIComponent(cursor) : ""),
    "ReleaseList",
  ),
);
const editBaseline = shallowRef<S["ReleaseModelRelease"] | null>(null);
const selected = shallowRef<S["ReleaseModelRelease"] | null>(null),
  history = shallowRef<D["ReleaseRevisionPage"] | null>(null),
  operation = shallowRef<S["ReleaseOperation"] | null>(null),
  editor = ref(""),
  editing = ref(false),
  message = ref(""),
  writing = ref(false),
  unknown = ref(false),
  reading = ref(false),
  confirmDelete = ref(false),
  operationReading = ref(false),
  needsRead = ref(false);
let selectionEpoch = 0,
  operationEpoch = 0,
  alive = true;
function invalidateOperationRead() {
  operationEpoch++;
  operationReading.value = false;
}
function beginEditing() {
  if (!selected.value || writing.value || unknown.value || needsRead.value)
    return;
  editBaseline.value = selected.value;
  editor.value = JSON.stringify(inputOf(selected.value), null, 2);
  editing.value = true;
}
const profile = () => ({ name: "", revision: "" });
function template(source: "ExternalAPI" | "SelfHosted") {
  invalidateOperationRead();
  operation.value = null;
  editBaseline.value = null;
  needsRead.value = false;
  selected.value = null;
  history.value = null;
  reading.value = false;
  editing.value = true;
  selectionEpoch++;
  const sourceSpec =
    source === "ExternalAPI"
      ? {
          type: source,
          externalAPI: {
            provider: "DeepSeek",
            endpointRef: profile(),
            upstreamModel: "",
            protocol: "OpenAIChatCompletions",
            credentialSecretRef: { name: "", key: "" },
          },
        }
      : {
          type: source,
          selfHosted: {
            engine: "SGLang",
            workload: "LeaderWorkerSet",
            weights: { pvcName: "", path: "", sha256: "", modelRevision: "" },
            runtimeProfileRef: profile(),
            placementProfileRef: profile(),
            image: "",
            groups: 0,
            podsPerGroup: 0,
            gpusPerPod: 0,
            gpuResourceName: "nvidia.com/gpu",
            cpuPerPod: "",
            memoryPerPod: "",
            tensorParallelSize: 0,
            pipelineParallelSize: 1,
            startupTimeoutSeconds: 0,
          },
        };
  editor.value = JSON.stringify(
    {
      apiVersion: "serving.maas.example/v1alpha1",
      kind: "ModelRelease",
      metadata: { namespace: "", name: "" },
      spec: {
        modelAlias: "",
        source: sourceSpec,
        gatewayRef: profile(),
        businessRefs: {
          capabilityProfileRef: profile(),
          pricePolicyRef: profile(),
          intakePolicyRef: profile(),
        },
        lifecycle: {
          desiredState: "Published",
          strategy: "BlueGreen",
          drainTimeoutSeconds: 0,
          progressDeadlineSeconds: 0,
          retainedRevisions: 0,
          retainUserData: true,
        },
      },
    },
    null,
    2,
  );
}
function inputOf(r: S["ReleaseModelRelease"]): S["ReleaseReleaseInput"] {
  return {
    apiVersion: r.apiVersion,
    kind: r.kind,
    metadata: { namespace: r.metadata.namespace, name: r.metadata.name },
    spec: structuredClone(r.spec),
  };
}
async function select(r: S["ReleaseModelRelease"]) {
  invalidateOperationRead();
  const mine = ++selectionEpoch;
  editBaseline.value = null;
  editor.value = "";
  reading.value = true;
  message.value = "";
  history.value = null;
  selected.value = null;
  editing.value = false;
  confirmDelete.value = false;
  try {
    const current = await api.json<S["ReleaseModelRelease"]>(
      releasePath(r),
      "ReleaseModelRelease",
    );
    if (mine !== selectionEpoch) return;
    if (r.metadata.uid && current.metadata.uid !== r.metadata.uid)
      throw new Error("同名 CR 已被替换，请重新加载列表。");
    selected.value = current;
    needsRead.value = false;
    editBaseline.value = current;
    editor.value = JSON.stringify(inputOf(current), null, 2);
  } catch (e) {
    if (mine === selectionEpoch) {
      message.value = explain(e);
      selected.value = null;
    }
  } finally {
    if (mine === selectionEpoch) reading.value = false;
  }
}
async function loadHistory(more = false) {
  const r = selected.value;
  if (!r) return;
  const mine = selectionEpoch;
  reading.value = true;
  try {
    const p = await revisions(
      api,
      r,
      more ? (history.value?.next_cursor ?? undefined) : undefined,
    );
    if (mine !== selectionEpoch) return;
    history.value =
      more && history.value
        ? { ...p, data: [...history.value.data, ...p.data] }
        : p;
  } catch (e) {
    if (mine === selectionEpoch) {
      message.value = "修订查询不可用：" + explain(e);
      history.value = null;
    }
  } finally {
    if (mine === selectionEpoch) reading.value = false;
  }
}
async function mutate(
  action: "save" | "pause" | "resume" | "delete" | "rollback",
  revision?: D["ReleaseRetainedRevision"],
) {
  if (!alive || writing.value || unknown.value) return;
  invalidateOperationRead();
  const mine = operationEpoch;
  writing.value = true;
  message.value = "";
  const r = selected.value;
  try {
    if (needsRead.value)
      throw new Error("请先重读当前 CR，核对最新配置和版本。");
    if (
      action === "save" &&
      r &&
      (!editBaseline.value ||
        editBaseline.value.metadata.uid !== r.metadata.uid ||
        editBaseline.value.metadata.resourceVersion !==
          r.metadata.resourceVersion)
    )
      throw new Error("编辑基线已变化，请重读当前 CR 后重新编辑。");
    let expected: {
      namespace: string;
      name: string;
      uid?: string;
      action: S["ReleaseOperation"]["action"];
    };
    let path = ADMIN + "/model-releases",
      method = "POST",
      body: unknown,
      headers: Record<string, string> = {};
    if (r) {
      if (!r.metadata.resourceVersion || !r.metadata.uid)
        throw new Error("缺少服务端 resourceVersion，请刷新。");
      path = releasePath(r);
      headers["If-Match"] = '"' + r.metadata.resourceVersion + '"';
      method = "PUT";
    }
    if (action === "delete") {
      if (!r) return;
      method = "DELETE";
    } else if (action === "rollback") {
      if (
        !r ||
        !revision ||
        !history.value ||
        !canRollback(history.value, revision, r)
      )
        throw new Error("修订已过期、受阻或归属不一致，请重新读取。");
      path += "/rollback";
      method = "POST";
      body = {
        target_revision: revision.revision,
        expected_cr_uid: r.metadata.uid,
      };
    } else {
      const input =
        action === "save"
          ? validate<S["ReleaseReleaseInput"]>(
              "ReleaseReleaseInput",
              JSON.parse(editor.value),
            )
          : inputOf(r!);
      if (
        r &&
        (input.metadata.name !== r.metadata.name ||
          input.metadata.namespace !== r.metadata.namespace)
      )
        throw new Error("更新不能更改 CR 名称或命名空间。");
      if (action === "pause" || action === "resume")
        input.spec.lifecycle.desiredState =
          action === "pause" ? "Paused" : "Published";
      validate("ReleaseReleaseInput", input);
      body = input;
    }
    const target = r?.metadata ?? (body as S["ReleaseReleaseInput"]).metadata;
    expected = {
      namespace: target.namespace,
      name: target.name,
      ...(r ? { uid: r.metadata.uid } : {}),
      action:
        action === "delete"
          ? "Delete"
          : action === "rollback"
            ? "Rollback"
            : r
              ? "Update"
              : "Create",
    };
    operation.value = null;
    const accepted = await api.json<S["ReleaseAccepted"]>(
      path,
      "ReleaseAccepted",
      {
        method,
        headers,
        ...(body === undefined ? {} : { body: JSON.stringify(body) }),
      },
    );
    if (!alive || mine !== operationEpoch) return;
    assertReleaseAccepted(accepted, expected);
    operation.value = accepted.operation;
    message.value = "配置已提交（202）；等待原操作与活动发布确认。";
    editing.value = false;
    confirmDelete.value = false;
    selectionEpoch++;
    reading.value = false;
    history.value = null;
    needsRead.value = !accepted.resource;
    editBaseline.value = accepted.resource ?? null;
    editor.value = accepted.resource
      ? JSON.stringify(inputOf(accepted.resource), null, 2)
      : "";
    if (accepted.resource) selected.value = accepted.resource;
    await refresh();
  } catch (e) {
    if (!alive || mine !== operationEpoch) return;
    message.value = explain(e);
    unknown.value = uncertain(e);
  } finally {
    if (alive && mine === operationEpoch) writing.value = false;
  }
}
async function recoverOperation() {
  if (!alive || !operation.value || operationReading.value || writing.value)
    return;
  const original = operation.value,
    mine = ++operationEpoch;
  const current = () =>
    alive && mine === operationEpoch && operation.value?.id === original.id;
  operationReading.value = true;
  try {
    const op = await api.json<S["ReleaseOperation"]>(
      ADMIN + "/release-operations/" + original.id,
      "ReleaseOperation",
    );
    if (!current()) return;
    if (
      op.id !== original.id ||
      op.namespace !== original.namespace ||
      op.name !== original.name ||
      op.cr_uid !== original.cr_uid ||
      op.action !== original.action
    )
      throw new Error("操作归属不一致，保留原操作供核对。");
    operation.value = op;
  } catch (e) {
    if (current()) message.value = explain(e);
  } finally {
    if (current()) operationReading.value = false;
  }
}
onMounted(() => refresh());
onBeforeUnmount(() => {
  alive = false;
  selectionEpoch++;
  operationEpoch++;
  editBaseline.value = null;
  editor.value = "";
});
</script>
<template>
  <div class="title-row">
    <div>
      <p class="eyebrow">RELEASE CONTROL</p>
      <h1>模型发布</h1>
      <p class="muted">提交期望配置，独立核对活动版本和可调用状态。</p>
    </div>
    <button :disabled="busy" @click="refresh()">刷新发布</button>
  </div>
  <p v-if="message" role="status" :class="unknown ? 'error' : 'notice'">
    {{ message }}
  </p>
  <p v-if="error" role="alert" class="error">{{ error }}</p>
  <div class="actions">
    <button :disabled="writing || unknown" @click="template('ExternalAPI')">
      新建外部 API CR</button
    ><button :disabled="writing || unknown" @click="template('SelfHosted')">
      新建私有推理 CR
    </button>
  </div>
  <p v-if="busy" role="status">正在读取发布…</p>
  <p v-if="!busy && !rows.length && !error" class="empty">暂无模型发布。</p>
  <div class="card-grid">
    <button
      v-for="r in rows"
      :key="r.metadata.uid ?? r.metadata.name"
      class="panel release-card"
      :disabled="reading || writing"
      @click="select(r)"
    >
      <strong>{{ r.spec.modelAlias }}</strong
      ><span>{{ r.spec.source.type }} · {{ r.status?.phase ?? "未观测" }}</span
      ><span class="badge">{{ callableLabel(r) }}</span
      ><small>{{ r.metadata.namespace }} / {{ r.metadata.name }}</small>
    </button>
  </div>
  <button v-if="cursor" :disabled="busy" @click="refresh(true)">
    加载更多发布
  </button>
  <section v-if="selected" class="panel">
    <div class="title-row">
      <h2>{{ selected.spec.modelAlias }}</h2>
      <button :disabled="reading || writing" @click="select(selected)">
        重读当前 CR
      </button>
    </div>
    <dl>
      <dt>已提交 generation</dt>
      <dd>{{ selected.metadata.generation ?? "未知" }}</dd>
      <dt>已观测 generation</dt>
      <dd>{{ selected.status?.observedGeneration ?? "未知" }}</dd>
      <dt>活动 generation</dt>
      <dd>{{ selected.status?.activeGeneration ?? "未知" }}</dd>
      <dt>期望修订</dt>
      <dd class="mono">{{ selected.status?.desiredRevision ?? "未知" }}</dd>
      <dt>活动修订</dt>
      <dd class="mono">{{ selected.status?.activeRevision ?? "未知" }}</dd>
      <dt>可调用</dt>
      <dd>{{ callableLabel(selected) }}</dd>
    </dl>
    <div class="table-scroll">
      <table>
        <thead>
          <tr>
            <th>条件</th>
            <th>状态</th>
            <th>原因 / 信息</th>
            <th>观测代数</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="c in selected.status?.conditions" :key="c.type">
            <td>{{ c.type }}</td>
            <td>{{ c.status }}</td>
            <td>{{ c.reason }} · {{ c.message }}</td>
            <td>{{ c.observedGeneration }}</td>
          </tr>
        </tbody>
      </table>
    </div>
    <p v-if="!selected.status" class="notice">
      尚无状态观测；配置存在不代表已生效。
    </p>
    <div class="actions">
      <button :disabled="writing || unknown" @click="beginEditing">
        编辑配置</button
      ><button
        :disabled="writing || unknown"
        @click="
          mutate(
            selected.spec.lifecycle.desiredState === 'Paused'
              ? 'resume'
              : 'pause',
          )
        "
      >
        {{
          selected.spec.lifecycle.desiredState === "Paused"
            ? "恢复发布"
            : "暂停发布"
        }}</button
      ><button :disabled="reading || writing" @click="loadHistory()">
        读取保留修订</button
      ><button
        class="danger"
        :disabled="writing || unknown"
        @click="confirmDelete = true"
      >
        下线并清理
      </button>
    </div>
    <div v-if="confirmDelete" class="notice">
      <p>
        确认关闭新准入并排空清理
        {{ selected.metadata.name }}？最终清理由服务端状态确认。
      </p>
      <button class="danger" :disabled="writing" @click="mutate('delete')">
        确认下线</button
      ><button @click="confirmDelete = false">取消</button>
    </div>
    <section v-if="history">
      <h3>保留修订 · {{ history.resource_state }}</h3>
      <p v-if="!history.data.length">无可见保留修订。</p>
      <article v-for="row in history.data" :key="row.revision" class="revision">
        <code>{{ row.revision }}</code>
        <p>
          {{ row.source_type }} · generation {{ row.generation }} ·
          {{ row.snapshot_state }} · {{ row.rollback_eligibility.state }}
        </p>
        <p>{{ row.rollback_eligibility.reason_codes.join(" / ") }}</p>
        <button
          :disabled="writing || unknown || !canRollback(history, row, selected)"
          @click="mutate('rollback', row)"
        >
          回滚到此修订
        </button>
      </article>
      <button
        v-if="history.next_cursor"
        :disabled="reading"
        @click="loadHistory(true)"
      >
        更多修订
      </button>
    </section>
  </section>
  <form v-if="editing" class="panel" @submit.prevent="mutate('save')">
    <h2>{{ selected ? "更新 CR" : "提交新 CR" }}</h2>
    <p class="muted">
      填入经过批准的引用与参数。模板空值和 0 占位必须补齐；Secret 只接受名称/key
      引用，禁止录入凭证正文。
    </p>
    <label
      >ModelRelease JSON<textarea
        v-model="editor"
        class="code-editor"
        rows="22"
        spellcheck="false"
        required
        :disabled="writing || unknown"
      ></textarea></label
    ><button class="primary" :disabled="writing || unknown">
      校验并提交配置
    </button>
  </form>
  <section v-if="operation" class="panel">
    <h2>原操作查询</h2>
    <code>{{ operation.id }}</code>
    <p>
      {{ operation.namespace }} / {{ operation.name }} · generation
      {{ operation.requested_generation ?? "未知" }}
    </p>
    <p>
      {{ operation.action }} · {{ operation.state }} · {{ operation.reason }} ·
      {{ operation.message }}
    </p>
    <button :disabled="operationReading || writing" @click="recoverOperation">
      查询原操作
    </button>
  </section>
  <p v-if="needsRead" class="notice">
    当前 ACK 未包含配置快照，请重读当前 CR 后再编辑或提交。
  </p>
  <p v-if="unknown" class="error">
    写入结果未知。当前 CR 仅供人工核对，不能证明原操作成功；如已取得原
    operation.id 可继续查询，禁止自动重放。
  </p>
  <p class="muted">
    保留修订查询采用 v0.4.2 草案适配。202
    仅表示受理；候选失败时旧活动版本可能仍可调用。
  </p>
</template>
