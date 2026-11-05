<script setup lang="ts">
import { onMounted, onBeforeUnmount, ref } from "vue";
import { api } from "./api/client";
import { explain } from "./ui";
import Models from "./pages/Models.vue";
import Keys from "./pages/Keys.vue";
import Playground from "./pages/Playground.vue";
import Releases from "./pages/Releases.vue";
import Usage from "./pages/Usage.vue";
const tab = ref("models"),
  authenticated = ref(false),
  busy = ref(true),
  error = ref(""),
  username = ref(""),
  password = ref("");
const demo =
  import.meta.env.DEV && import.meta.env.VITE_CONSOLE_FIXTURES === "true";
async function boot() {
  try {
    if (demo) {
      const { fixtureFetch } = await import("./fixtures");
      api.fetcher = fixtureFetch;
    }
    await api.session();
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
    await api.logout();
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
      <p class="eyebrow">MODEL OPERATIONS</p>
      <nav aria-label="主导航">
        <button
          v-for="[id, label] in nav"
          :key="id"
          :class="{ active: tab === id }"
          :disabled="!authenticated"
          @click="tab = id"
        >
          <span>{{ label }}</span
          ><span aria-hidden="true">↗</span>
        </button>
      </nav>
      <div class="sidebar-foot">
        <span class="dot"></span> 私有模型 · 统一入口<small>Go / Higress</small>
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
      <p v-if="error" role="alert" class="error">{{ error }}</p>
      <section v-if="!authenticated" class="login panel">
        <p class="eyebrow">ADMIN CONSOLE</p>
        <h1>登录管理工作台</h1>
        <p class="muted">使用管理员会话管理模型和预算。</p>
        <form @submit.prevent="login">
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
        ><Models v-if="tab === 'models'" /><Keys
          v-else-if="tab === 'keys'" /><Playground
          v-else-if="tab === 'play'" /><Releases
          v-else-if="tab === 'releases'" /><Usage v-else
      /></template>
      <footer>管理会话与消费 Key 分离 · 用量以服务端耐久记录为准</footer>
    </main>
  </div>
</template>
