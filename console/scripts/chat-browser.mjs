import { createServer } from "vite";
import { chromium } from "playwright-core";
import fs from "node:fs/promises";
import assert from "node:assert/strict";
const dir = "artifacts/chat";
await fs.mkdir(dir, { recursive: true });
const server = await createServer({
  server: { host: "127.0.0.1", port: 0 },
  define: { "import.meta.env.VITE_CONSOLE_FIXTURES": JSON.stringify("true") },
});
let browser;
const checks = [],
  errors = [];
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
  await page.goto(url);
  await page
    .getByRole("navigation")
    .getByRole("button", { name: "Chat 工作台", exact: true })
    .click();
  await page.getByRole("button", { name: "＋ 新建会话", exact: true }).click();
  await page
    .getByLabel("消息", { exact: true })
    .fill("第一轮 **Markdown** <img src=x onerror=alert(1)>");
  await page.getByRole("button", { name: "发送消息", exact: true }).click();
  await page.getByText("completed", { exact: true }).waitFor();
  assert.equal(await page.locator(".chat-markdown img").count(), 0);
  assert((await page.locator(".chat-markdown pre code").count()) > 0);
  checks.push("stream Markdown/code rendered and unsafe HTML stripped");
  const originalHash = new URL(page.url()).hash;
  await page.getByLabel("消息", { exact: true }).fill("第二轮消息");
  await page.getByRole("button", { name: "发送消息", exact: true }).click();
  await page.getByText("completed", { exact: true }).waitFor();
  await page.getByText("这是第", { exact: false }).last().waitFor();
  assert.equal(await page.locator(".chat-message").count(), 4);
  checks.push("multi-turn conversation persisted");
  await page.reload();
  await page.locator(".chat-message").nth(3).waitFor();
  assert.equal(new URL(page.url()).hash, originalHash);
  checks.push("refresh restores session and original messages");
  await page.getByRole("button", { name: "重命名", exact: true }).click();
  await page.getByLabel("会话名称", { exact: true }).fill("我的持久会话");
  await page.getByRole("button", { name: "保存名称", exact: true }).click();
  await page
    .getByRole("heading", { name: "我的持久会话", exact: true })
    .waitFor();
  checks.push("rename");
  await page.screenshot({ path: dir + "/chat-desktop.png", fullPage: true });
  await page
    .getByRole("button", { name: "编辑为新消息", exact: true })
    .first()
    .click();
  await page.getByLabel("消息", { exact: true }).fill("编辑后的新消息");
  await page.getByRole("button", { name: "发送消息", exact: true }).click();
  await page.getByText("completed", { exact: true }).waitFor();
  assert.equal(await page.locator(".chat-message").count(), 6);
  await page.getByText("修订关联：", { exact: false }).waitFor();
  checks.push("edit keeps original message and new lineage");
  await page
    .getByRole("button", { name: "重新生成（新运行）", exact: true })
    .last()
    .click();
  await page.getByText("completed", { exact: true }).waitFor();
  assert.equal(await page.locator(".chat-message").count(), 8);
  checks.push("explicit regenerate creates linked run");
  await page.getByLabel("消息", { exact: true }).fill("停止测试");
  await page.getByRole("button", { name: "发送消息", exact: true }).click();
  await page.getByRole("button", { name: "停止运行", exact: true }).click();
  await page.getByText("cancelled", { exact: true }).waitFor();
  checks.push("stop current run without replay");
  await page.getByLabel("运行模式", { exact: false }).selectOption("agent");
  await page.getByLabel("消息", { exact: true }).fill("Agent工具测试");
  await page.getByRole("button", { name: "发送消息", exact: true }).click();
  await page
    .getByRole("button", { name: "批准此次工具", exact: true })
    .waitFor();
  await page.screenshot({ path: dir + "/agent-approval.png", fullPage: true });
  await page.reload();
  await page
    .getByRole("button", { name: "批准此次工具", exact: true })
    .waitFor();
  checks.push("Agent approval checkpoint survives refresh");
  await page.getByRole("button", { name: "批准此次工具", exact: true }).click();
  await page.getByText("completed", { exact: true }).first().waitFor();
  await page.getByText('{"characters":', { exact: false }).waitFor();
  checks.push("pure computation result and Agent steps");
  await page.getByLabel("消息", { exact: true }).fill("重连测试");
  await page.getByRole("button", { name: "发送消息", exact: true }).click();
  await page.getByRole("button", { name: "断开事件连接", exact: true }).click();
  await page.getByRole("button", { name: "只读重连", exact: true }).click();
  await page.getByText("completed", { exact: true }).first().waitFor();
  checks.push("read-only event reconnect");
  await page.getByLabel("消息", { exact: true }).fill("/error");
  await page.getByRole("button", { name: "发送消息", exact: true }).click();
  await page.getByText("failed", { exact: true }).waitFor();
  await page.getByText("开发模型模拟上游失败", { exact: false }).waitFor();
  checks.push("failure visible and no automatic generation");
  await page.screenshot({ path: dir + "/chat-error.png", fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({ path: dir + "/chat-mobile.png", fullPage: true });
  assert.equal(
    await page.evaluate(
      () => document.documentElement.scrollWidth > innerWidth,
    ),
    false,
  );
  checks.push("390px layout");
  await page.getByRole("button", { name: "删除会话", exact: true }).click();
  await page.getByRole("button", { name: "确认删除会话", exact: true }).click();
  await page.getByText("暂无会话", { exact: true }).waitFor();
  checks.push("delete session");
  assert.deepEqual(errors, []);
  await fs.writeFile(
    dir + "/results.json",
    JSON.stringify(
      {
        scope:
          "Explicit browser-local development adapter; no Go session service or real model",
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
