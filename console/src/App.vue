<script setup lang="ts">
import { onMounted, onBeforeUnmount, ref, defineAsyncComponent } from "vue";
import { api } from "./api/client";
import { explain } from "./ui";
import { loadDeployment } from "./deployment";
const ChatWorkspace = defineAsyncComponent(
  () => import("./pages/ChatWorkspace.vue"),
);
import Models from "./pages/Models.vue";
import Keys from "./pages/Keys.vue";
import Playground from "./pages/Playground.vue";
import Releases from "./pages/Releases.vue";
import Usage from "./pages/Usage.vue";
const tab = ref(location.hash.startsWith("#chat") ? "chat" : "models"),
  authenticated = ref(false),
  busy = ref(true),
  error = ref(""),
  username = ref(""),
  password = ref("");
const usageModel = ref(""),
  usageKey = ref(""),
  playModel = ref("");
function navigate(
  id: string,
  filter?: { key_id?: string; model_alias?: string },
) {
  usageKey.value = filter?.key_id ?? "";
  usageModel.value = filter?.model_alias ?? "";
  playModel.value = filter?.model_alias ?? "";
  tab.value = id;
}
const local =
  (import.meta.env.DEV || import.meta.env.MODE === "workbench") &&
  import.meta.env.VITE_LOCAL_CONTROL === "true";
const ar1Controlled =
  import.meta.env.DEV && import.meta.env.VITE_CHAT_AR1_CONTROLLED === "true";
const ar1Enabled = ref(
  import.meta.env.DEV && import.meta.env.VITE_CHAT_AR1_ENABLED === "true",
);
async function configureDeployment() {
  if (!import.meta.env.DEV)
    ar1Enabled.value = (await loadDeployment(api.fetcher)).chat.enabled;
}
const inferenceAvailable =
  !local ||
  (import.meta.env.DEV &&
    import.meta.env.VITE_LOCAL_INFERENCE_ENABLED === "true");
const demo =
  import.meta.env.DEV && import.meta.env.VITE_CONSOLE_FIXTURES === "true";
