import { createServer } from "vite";
import { chromium } from "playwright-core";
import fs from "node:fs/promises";
import assert from "node:assert/strict";
if (!process.env.MAAS_LOCAL_API)
  throw Error("Explicit disposable release harness required");
const inputs = JSON.parse(
  await fs.readFile("artifacts/release-browser-inputs.json", "utf8"),
);
const output = "artifacts/release-browser";
await fs.mkdir(output, { recursive: true });
const server = await createServer();
let browser;
const checks = [],
  errors = [],
  statuses = [];
try {
  await server.listen();
  const url = "http://127.0.0.1:" + server.httpServer.address().port;
  browser = await chromium.launch({
    executablePath:
      process.env.EDGE_PATH ||
      "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
    headless: true,
  });
  const context = await browser.newContext({
      viewport: { width: 1440, height: 1000 },
    }),
    page = await context.newPage();
  page.setDefaultTimeout(20000);
  page.on("pageerror", (e) => errors.push(e.message));
  page.on("response", (r) => {
    if (r.url().includes("/api/admin/v1/"))
      statuses.push({
        path: new URL(r.url()).pathname,
        method: r.request().method(),
        status: r.status(),
      });
  });
  const button = (name) => page.getByRole("button", { name, exact: true });
  const observe = async (method, suffix, click) => {
    const pending = page.waitForResponse(
      (r) =>
        r.request().method() === method &&
        new URL(r.url()).pathname.endsWith(suffix),
    );
    await click();
    const response = await pending;
    return { status: response.status(), body: await response.json() };
  };
  const reread = async () => {
    await button("重读当前 CR").click();
    await button("编辑配置").waitFor();
    await page.waitForFunction(
      () =>
        !document.querySelector(".release-card").__vueParentComponent.setupState
          .reading,
    );
  };
  const edit = async (change) => {
    await button("编辑配置").click();
    const input = JSON.parse(
      await page.getByLabel("ModelRelease JSON").inputValue(),
    );
    change(input);
    await page.getByLabel("ModelRelease JSON").fill(JSON.stringify(input));
    return observe("PUT", input.metadata.name, () =>
      button("校验并提交配置").click(),
    );
  };
  const exact = async (id) => {
    const result = await observe("GET", id, () => button("查询原操作").click());
    assert.equal(result.status, 200);
    assert.equal(result.body.id, id);
    return result.body;
  };
  const create = async (name) => {
    await button("新建外部 API CR").click();
    await page
      .getByLabel("ModelRelease JSON")
      .fill(JSON.stringify(inputs[name]));
    const result = await observe("POST", "model-releases", () =>
      button("校验并提交配置").click(),
    );
    assert.equal(result.status, 202);
    assert.equal(result.body.operation.action, "Create");
    return result.body;
  };
  await page.goto(url);
  await page.getByRole("heading", { name: "模型目录", exact: true }).waitFor();
  await button("模型目录").click();
  await page
    .getByText("尚无模型。请先提交获准发布配置。", { exact: true })
    .waitFor();
  checks.push("actual same-kernel empty model catalogue");
  await button("模型发布").click();
  await page.getByText("暂无模型发布。", { exact: true }).waitFor();
  checks.push("actual empty release list, no fixture fallback");
  const created = await create("managed-model");
  assert.equal(created.operation.state, "Running");
  assert(created.resource.metadata.uid);
  checks.push(
    "browser creates approved synthetic CR with real API-server UID and 202 Running",
  );
  assert.equal((await exact(created.operation.id)).state, "Running");
  checks.push("202 and exact original operation do not imply Callable");
  await reread();
  const history = await observe("GET", "revisions", () =>
    button("读取保留修订").click(),
  );
  assert.equal(history.status, 200);
  const firstRevision = history.body.data[0].revision;
  assert.equal(history.body.requested_cr_uid, created.resource.metadata.uid);
  checks.push("real retained history is scoped to original UID");
  await page.screenshot({
    path: output + "/release-created.png",
    fullPage: true,
  });
  const paused = await observe("PUT", "managed-model", () =>
    button("暂停发布").click(),
  );
  assert.equal(paused.body.operation.action, "Pause");
  assert.equal((await exact(paused.body.operation.id)).state, "Succeeded");
  checks.push("PUT Pause ACK and persisted terminal operation");
  await reread();
  const savedPause = await edit(() => {});
  assert.equal(savedPause.body.operation.action, "Update");
  assert.equal(savedPause.body.resource.spec.lifecycle.desiredState, "Paused");
  checks.push(
    "editing after pause saves Paused with correct version and Update action",
  );
  await reread();
  const resumed = await observe("PUT", "managed-model", () =>
    button("恢复发布").click(),
  );
  assert.equal(resumed.body.operation.action, "Resume");
  checks.push("PUT Resume ACK accepted by strict page association");
  await reread();
  const editorPause = await edit(
    (x) => (x.spec.lifecycle.desiredState = "Paused"),
  );
  assert.equal(editorPause.body.operation.action, "Pause");
  await reread();
  const editorResume = await edit(
    (x) => (x.spec.lifecycle.desiredState = "Published"),
  );
  assert.equal(editorResume.body.operation.action, "Resume");
  checks.push(
    "JSON Save classifies actual desiredState transitions as Pause and Resume",
  );
  await reread();
  const updated = await edit(
    (x) => (x.spec.source.externalAPI.upstreamModel = "test-second-model"),
  );
  assert.equal(updated.body.operation.action, "Update");
  checks.push(
    "approved spec update uses original RV and creates a retained revision",
  );
  await reread();
  await button("读取保留修订").click();
  await page.locator(".revision").filter({ hasText: firstRevision }).waitFor();
  const rollback = await observe("POST", "rollback", () =>
    page
      .locator(".revision")
      .filter({ hasText: firstRevision })
      .getByRole("button")
      .click(),
  );
  assert.equal(rollback.status, 202);
  assert.equal(rollback.body.resource, null);
  assert.equal(rollback.body.operation.action, "Rollback");
  await exact(rollback.body.operation.id);
  checks.push(
    "null-resource rollback retains and queries only original operation ID",
  );
  await reread();
  await button("编辑配置").click();
  assert.equal(
    JSON.parse(await page.getByLabel("ModelRelease JSON").inputValue()).spec
      .source.externalAPI.upstreamModel,
    inputs["managed-model"].spec.source.externalAPI.upstreamModel,
  );
  checks.push("edit after rollback uses confirmed rolled-back spec");
  await button("下线并清理").click();
  const removed = await observe("DELETE", "managed-model", () =>
    button("确认下线").click(),
  );
  assert.equal(removed.status, 202);
  assert.equal(removed.body.resource, null);
  assert.equal(removed.body.operation.action, "Delete");
  await exact(removed.body.operation.id);
  checks.push(
    "null-resource delete keeps durable operation lookup after CR removal",
  );
  await create("conflict-browser-model");
  await reread();
  const writesBefore = statuses.filter(
    (x) => x.method === "PUT" && x.path.endsWith("conflict-browser-model"),
  ).length;
  const conflict = await edit(
    (x) => x.spec.lifecycle.progressDeadlineSeconds++,
  );
  assert.equal(conflict.status, 409);
  await page
    .getByText("配置已被修改，请刷新并核对后重新提交。", { exact: true })
    .waitFor();
  assert.equal(
    statuses.filter(
      (x) => x.method === "PUT" && x.path.endsWith("conflict-browser-model"),
    ).length,
    writesBefore + 1,
  );
  checks.push("actual API-server CAS race is visible 409 and never retried");
  await create("unknown-browser-model");
  await reread();
  const unknown = await edit((x) => x.spec.lifecycle.progressDeadlineSeconds++);
  assert.equal(unknown.status, 202);
  assert.equal(unknown.body.resource, null);
  assert.equal(unknown.body.operation.state, "Unknown");
  await page
    .getByText("原操作写入结果未知（202）；仅查询原操作 ID，禁止重放。", {
      exact: true,
    })
    .waitFor();
  const count = statuses.filter(
    (x) => x.method === "PUT" && x.path.endsWith("unknown-browser-model"),
  ).length;
  for (let i = 0; i < 3; i++)
    assert.equal((await exact(unknown.body.operation.id)).state, "Unknown");
  assert(await button("编辑配置").isDisabled());
  assert.equal(
    statuses.filter(
      (x) => x.method === "PUT" && x.path.endsWith("unknown-browser-model"),
    ).length,
    count,
  );
  checks.push(
    "real API-server post-write ACK loss stays Unknown and locks replay across exact queries",
  );
  await page.screenshot({ path: output + "/ack-unknown.png", fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  assert.equal(
    await page.evaluate(
      () => document.documentElement.scrollWidth > innerWidth,
    ),
    false,
  );
  await page.screenshot({
    path: output + "/release-mobile.png",
    fullPage: true,
  });
  checks.push("390px release/unknown workflow without page overflow");
  assert.equal(
    await page.evaluate(() => localStorage.length + sessionStorage.length),
    0,
  );
  assert(
    (await context.cookies(url)).find((c) => c.name === "maas_session")
      ?.httpOnly,
  );
  checks.push("HttpOnly management session and no credential persistence");
  await button("退出会话").click();
  await button("连接本地 Go 管理接口").waitFor();
  checks.push("local temporary session logout");
  assert.deepEqual(errors, []);
  await fs.writeFile(
    output + "/results.json",
    JSON.stringify(
      {
        scope:
          "Actual Go + disposable MySQL + real envtest API-server/etcd; synthetic approved metadata and failing gateway producer; explicit reconciler steps, no model or workload",
        checks,
        statuses,
        errors,
      },
      null,
      2,
    ),
  );
  console.log(
    JSON.stringify({ actualReleaseBrowserChecks: checks.length, errors }),
  );
} finally {
  await browser?.close();
  await server.close();
}
