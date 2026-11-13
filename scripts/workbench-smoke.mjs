import { startWorkbench, root } from "./dev.mjs";
import { createRequire } from "node:module";
import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import assert from "node:assert/strict";

const require = createRequire(path.join(root, "console", "package.json"));
const output = path.join(root, "artifacts", "workbench");
await mkdir(output, { recursive: true });
const checks = [],
  errors = [];
let app, browser, failure;
const until = async (read, test, label) => {
  const deadline = Date.now() + 20000;
  while (Date.now() < deadline) {
    const value = await read();
    if (test(value)) return value;
    await new Promise((resolve) => setTimeout(resolve, 200));
  }
  throw Error("Timed out: " + label);
};
try {
  app = await startWorkbench({
    port: 0,
    build: !process.argv.includes("--skip-build"),
  });
  const { chromium } = require("playwright-core");
  browser = await chromium.launch({
    executablePath:
      process.env.EDGE_PATH ||
      (process.platform === "win32"
        ? "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe"
        : "/usr/bin/chromium"),
    headless: true,
  });
  const page = await browser.newPage({
    viewport: { width: 1440, height: 1000 },
  });
  page.setDefaultTimeout(20000);
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto(app.url);
  await page.getByRole("heading", { name: "模型目录", exact: true }).waitFor();
  const get = async (route) => {
    const response = await page.request.get(app.url + "/api/admin/v1" + route);
    assert.equal(response.status(), 200, route);
    return response.json();
  };
  const models = await until(
    () => get("/models"),
    (value) => value.data.length > 0,
    "seeded real profile",
  );
  assert.equal(models.data[0].callable, false);
  assert(
    (await page.context().cookies()).some(
      (cookie) =>
        cookie.name === "maas_session" &&
        cookie.httpOnly &&
        cookie.sameSite === "Strict",
    ),
  );
  checks.push(
    "root startup serves compiled Vue and actual same-origin Go API",
    "HttpOnly local session and model catalogue use real MySQL metadata",
    "unconfigured inference remains non-callable",
  );
  await page.screenshot({
    path: path.join(output, "catalogue.png"),
    fullPage: true,
  });
  const nav = async (name) => {
    await page.getByRole("button", { name, exact: true }).click();
    await page.getByRole("heading", { name, exact: true }).waitFor();
  };
  await nav("平台 Key");
  await page.getByTestId("create-key").click();
  await page.getByLabel("名称", { exact: true }).fill("集成运行 Key");
  await page.getByLabel("UTC 周期", { exact: false }).selectOption("utc_day");
  await page.getByLabel("请求数限额", { exact: true }).fill("20");
  const createdKey = page.waitForResponse(
    (r) =>
      r.request().method() === "POST" &&
      new URL(r.url()).pathname.endsWith("/keys"),
  );
  await page.getByRole("button", { name: "创建 Key", exact: true }).click();
  assert.equal((await createdKey).status(), 201);
  await page.getByTestId("one-time-secret").waitFor();
  await page.getByRole("button", { name: "我已保存，关闭原值" }).click();
  await page.getByRole("button", { name: "修改预算", exact: true }).click();
  await page.getByLabel("请求数限额", { exact: true }).fill("0");
  const patched = page.waitForResponse(
    (r) =>
      r.request().method() === "PATCH" &&
      new URL(r.url()).pathname.includes("/keys/"),
  );
  await page.getByRole("button", { name: "保存预算", exact: true }).click();
  assert.equal((await patched).status(), 200);
  await page.getByRole("button", { name: "撤销", exact: true }).click();
  const revoke = page.waitForResponse((r) =>
    new URL(r.url()).pathname.endsWith("/revoke"),
  );
  await page.getByRole("button", { name: "确认撤销", exact: true }).click();
  assert.equal((await revoke).status(), 200);
  checks.push(
    "create Key and hide one-time secret",
    "explicit zero request budget reaches Go/MySQL",
    "revoke uses the same durable Key kernel",
  );
  await page.screenshot({
    path: path.join(output, "keys.png"),
    fullPage: true,
  });
  await nav("模型发布");
  await page.getByRole("button", { name: "载入本地示例", exact: true }).click();
  const editor = page.getByLabel("ModelRelease JSON");
  await editor.waitFor();
  const input = JSON.parse(await editor.inputValue());
  const name = input.metadata.name,
    namespace = input.metadata.namespace;
  const releasePath = "/model-releases/" + namespace + "/" + name;
  const mutation = async (action) => {
    const pending = page.waitForResponse(
      (r) =>
        ["POST", "PUT", "DELETE"].includes(r.request().method()) &&
        new URL(r.url()).pathname.includes("/model-releases"),
    );
    await action();
    const response = await pending;
    assert.equal(response.status(), 202);
    return response.json();
  };
  await mutation(() =>
    page.getByRole("button", { name: "校验并提交配置", exact: true }).click(),
  );
  const observed = () =>
    until(
      () => get(releasePath),
      (m) =>
        m.status?.observedGeneration === m.metadata.generation &&
        ["Degraded", "Paused"].includes(m.status.phase),
      "controller observation",
    );
  await observed();
  await page.getByRole("button", { name: "重读当前 CR", exact: true }).click();
  const paused = await mutation(() =>
    page.getByRole("button", { name: "暂停发布", exact: true }).click(),
  );
  await until(
    () => get("/release-operations/" + paused.operation.id),
    (o) => o.state === "Succeeded",
    "durable pause completion",
  );
  await observed();
  await page.getByRole("button", { name: "重读当前 CR", exact: true }).click();
  await mutation(() =>
    page.getByRole("button", { name: "恢复发布", exact: true }).click(),
  );
  await observed();
  await page.getByRole("button", { name: "重读当前 CR", exact: true }).click();
  await page.getByRole("button", { name: "编辑配置", exact: true }).click();
  const changed = JSON.parse(await editor.inputValue());
  changed.spec.source.externalAPI.upstreamModel = "local-example-v2";
  await editor.fill(JSON.stringify(changed, null, 2));
  await mutation(() =>
    page.getByRole("button", { name: "校验并提交配置", exact: true }).click(),
  );
  await observed();
  await page.getByRole("button", { name: "重读当前 CR", exact: true }).click();
  await page.getByRole("button", { name: "读取保留修订", exact: true }).click();
  const rollback = page
    .getByRole("button", { name: "回滚到此修订", exact: true })
    .last();
  await until(
    () => rollback.isEnabled(),
    Boolean,
    "retained original UID rollback eligibility",
  );
  await mutation(() => rollback.click());
  const restored = await observed();
  assert.equal(
    restored.spec.source.externalAPI.upstreamModel,
    "local-example-v1",
  );
  checks.push(
    "create ModelRelease from usable local references",
    "continuous real controller persists pause completion",
    "resume and update retain UID/resourceVersion guards",
    "original UID history and rollback restore original spec",
  );
  await page.screenshot({
    path: path.join(output, "release.png"),
    fullPage: true,
  });
  await page.getByRole("button", { name: "重读当前 CR", exact: true }).click();
  await page.getByRole("button", { name: "下线并清理", exact: true }).click();
  const deleted = await mutation(() =>
    page.getByRole("button", { name: "确认下线", exact: true }).click(),
  );
  await until(
    () => get("/release-operations/" + deleted.operation.id),
    (o) => o.state === "Succeeded",
    "delete operation retained after cleanup",
  );
  await until(
    async () =>
      (
        await page.request.get(app.url + "/api/admin/v1" + releasePath)
      ).status(),
    (status) => status === 404,
    "finalizer removes the original CR after durable cleanup",
  );
  checks.push("delete and original operation query survive CR removal");
  await nav("请求与用量");
  await page.getByText("当前筛选没有请求。", { exact: true }).waitFor();
  checks.push("usage reads actual empty durable ledger");
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({
    path: path.join(output, "mobile.png"),
    fullPage: true,
  });
  await page.getByRole("button", { name: "退出会话", exact: true }).click();
  assert.equal(
    (await page.request.get(app.url + "/api/admin/v1/keys")).status(),
    401,
  );
  assert.equal(
    (
      await page.request.post(app.url + "/v1/chat/completions", { data: {} })
    ).status(),
    503,
  );
  checks.push(
    "logout invalidates the local session",
    "missing inference returns structured failure without SPA or supplier bypass",
  );
  assert.deepEqual(errors, []);
} catch (error) {
  failure = error.message;
  throw error;
} finally {
  if (browser) await browser.close();
  if (app) {
    const result = await app.stop();
    assert.equal(result.code, 0, "workbench exits cleanly");
    assert.equal(result.cleaned, true, "owned temporary data cleaned");
    checks.push(
      "one stop shuts down HTTP, API-server/etcd and private MySQL with cleanup",
    );
  }
  await writeFile(
    path.join(output, "results.json"),
    JSON.stringify(
      {
        checks,
        errors,
        failure: failure ?? null,
        scope: "compiled-Vue-real-Go-MySQL-envtest-local-integration",
      },
      null,
      2,
    ),
  );
}
console.log(
  JSON.stringify({
    passed: checks.length,
    pageErrors: errors.length,
    results: "artifacts/workbench/results.json",
  }),
);