async function boot() {
  try {
    await configureDeployment();
    if (demo) {
      const { fixtureFetch } = await import("./fixtures");
      api.fetcher = fixtureFetch;
    }
    if (local || ar1Controlled) {
      const { enterLocalControl } = await import("./api/local-control");
      await enterLocalControl();
      tab.value = ar1Controlled ? "chat" : "models";
    } else await api.session();
    authenticated.value = true;
  } catch (e) {
    error.value = explain(e);
  } finally {
    busy.value = false;
  }
}
async function login() {
  busy.value = true;
  error.value = "";
  try {
    await configureDeployment();
    if (local || ar1Controlled) {
      const { enterLocalControl } = await import("./api/local-control");
      await enterLocalControl();
      tab.value = ar1Controlled ? "chat" : "models";
    } else
      await api.login({ username: username.value, password: password.value });
    authenticated.value = true;
  } catch (e) {
    error.value = explain(e);
  } finally {
    password.value = "";
    busy.value = false;
  }
}
async function logout() {
  busy.value = true;
  try {
    if (local || ar1Controlled) {
      const { leaveLocalControl } = await import("./api/local-control");
      await leaveLocalControl();
    } else await api.logout();
    authenticated.value = false;
    error.value = "";
  } catch (e) {
    error.value = explain(e);
  } finally {
    authenticated.value = false;
    api.csrf = "";
    password.value = "";
    busy.value = false;
  }
}
function expired() {
  authenticated.value = false;
  api.csrf = "";
  password.value = "";
  error.value = "管理会话已过期，请重新登录。";
}
onMounted(() => {
  window.addEventListener("maas-session-expired", expired);
  window.addEventListener("pagehide", expired);
  void boot();
});
onBeforeUnmount(() => {
  window.removeEventListener("maas-session-expired", expired);
  window.removeEventListener("pagehide", expired);
});
const nav = [
  ["chat", "Chat 工作台"],
  ["models", "模型目录"],
  ["keys", "平台 Key"],
  ["play", "在线试用"],
  ["releases", "模型发布"],
  ["usage", "请求与用量"],
];
</script>
<template>
  <div class="shell">
    <aside>
      <div class="brand">
        <span class="brand-mark">M</span>MaaS <small>工作台</small>
      </div>
      <p class="workspace-label">
        内部试点工作区<small>单管理员 · 模型服务平台</small>
      </p>
      <nav aria-label="主导航">
        <template
          v-for="group in [
            {
              label: 'BUILD / 开发',
              items: nav.filter(
                (x) =>
                  ['chat', 'models', 'play'].includes(x[0]!) &&
                  (!ar1Controlled || x[0] === 'chat'),
              ),
            },
            {
              label: 'OPERATE / 运营',
              items: nav.filter(
                (x) =>
                  !ar1Controlled && !['chat', 'models', 'play'].includes(x[0]!),
              ),
            },
          ]"
          :key="group.label"
        >
          <span class="nav-group">{{ group.label }}</span>
          <button
            v-for="[id, label] in group.items"
            :key="id"
            :class="{ active: tab === id }"
            :disabled="!authenticated"
            @click="navigate(id)"
          >
            <span>{{ label }}</span><span aria-hidden="true">↗</span>
          </button></template
        >
      </nav>
      <div class="sidebar-foot">
        <span class="dot"></span> 单管理员工作台
        <details>
          <summary>连接与数据说明</summary>
          <small>Go / Higress · 用量以服务端记录为准</small>
        </details>
      </div>
    </aside>
    <main>
      <header>
        <span>平台 / {{ nav.find((x) => x[0] === tab)?.[1] }}</span
        ><button
          v-if="authenticated"
          class="quiet"
          :disabled="busy"
          @click="logout"
        >
          退出会话
        </button>
      </header>
      <div v-if="demo" class="notice">
        开发测试夹具 · 所有模型、Key、发布与用量均为模拟数据，未连接真实模型。
      </div>
      <div v-if="local" class="notice">
        本地工作台 · 停止服务后清理本次临时数据；模型推理尚未接入。
      </div>
      <p v-if="error" role="alert" class="error">{{ error }}</p>
      <section v-if="!authenticated" class="login panel">
        <p class="eyebrow">ADMIN CONSOLE</p>
        <h1>登录管理工作台</h1>
        <p class="muted">使用管理员会话管理模型和预算。</p>
        <button
          v-if="local || ar1Controlled"
          class="primary"
          :disabled="busy"
          @click="login"
        >
          连接本地 Go 会话
        </button>
        <form v-else @submit.prevent="login">
          <label
            >管理员账号<input
              v-model="username"
              autocomplete="username"
              required
              maxlength="64" /></label
          ><label
            >密码<input
              v-model="password"
              type="password"
              autocomplete="current-password"
              required
              maxlength="1024" /></label
          ><button class="primary" :disabled="busy">
            {{ busy ? "正在验证…" : "登录" }}
          </button>
        </form>
      </section>
      <template v-else
        ><ChatWorkspace
          v-if="tab === 'chat'"
          :development="demo"
          :http="ar1Enabled && !demo"
          :controlled="ar1Controlled" /><Models
          v-else-if="tab === 'models'"
          @navigate="navigate" /><Keys
          v-else-if="tab === 'keys'"
          @navigate="navigate" /><Playground
          v-else-if="tab === 'play'"
          :initial-model="playModel"
          :inference-available="inferenceAvailable"
          @navigate="navigate" /><Releases
          v-else-if="tab === 'releases'"
          :initial-model="playModel" /><Usage
          v-else
          :key-filter="usageKey"
          :model-filter="usageModel"
          @navigate="navigate"
      /></template>
      <footer>管理会话与消费 Key 分离 · 用量以服务端耐久记录为准</footer>
    </main>
  </div>
</template>
