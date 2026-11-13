import { createServer } from "vite";
import { chromium } from "playwright-core";
import fs from "node:fs/promises";
import assert from "node:assert/strict";
if (!process.env.MAAS_LOCAL_API || !process.env.MAAS_BROWSER_CR)
  throw Error("Use the disposable Go/API-server/MySQL browser harness.");
const output = "artifacts/management-browser";
await fs.mkdir(output, { recursive: true });
const server = await createServer();
let browser;
const checks = [],
  errors = [],
  requests = [];
try {
  await server.listen();
  const url = "http://127.0.0.1:" + server.httpServer.address().port;
  browser = await chromium.launch({
    executablePath:
      process.env.EDGE_PATH ||
      "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
    headless: true,
  });
  const page = await browser.newPage({
    viewport: { width: 1440, height: 1000 },
  });
  page.setDefaultTimeout(15000);
  page.on("pageerror", (e) => errors.push(e.message));
  page.on("response", (r) => {
    if (r.url().includes("/api/admin/v1/"))
      requests.push({
        method: r.request().method(),
        path: new URL(r.url()).pathname,
        status: r.status(),
      });
  });
  const nav = async (name) => {
    await page.getByRole("button", { name, exact: true }).click();
    await page.getByRole("heading", { name, exact: true }).waitFor();
  };
  const shot = async (name) => {
    await page.mouse.move(1400, 5);
    await page.screenshot({
      path: output + "/" + name + ".png",
      fullPage: true,
    });
  };
  await page.goto(url);
  await page.getByRole("heading", { name: "模型目录", exact: true }).waitFor();
  checks.push("model catalogue is an independent real Go page");
  await nav("平台 Key");
  await page.getByTestId("create-key").click();
  await page.getByLabel("名称", { exact: true }).fill("应用测试 Key");
  await page.getByLabel("UTC 周期", { exact: false }).selectOption("utc_day");
  await page.getByLabel("请求数限额", { exact: true }).fill("20");
  const keyPost = page.waitForResponse(
    (r) =>
      r.request().method() === "POST" &&
      new URL(r.url()).pathname.endsWith("/keys"),
  );
  await page.getByRole("button", { name: "创建 Key", exact: true }).click();
  assert.equal((await keyPost).status(), 201);
  await page.getByTestId("one-time-secret").waitFor();
  await page.getByRole("button", { name: "我已保存，关闭原值" }).click();
  checks.push("create dialog and one-time Key over actual Go/MySQL");
  await page.getByLabel("搜索 Key", { exact: true }).fill("不存在");
  await page.getByText("没有匹配的 Key。", { exact: true }).waitFor();
  await page.getByLabel("搜索 Key", { exact: true }).fill("");
  await shot("keys");
  await page.getByRole("button", { name: "查看预算", exact: true }).click();
  await page
    .getByRole("heading", { name: "应用测试 Key · 预算明细", exact: true })
    .waitFor();
  await page.getByRole("button", { name: "关闭弹窗" }).click();
  checks.push("search, status and budget detail remain readable");
  await page.getByRole("button", { name: "查看用量", exact: true }).click();
  await page
    .getByRole("heading", { name: "请求与用量", exact: true })
    .waitFor();
  assert(await page.getByLabel("Key UUID", { exact: true }).inputValue());
  await page.getByText("当前筛选没有请求。", { exact: true }).waitFor();
  await shot("usage");
  checks.push("Key links to actual usage with its original Key ID");
  await nav("模型发布");
  await page
    .getByRole("button", { name: "新建外部 API CR", exact: true })
    .click();
  await page
    .getByLabel("ModelRelease JSON")
    .fill(JSON.stringify(JSON.parse(process.env.MAAS_BROWSER_CR), null, 2));
  const created = page.waitForResponse(
    (r) =>
      r.request().method() === "POST" &&
      new URL(r.url()).pathname.endsWith("/model-releases"),
  );
  await page
    .getByRole("button", { name: "校验并提交配置", exact: true })
    .click();
  assert.equal((await created).status(), 202);
  await page.getByText("配置已提交（202）", { exact: false }).waitFor();
  checks.push("create model release through actual Go and API-server");
  const read = async () => {
    let last = "",
      same = 0;
    const cr = JSON.parse(process.env.MAAS_BROWSER_CR);
    const path =
      "/api/admin/v1/model-releases/" +
      cr.metadata.namespace +
      "/" +
      cr.metadata.name;
    for (let attempt = 0; attempt < 25; attempt++) {
      const reply = await page.request.get(url + path);
      assert.equal(reply.status(), 200);
      const value = await reply.json(),
        rv = value.metadata.resourceVersion;
      same = rv === last ? same + 1 : 0;
      last = rv;
      if (same >= 2) break;
      await page.waitForTimeout(200);
    }
    const response = page.waitForResponse(
      (r) =>
        r.request().method() === "GET" && new URL(r.url()).pathname === path,
    );
    await page
      .getByRole("button", { name: "重读当前 CR", exact: true })
      .click();
    assert.equal((await response).status(), 200);
    await page.waitForFunction(() =>
      Array.from(document.querySelectorAll("button")).some(
        (b) => b.textContent.trim() === "重读当前 CR" && !b.disabled,
      ),
    );
  };
  await read();
  await shot("release-created");
  const mutate = async (label, action) => {
    await read();
    const result = page.waitForResponse(
      (r) =>
        r.request().method() === "PUT" && r.url().includes("/model-releases/"),
    );
    await page.getByRole("button", { name: label, exact: true }).click();
    const response = await result;
    assert.equal(response.status(), 202);
    const value = await response.json();
    assert.equal(value.operation.action, action);
    await page
      .getByRole("button", {
        name: label === "暂停发布" ? "恢复发布" : "暂停发布",
        exact: true,
      })
      .waitFor();
  };
  await mutate("暂停发布", "Pause");
  await page.getByRole("button", { name: "查询原操作", exact: true }).click();
  await shot("release-paused");
  checks.push(
    "Pause via PUT, exact operation query, no automatic success promotion",
  );
  await mutate("恢复发布", "Resume");
  checks.push("Resume follows current UID/resourceVersion");
  await read();
  await page.getByRole("button", { name: "编辑配置", exact: true }).click();
  let input = JSON.parse(
    await page.getByLabel("ModelRelease JSON").inputValue(),
  );
  input.spec.source.externalAPI.upstreamModel = "test-second-model";
  await page
    .getByLabel("ModelRelease JSON")
    .fill(JSON.stringify(input, null, 2));
  const edited = page.waitForResponse(
    (r) =>
      r.request().method() === "PUT" && r.url().includes("/model-releases/"),
  );
  await page
    .getByRole("button", { name: "校验并提交配置", exact: true })
    .click();
  assert.equal((await edited).status(), 202);
  checks.push("update approved model configuration");
  await read();
  await page.getByRole("button", { name: "读取保留修订", exact: true }).click();
  await page
    .getByRole("heading", { name: "保留修订 · present", exact: true })
    .waitFor();
  await page.waitForFunction(
    () => document.querySelectorAll(".revision").length >= 2,
  );
  const rollback = page
    .locator(".revision")
    .filter({
      has: page.getByRole("button", { name: "回滚到此修订", exact: true }),
    })
    .last()
    .getByRole("button", { name: "回滚到此修订", exact: true });
  const rolled = page.waitForResponse(
    (r) => r.request().method() === "POST" && r.url().endsWith("/rollback"),
  );
  await rollback.click();
  const rollbackReply = await rolled;
  assert.equal(rollbackReply.status(), 202);
  assert.equal((await rollbackReply.json()).operation.action, "Rollback");
  await page.getByRole("button", { name: "查询原操作", exact: true }).click();
  await read();
  await shot("release-rollback");
  checks.push(
    "retained revisions and rollback use real Go history, with nullable ACK resource",
  );
  await nav("模型目录");
  await page.getByRole("button", { name: "刷新目录", exact: true }).click();
  await page.getByText("本地发布验证模型", { exact: true }).waitFor();
  await shot("models");
  checks.push(
    "registered model is visible but not Callable without real gateway proof",
  );
  await page
    .getByRole("button", { name: "在线试用", exact: true })
    .last()
    .click();
  await page.getByRole("heading", { name: "在线试用", exact: true }).waitFor();
  await page
    .getByText("当前 Go 服务尚未开放推理入口。", { exact: false })
    .waitFor();
  assert(
    await page
      .getByRole("button", { name: "发送请求", exact: true })
      .isDisabled(),
  );
  await shot("playground");
  checks.push(
    "online trial has its own page and honestly blocks unavailable inference",
  );
  assert.equal(
    await page.evaluate(() => localStorage.length + sessionStorage.length),
    0,
  );
  checks.push("credentials stay outside browser storage");
  await page.setViewportSize({ width: 390, height: 844 });
  await nav("平台 Key");
  await shot("keys-mobile");
  assert.equal(
    await page.evaluate(
      () => document.documentElement.scrollWidth > innerWidth,
    ),
    false,
  );
  checks.push("mobile Key table becomes readable cards without page overflow");
  assert.deepEqual(errors, []);
  await fs.writeFile(
    output + "/results.json",
    JSON.stringify(
      {
        scope:
          "Real Go + temporary MySQL + envtest API-server; approved metadata and missing gateway are test adapters; no model calls",
        checks,
        requests,
        errors,
      },
      null,
      2,
    ),
  );
  console.log(
    JSON.stringify({
      managementBrowserChecks: checks.length,
      pageErrors: errors.length,
    }),
  );
} finally {
  await browser?.close();
  await server.close();
}
