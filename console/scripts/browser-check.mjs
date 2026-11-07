import { createServer } from "vite";
import { chromium } from "playwright-core";
import fs from "node:fs/promises";
import assert from "node:assert/strict";
const dir = "artifacts";
await fs.mkdir(dir, { recursive: true });
const server = await createServer({
  server: { host: "127.0.0.1", port: 0 },
  define: { "import.meta.env.VITE_CONSOLE_FIXTURES": JSON.stringify("true") },
});
let browser;
const errors = [];
const checks = [];
const check = (label) => checks.push(label);
try {
  await server.listen();
  const address = server.httpServer.address();
  const url = "http://127.0.0.1:" + address.port;
  browser = await chromium.launch({
    executablePath:
      process.env.EDGE_PATH ||
      "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
    headless: true,
  });
  const page = await browser.newPage({
    viewport: { width: 1440, height: 1000 },
    deviceScaleFactor: 1,
  });
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto(url);
  await page.getByRole("heading", { name: "模型目录", exact: true }).waitFor();
  await page.getByText("DeepSeek · 开发样例", { exact: true }).waitFor();
  await page.screenshot({ path: dir + "/catalog-desktop.png", fullPage: true });
  check("desktop catalog, fixture banner and two sources");
  await page.getByRole("button", { name: "平台 Key", exact: true }).click();
  await page.getByTestId("create-key").click();
  await page.getByLabel("名称", { exact: true }).fill("浏览器验证 Key");
  await page.getByLabel("UTC 周期").selectOption("utc_day");
  await page.getByLabel("请求数限额", { exact: true }).fill("0");
  await page
    .getByLabel("金额限额（原子单位）", { exact: true })
    .fill("99999999999999999999999999999999999999");
  await page.getByLabel("币种", { exact: true }).fill("USD");
  await page.getByRole("button", { name: "创建 Key", exact: true }).click();
  await page.getByTestId("one-time-secret").waitFor();
  check("explicit zero and 38-digit budget, one-time secret");
  await page.getByRole("button", { name: "我已保存，关闭原值" }).click();
  assert.equal(await page.getByTestId("one-time-secret").count(), 0);
  await page.screenshot({ path: dir + "/keys-desktop.png", fullPage: true });
  await page
    .getByRole("navigation", { name: "主导航" })
    .getByRole("button", { name: "在线试用", exact: true })
    .click();
  await page.getByLabel("模型").selectOption("model-a");
  await page
    .getByLabel("消费 Key", { exact: true })
    .fill("fixture_only_not_a_credential_000001");
  await page.getByLabel("消息", { exact: true }).fill("测试停止后精确回查");
  await page.getByRole("button", { name: "发送请求", exact: true }).click();
  await page
    .getByText("这是开发夹具的流式响应。", { exact: false })
    .first()
    .waitFor();
  await page.getByRole("button", { name: "停止传输", exact: true }).click();
  await page.getByText("精确查询：recorded", { exact: false }).waitFor();
  await page.getByText("容量：quarantined", { exact: false }).waitFor();
  await page.screenshot({
    path: dir + "/playground-cancelled.png",
    fullPage: true,
  });
  check(
    "stream stop, original request lookup, quarantined capacity and unknown tokens",
  );
  await page.getByRole("button", { name: "模型发布", exact: true }).click();
  await page.locator(".release-card").first().click();
  await page.getByRole("heading", { name: "model-a", exact: true }).waitFor();
  await page.getByRole("button", { name: "读取保留修订", exact: true }).click();
  await page.getByText("保留修订 · present", { exact: false }).waitFor();
  await page.screenshot({ path: dir + "/release-desktop.png", fullPage: true });
  check(
    "failed desired candidate, old active callable publication and retained revisions",
  );
  await page.getByRole("button", { name: "暂停发布", exact: true }).click();
  await page.getByText("配置已提交（202）", { exact: false }).waitFor();
  await page.getByText("Pause · Accepted", { exact: false }).waitFor();
  check("202 remains Accepted, not Callable success");
  await page.getByRole("button", { name: "请求与用量", exact: true }).click();
  await page.getByText("Token 输入 未知", { exact: false }).waitFor();
  await page.getByLabel("查询类型").selectOption("summary");
  await page.getByText("未知金额占用 520000", { exact: false }).waitFor();
  check("request and currency/price-separated summary with unknown held");
  assert.equal(
    await page.evaluate(() => localStorage.length + sessionStorage.length),
    0,
  );
  check("no browser storage for credentials");
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole("button", { name: "模型目录", exact: true }).click();
  await page.getByText("DeepSeek · 开发样例", { exact: true }).waitFor();
  await page.screenshot({ path: dir + "/catalog-mobile.png", fullPage: true });
  assert.equal(
    await page.evaluate(
      () => document.documentElement.scrollWidth > innerWidth,
    ),
    false,
  );
  check("390px mobile layout without page overflow");
  await page.goto(url + "/?scenario=empty");
  await page
    .getByText("尚无模型。请先提交获准发布配置。", { exact: true })
    .waitFor();
  check("empty catalog");
  await page.goto(url + "/?scenario=login");
  await page
    .getByRole("heading", { name: "登录管理工作台", exact: true })
    .waitFor();
  await page.getByLabel("管理员账号").fill("fixture-admin");
  await page.getByLabel("密码", { exact: true }).fill("fixture-not-a-password");
  await page.getByRole("button", { name: "登录", exact: true }).click();
  await page.getByRole("heading", { name: "模型目录", exact: true }).waitFor();
  await page.getByRole("button", { name: "退出会话", exact: true }).click();
  await page
    .getByRole("heading", { name: "登录管理工作台", exact: true })
    .waitFor();
  check("administrator login and logout, ephemeral password");
  assert.deepEqual(errors, []);
  await fs.writeFile(
    dir + "/browser-results.json",
    JSON.stringify(
      {
        kind: "development_fixture_browser_checks_not_real_model_integration",
        checks,
        errors,
      },
      null,
      2,
    ),
  );
  console.log(JSON.stringify({ checks: checks.length, errors }));
} finally {
  await browser?.close();
  await server.close();
}
