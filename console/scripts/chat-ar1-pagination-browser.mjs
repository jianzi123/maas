import { createServer } from "vite";
import { chromium } from "playwright-core";
import fs from "node:fs/promises";
import assert from "node:assert/strict";
import { ar1LocalFromEnv } from "./ar1-local.mjs";
const base = process.env.MAAS_AR1_BROWSER_API;
if (!base) throw Error("Fixed disposable Go AR-1 required");
const dir = "artifacts/chat-ar1-pagination";
await fs.mkdir(dir, { recursive: true });
const server = await createServer({
  plugins: [ar1LocalFromEnv({ MAAS_LOCAL_AGENT_API: base })],
  server: { host: "127.0.0.1", port: 0 },
});
let browser, page;
const checks = [],
  errors = [],
  responses = [],
  network = [];
try {
  await server.listen();
  const url = "http://127.0.0.1:" + server.httpServer.address().port;
  browser = await chromium.launch({
    executablePath:
      process.env.EDGE_PATH ||
      "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
    headless: true,
  });
  page = await browser.newPage();
  page.setDefaultTimeout(15000);
  page.on("pageerror", (e) => errors.push(e.message));
  page.on("request", (r) => {
    if (r.url().includes("/api/agent/v1"))
      network.push({ method: r.method(), path: new URL(r.url()).pathname });
  });
  await page.goto(url + "/#chat");
  await page.getByRole("button", { name: "＋ 新建会话", exact: true }).click();
  await page.waitForFunction(() => location.hash.startsWith("#chat/"));
  const sid = decodeURIComponent(new URL(page.url()).hash.slice(6)),
    root = url + "/api/agent/v1/sessions/" + sid;
  const csrf = await page.evaluate(async () => {
    const { api } = await import("/src/api/client.ts");
    return api.csrf;
  });
  const headers = {
    "Content-Type": "application/json",
    Origin: url,
    "X-CSRF-Token": csrf,
  };
  const context = page.context();
  async function snap() {
    const r = await context.request.get(root);
    assert.equal(r.status(), 200);
    return r.json();
  }
  const limits = {
    max_steps: 4,
    max_model_calls: 1,
    max_tool_calls: 8,
    max_duration_ms: 10000,
    tool_timeout_ms: 1000,
    max_tool_output_bytes: 8192,
    max_context_tokens: 32768,
    no_progress_limit: 3,
    max_tokens: "100",
    max_money_atomic: "100",
    currency: "TST",
  };
  async function generate(
    text = "/history",
    operation = "send",
    reference = null,
  ) {
    const s = await snap();
    const r = await context.request.post(root + "/runs", {
      headers: { ...headers, "If-Match": '"' + s.conversation.revision + '"' },
      data: {
        client_operation_id: crypto.randomUUID(),
        mode: "chat",
        operation,
        text,
        referenced_message_id: reference,
        model_alias: "demo",
        limits,
        tools: [],
      },
    });
    assert.equal(r.status(), 202);
    const ack = await r.json();
    for (let i = 0; i < 200; i++) {
      const s = await snap(),
        run = s.runs.find((r) => r.id === ack.run.id);
      if (["completed", "failed", "limit_reached"].includes(run.state)) {
        assert.equal(run.state, "completed");
        return ack;
      }
      await page.waitForTimeout(20);
    }
    throw Error("Controlled run did not terminate");
  }
  async function load() {
    await page.reload();
    await page.getByRole("button", { name: "发送消息", exact: true }).waitFor();
  }
  for (let i = 0; i < 49; i++) await generate();
  await load();
  await page.waitForFunction(
    () => document.querySelectorAll(".chat-message").length === 98,
  );
  checks.push("98 historical messages via ordinary Go Run commands");
  await generate();
  await load();
  await page.waitForFunction(
    () => document.querySelectorAll(".chat-message").length === 100,
  );
  checks.push("100-message Snapshot boundary");
  await generate();
  let expired = 0;
  await page.route("**/messages?**", async (route) => {
    if (!expired) {
      expired++;
      const s = await snap();
      const r = await context.request.patch(root, {
        headers: {
          ...headers,
          "If-Match": '"' + s.conversation.revision + '"',
        },
        data: { title: "分页修订变化" },
      });
      assert.equal(r.status(), 200);
    }
    const r = await route.fetch();
    if (r.status() === 410) {
      const e = await r.json();
      assert.equal(e.error.code, "cursor_expired");
      assert.equal(e.error.snapshot_required, true);
      assert.equal(e.error.retryable, false);
      responses.push(e);
    }
    await route.fulfill({ response: r });
  });
  const before = network.filter(
    (n) => n.method === "POST" && n.path.endsWith("/runs"),
  ).length;
  await load();
  await page.waitForFunction(
    () => document.querySelectorAll(".chat-message").length === 102,
  );
  assert.equal(responses.length, 1);
  assert.equal(
    network.filter((n) => n.method === "POST" && n.path.endsWith("/runs"))
      .length,
    before,
  );
  checks.push(
    "MessagePage real 410 restarts Snapshot without POST, no missing/duplicate 102 messages",
  );
  await page.unroute("**/messages?**");
  await page.getByLabel("消息", { exact: true }).fill("中文🙂末尾");
  const accepted = page.waitForResponse(
    (r) =>
      r.request().method() === "POST" &&
      new URL(r.url()).pathname.endsWith("/runs"),
  );
  await page.getByRole("button", { name: "发送消息", exact: true }).click();
  const ack = await accepted;
  assert.equal(ack.status(), 202);
  const sentRun = (await ack.json()).run.id;
  let quiescent = false;
  for (let i = 0; i < 150; i++) {
    const s = await snap();
    if (
      !s.conversation.active_run_id &&
      s.runs.at(-1)?.id === sentRun &&
      s.runs.at(-1)?.state === "completed"
    ) {
      quiescent = true;
      break;
    }
    await page.waitForTimeout(20);
  }
  assert(
    quiescent,
    "current Chinese run must reach its persisted terminal before edit",
  );
  const reconnect = page.getByRole("button", { name: "只读重连", exact: true });
  if (await reconnect.isVisible()) await reconnect.click();
  await page.waitForFunction(
    () => document.querySelectorAll(".chat-message").length === 104,
  );
  await page.waitForFunction(
    () =>
      document.querySelector(".chat-controls .badge")?.textContent ===
      "completed",
  );
  const texts = await page
    .locator(".chat-message.assistant .chat-markdown")
    .allTextContents();
  assert(texts.at(-1).includes("你好，🌏。"));
  checks.push(
    "Chinese/emoji terminal recovers after bounded revision churn by explicit GET reconnect",
  );
  const eventResponse = await context.request.get(
    root + "/runs/" + sentRun + "/events?page_size=100",
  );
  assert.equal(eventResponse.status(), 200);
  const eventPage = await eventResponse.json();
  assert.equal(eventPage.next_cursor, null);
  let deltaText = "";
  for (const event of eventPage.data) {
    assert.equal(event.run_id, sentRun);
    if (event.type === "message.delta") {
      assert.equal(
        BigInt(event.data.offset),
        BigInt(Buffer.byteLength(deltaText)),
      );
      deltaText += event.data.text;
    }
  }
  assert(deltaText.includes("你好，🌏。"));
  await fs.writeFile(
    dir + "/chinese-events.json",
    JSON.stringify(eventPage, null, 2),
  );
  assert.equal(
    network.filter((n) => n.method === "POST" && n.path.endsWith("/runs"))
      .length,
    before + 1,
  );
  checks.push(
    "same Run persisted Chinese/emoji delta UTF-8 offsets, read recovery adds zero Run POST",
  );
  const original = (await snap()).messages.find((m) => m.role === "user");
  await generate("编辑中文🙂", "edit", original.id);
  await load();
  await page.waitForFunction(
    () => document.querySelectorAll(".chat-message").length === 106,
  );
  const ids = await page
    .locator(".chat-message")
    .evaluateAll((elements) => elements.map((e) => e.textContent));
  assert.equal(ids.length, 106);
  checks.push("normal edit command retained history and refresh projection");
  await page.locator(".chat-message").last().scrollIntoViewIfNeeded();
  await page.screenshot({ path: dir + "/history.png", fullPage: false });
  assert.deepEqual(errors, []);
  await fs.writeFile(
    dir + "/results.json",
    JSON.stringify(
      {
        backend: "a4c1347b6e01ed6fdf9925cf9ee26cb82251c405",
        scope:
          "Actual ARHandler/Host/Go file storage/Cookie/CSRF. Synthetic ModelClient, approval and message-count context adapter; no provider",
        checks,
        errors,
        responses,
        network,
      },
      null,
      2,
    ),
  );
  console.log(
    JSON.stringify({ checks: checks.length, pageErrors: errors.length }),
  );
} catch (error) {
  await fs.writeFile(
    dir + "/failure.json",
    JSON.stringify(
      {
        message: error.message,
        checks,
        errors,
        network,
        body: await page
          ?.locator("body")
          .innerText()
          .catch(() => ""),
      },
      null,
      2,
    ),
  );
  await page?.screenshot({ path: dir + "/failure.png" }).catch(() => {});
  throw error;
} finally {
  await browser?.close();
  await server.close();
}
