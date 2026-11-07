import { createServer } from "vite";
import { chromium } from "playwright-core";
import fs from "node:fs/promises";
import assert from "node:assert/strict";
if (!process.env.MAAS_LOCAL_API)
  throw Error(
    "Use the disposable Go browser harness; an explicit loopback API is required.",
  );
const output = "artifacts/go-browser";
await fs.mkdir(output, { recursive: true });
const server = await createServer();
let browser;
const checks = [],
  errors = [],
  statuses = [];
try {
  await server.listen();
  const url = "http://127.0.0.1:" + server.httpServer.address().port;
  const denied = await fetch(url + "/__maas/local-session", {
    method: "POST",
    headers: { Origin: "https://untrusted.invalid" },
  });
  assert.equal(denied.status, 403);
  checks.push("bootstrap rejects another Origin");
  browser = await chromium.launch({
    executablePath:
      process.env.EDGE_PATH ||
      "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
    headless: true,
  });
  const context = await browser.newContext({
    viewport: { width: 1440, height: 1000 },
  });
  const page = await context.newPage();
  page.setDefaultTimeout(15000);
  page.on("pageerror", (e) => errors.push(e.message));
  page.on("response", (r) => {
    if (r.url().includes("/api/admin/v1/"))
      statuses.push({
        path: new URL(r.url()).pathname,
        method: r.request().method(),
        status: r.status(),
      });
  });
  await page.goto(url);
  await page.getByRole("heading", { name: "模型目录", exact: true }).waitFor();
  await page.getByRole("button", { name: "平台 Key", exact: true }).click();
  await page.getByRole("heading", { name: "平台 Key", exact: true }).waitFor();
  await page.getByText("尚无平台 Key。", { exact: false }).waitFor();
  await page.getByText("本地临时管理会话", { exact: false }).waitFor();
  checks.push("page uses actual Go key listing under temporary session");
  const cookies = await context.cookies(url);
  assert(cookies.find((c) => c.name === "maas_session")?.httpOnly);
  checks.push("management cookie is HttpOnly");
  await page.getByTestId("create-key").click();
  await page.getByLabel("名称", { exact: true }).fill("本地 Go 功能验证");
  await page.getByLabel("UTC 周期").selectOption("utc_day");
  await page.getByLabel("请求数限额", { exact: true }).fill("9");
  await page.getByLabel("Token 限额", { exact: true }).fill("1000");
  await page.getByLabel("金额限额（原子单位）", { exact: true }).fill("800000");
  await page.getByLabel("币种", { exact: true }).fill("TST");
  const created = page.waitForResponse(
    (r) =>
      new URL(r.url()).pathname.endsWith("/keys") &&
      r.request().method() === "POST",
  );
  await page.getByRole("button", { name: "创建 Key", exact: true }).click();
  const response = await created;
  assert.equal(response.status(), 201);
  const { key } = await response.json();
  await page.getByTestId("one-time-secret").waitFor();
  checks.push("actual Go/MySQL creates Key with three explicit budgets");
  await page.getByRole("button", { name: "我已保存，关闭原值" }).click();
  assert.equal(await page.getByTestId("one-time-secret").count(), 0);
  await page.getByRole("button", { name: "刷新列表", exact: true }).click();
  await page.getByText("本地 Go 功能验证", { exact: true }).waitFor();
  assert.equal(await page.getByTestId("one-time-secret").count(), 0);
  checks.push("secret closed and absent after actual metadata reload");
  await page.mouse.move(1400, 5);
  await page.screenshot({ path: output + "/keys-created.png", fullPage: true });
  await page.getByRole("button", { name: "修改预算", exact: true }).click();
  await page.getByLabel("请求数限额", { exact: true }).fill("0");
  const updated = page.waitForResponse((r) => r.request().method() === "PATCH");
  await page.getByRole("button", { name: "保存预算", exact: true }).click();
  assert.equal((await updated).status(), 200);
  await page.getByText("预算已更新。", { exact: true }).waitFor();
  checks.push("actual budget CAS saves explicit zero");
  const csrf = await page.evaluate(async () => {
    const { api } = await import("/src/api/client.ts");
    return api.csrf;
  });
  const conflict = await context.request.patch(
    url + "/api/admin/v1/keys/" + key.id,
    {
      headers: {
        Origin: url,
        "X-CSRF-Token": csrf,
        "Content-Type": "application/json",
      },
      data: {
        expected_revision: key.budget_policy.revision,
        limits: { ...key.budget_policy.limits, requests: "1" },
      },
    },
  );
  assert.equal(conflict.status(), 409);
  checks.push("old budget revision receives actual 409");
  await page.getByRole("button", { name: "撤销", exact: true }).click();
  const revoked = page.waitForResponse((r) => r.url().endsWith("/revoke"));
  await page.getByRole("button", { name: "确认撤销", exact: true }).click();
  assert.equal((await revoked).status(), 200);
  await page.getByText("Key 已撤销。", { exact: true }).waitFor();
  await page.mouse.move(1400, 5);
  await page.screenshot({ path: output + "/key-revoked.png", fullPage: true });
  checks.push("actual Key revoke reflected in page");
  await page.getByRole("button", { name: "请求与用量", exact: true }).click();
  await page.getByText("当前筛选没有请求。", { exact: true }).waitFor();
  await page.getByLabel("查询类型").selectOption("summary");
  await page.getByText("当前筛选没有汇总。", { exact: true }).waitFor();
  await page.mouse.move(1400, 5);
  await page.screenshot({ path: output + "/usage.png", fullPage: true });
  checks.push("actual empty request and usage projections");
  const lookup = await context.request.get(
    url +
      "/api/admin/v1/usage/requests?request_id=00000000-0000-4000-8000-000000000099",
  );
  assert.equal(lookup.status(), 200);
  assert.equal((await lookup.json()).lookup.resolution, "unknown");
  checks.push("missing original request remains unknown");
  const history = await context.request.get(
    url +
      "/api/admin/v1/model-releases/maas-models-example/external-model-example/revisions?cr_uid=00000000-0000-4000-8000-000000000010",
  );
  assert.equal(history.status(), 503);
  checks.push("unconfigured authoritative history remains 503");
  await page.getByRole("button", { name: "模型发布", exact: true }).click();
  await page.getByRole("alert").waitFor();
  await page.mouse.move(1400, 5);
  await page.screenshot({
    path: output + "/available-subset.png",
    fullPage: true,
  });
  checks.push(
    "unconfigured release API remains an explicit error, never mocked",
  );
  assert.equal(
    await page.evaluate(() => localStorage.length + sessionStorage.length),
    0,
  );
  checks.push("no credential persistence");
  await page.getByRole("button", { name: "退出会话", exact: true }).click();
  await page
    .getByRole("button", { name: "连接本地 Go 管理接口", exact: true })
    .waitFor();
  assert(!(await context.cookies(url)).some((c) => c.name === "maas_session"));
  checks.push("local logout clears browser session");
  assert.deepEqual(errors, []);
  await fs.writeFile(
    output + "/results.json",
    JSON.stringify(
      {
        scope:
          "Actual Go controlapi.Handler + temporary MySQL; local session installation bridge; no inference, vendor or target deployment",
        checks,
        statuses,
        errors,
      },
      null,
      2,
    ),
  );
  console.log(
    JSON.stringify({
      actualGoBrowserChecks: checks.length,
      pageErrors: errors.length,
    }),
  );
} finally {
  await browser?.close();
  await server.close();
}
