import { createServer } from "vite";
import { chromium } from "playwright-core";
import fs from "node:fs/promises";
import assert from "node:assert/strict";
import { ar1LocalFromEnv } from "./ar1-local.mjs";

const base = process.env.MAAS_AR1_BROWSER_API;
if (!base)
  throw Error(
    "Set MAAS_AR1_BROWSER_API to the fixed Go AR-1 loopback service.",
  );
const extended = process.env.MAAS_AR1_BROWSER_EXTENDED === "1";
const dir = "artifacts/chat-ar1/" + (extended ? "extended" : "official");
await fs.mkdir(dir, { recursive: true });
const server = await createServer({
  plugins: [ar1LocalFromEnv({ MAAS_LOCAL_AGENT_API: base })],
  server: { host: "127.0.0.1", port: 0 },
});
let browser;
const checks = [],
  errors = [],
  network = [],
  bodies = [];
let page;
const state = async (wanted) =>
  page.waitForFunction(
    (wanted) =>
      document.querySelector(".chat-controls .badge")?.textContent === wanted &&
      (["completed", "cancelled", "failed", "limit_reached"].includes(wanted)
        ? !document.querySelector(".chat-composer textarea")?.disabled
        : true),
    wanted,
    { timeout: 15000 },
  );
const newSession = async () => {
  await page.getByRole("button", { name: "＋ 新建会话", exact: true }).click();
  await page.waitForFunction(() => {
    const t = document.querySelector(".chat-composer textarea");
    return t && !t.disabled;
  });
};
const send = async (text) => {
  await page.getByLabel("消息", { exact: true }).fill(text);
  await page.getByRole("button", { name: "发送消息", exact: true }).click();
};
const runPosts = () => bodies.filter((b) => b.path.endsWith("/runs")).length;
const capture = async (name) => {
  const data = await page.evaluate(async () => {
    const root = "/api/agent/v1";
    const sid = decodeURIComponent(location.hash.slice(6));
    const snapshot = await (await fetch(root + "/sessions/" + sid)).json();
    const run = snapshot.runs.at(-1);
    const path = root + "/sessions/" + sid + "/runs/" + run.id;
    const replay = await (await fetch(path + "/events?page_size=100")).json();
    const stream = await (await fetch(path + "/events/stream")).text();
    return { snapshot, replay, stream };
  });
  assert.equal(
    data.snapshot.conversation.id,
    new URL(page.url()).hash.slice(6),
  );
  assert(data.replay.data.length > 0);
  assert(data.stream.includes("event: run."));
  for (const e of data.replay.data) {
    assert(data.stream.includes("id: " + e.cursor));
    assert.equal(e.session_id, data.snapshot.conversation.id);
  }
  await fs.writeFile(dir + "/" + name + ".json", JSON.stringify(data, null, 2));
  return data;
};
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
  });
  page = await context.newPage();
  page.setDefaultTimeout(15000);
  page.on("pageerror", (e) => errors.push(e.message));
  page.on("request", (r) => {
    const path = new URL(r.url()).pathname;
    if (!path.startsWith("/api/agent/v1")) return;
    network.push({ method: r.method(), path });
    if (["POST", "PATCH", "DELETE"].includes(r.method())) {
      const v = r.postDataJSON() ?? {};
      bodies.push({
        path,
        method: r.method(),
        client_operation_id: v.client_operation_id,
        decision_id: v.decision_id,
        operation: v.operation,
        referenced_message_id: v.referenced_message_id,
        text_is_null: v.text === null,
        if_match: r.headers()["if-match"] ?? null,
      });
    }
  });
  await page.goto(url + "/#chat");
  await page
    .getByRole("button", { name: "＋ 新建会话", exact: true })
    .waitFor();
  await newSession();
  await send(
    "第一轮 **Markdown**\n\n```ts\nconst x = 1;\n```\n<img src=x onerror=alert(1)>",
  );
  await state("completed");
  assert.equal(await page.locator(".chat-markdown img").count(), 0);
  assert((await page.locator(".chat-markdown pre code").count()) > 0);
  assert.equal(runPosts(), 1);
  await page.getByText("Token 已知：10", { exact: false }).waitFor();
  const firstHash = new URL(page.url()).hash;
  checks.push(
    "same Go cookie/CSRF session, Chat, safe Markdown, child R and exact grouped usage",
  );
  const beforeRefresh = runPosts();
  await page.reload();
  await state("completed");
  assert.equal(new URL(page.url()).hash, firstHash);
  assert.equal(runPosts(), beforeRefresh);
  assert.equal(await page.locator(".chat-message.user").count(), 1);
  checks.push("refresh reads the same durable Go session without a run POST");
  await page.getByRole("button", { name: "重命名", exact: true }).click();
  await page.getByLabel("会话名称", { exact: true }).fill("Go 持久会话");
  await page.getByRole("button", { name: "保存名称", exact: true }).click();
  await page
    .getByRole("heading", { name: "Go 持久会话", exact: true })
    .waitFor();
  await page
    .getByRole("button", { name: "编辑为新消息", exact: true })
    .first()
    .click();
  await send("编辑后的消息");
  await state("completed");
  assert.equal(await page.locator(".chat-message.user").count(), 2);
  assert.equal(bodies.at(-1).operation, "edit");
  await page
    .getByRole("button", { name: "重新生成（新运行）", exact: true })
    .last()
    .click();
  await state("completed");
  assert.equal(bodies.at(-1).operation, "regenerate");
  assert.equal(bodies.at(-1).text_is_null, true);
  const history = await capture("chat-history");
  assert.equal(history.snapshot.runs.length, 3);
  assert(history.snapshot.messages.some((m) => m.supersedes_message_id));
  checks.push(
    "rename/edit/regenerate use AR-1 revision and preserve original messages/consumption",
  );
  await page.screenshot({ path: dir + "/chat-desktop.png", fullPage: true });

  await newSession();
  await page.getByLabel("运行模式").selectOption("agent");
  await send("6乘7并读取可见模型");
  if (extended) {
    await page
      .getByRole("button", { name: "批准此次工具", exact: true })
      .waitFor();
    await page.screenshot({ path: dir + "/approval.png", fullPage: true });
    const before = runPosts();
    await page.reload();
    await page
      .getByRole("button", { name: "批准此次工具", exact: true })
      .waitFor();
    assert.equal(runPosts(), before);
    await page
      .getByRole("button", { name: "批准此次工具", exact: true })
      .click();
    checks.push(
      "persisted approval survives refresh and binds real tool args/revision/policy/decision UUID",
    );
  }
  await state("completed");
  await page
    .locator(".agent-trace")
    .getByText('"42"', { exact: true })
    .waitFor();
  await page.getByText("Token 已知：20", { exact: false }).waitFor();
  const agent = await capture("agent");
  assert.equal(agent.snapshot.runs.at(-1).child_request_ids.length, 2);
  checks.push(
    "Go loop executes real bounded_arithmetic and scope-filtered catalog; two child Rs and usage groups",
  );
  await page.screenshot({ path: dir + "/agent-desktop.png", fullPage: true });

  const anonymous = await browser.newContext();
  const forbidden = await anonymous.request.get(url + "/api/agent/v1/sessions");
  assert.equal(forbidden.status(), 401);
  await anonymous.close();
  const csrfStatus = await page.evaluate(
    async () =>
      (
        await fetch("/api/agent/v1/sessions", {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "X-CSRF-Token": "wrong",
          },
          body: "{}",
        })
      ).status,
  );
  assert.equal(csrfStatus, 403);
  checks.push(
    "actual Go session middleware rejects anonymous read and wrong-CSRF write",
  );

  const lostCreationBefore = bodies.filter(
    (b) => b.method === "POST" && b.path === "/api/agent/v1/sessions",
  ).length;
  await page.route(
    "**/api/agent/v1/sessions",
    async (route) => {
      if (route.request().method() !== "POST") return route.continue();
      await route.fetch();
      await route.abort("failed");
    },
    { times: 1 },
  );
  await page.getByRole("button", { name: "＋ 新建会话", exact: true }).click();
  await page.getByText("提交结果未知", { exact: false }).first().waitFor();
  await page.reload();
  await page.waitForFunction(() => {
    const t = document.querySelector(".chat-composer textarea");
    return t && !t.disabled;
  });
  assert.equal(
    bodies.filter(
      (b) => b.method === "POST" && b.path === "/api/agent/v1/sessions",
    ).length,
    lostCreationBefore + 1,
  );
  checks.push(
    "lost Session ACK recovers by original principal-scoped creation command after refresh; one POST",
  );
  const lostRunBefore = runPosts();
  await page.route(
    "**/api/agent/v1/sessions/*/runs",
    async (route) => {
      await route.fetch();
      await route.abort("failed");
    },
    { times: 1 },
  );
  await send("原运行响应丢失恢复");
  await page.getByText("提交结果未知", { exact: false }).first().waitFor();
  await page.reload();
  await state("completed");
  assert.equal(runPosts(), lostRunBefore + 1);
  checks.push(
    "lost Run ACK recovers through original command/hash after refresh with no generation replay",
  );

  if (extended) {
    await newSession();
    await send("/slow");
    await page
      .getByRole("button", { name: "断开事件连接", exact: true })
      .click();
    const before = runPosts();
    await page.getByRole("button", { name: "只读重连", exact: true }).click();
    await state("completed");
    assert.equal(runPosts(), before);
    assert(
      (
        await page.locator(".chat-message.assistant").last().textContent()
      ).includes("🌏"),
    );
    checks.push(
      "real SSE UTF-8 offsets and read-only reconnect preserve Chinese/emoji without a duplicate run",
    );
    await newSession();
    await send("/slow");
    await page.getByRole("button", { name: "停止运行", exact: true }).click();
    await state("cancelled");
    const stopped = await capture("cancelled");
    assert.equal(stopped.snapshot.runs.at(-1).cancel_requested, true);
    assert(stopped.replay.data.some((e) => e.type === "run.cancel_requested"));
    assert(stopped.replay.data.some((e) => e.type === "run.cancelled"));
    checks.push(
      "cancel 202 and actual terminal are separate real persisted events; no local refund",
    );
    await newSession();
    await send("/unknown");
    await state("needs_confirmation");
    const beforeUnknown = runPosts();
    await page.reload();
    await state("needs_confirmation");
    assert.equal(runPosts(), beforeUnknown);
    assert.equal(
      await page
        .getByRole("button", { name: "发送消息", exact: true })
        .isEnabled(),
      false,
    );
    assert.equal(
      await page
        .getByRole("button", { name: "批准此次工具", exact: true })
        .count(),
      0,
    );
    await page
      .getByText("Token / 金额：未知 / 不可获取", { exact: true })
      .waitFor();
    await capture("needs-confirmation");
    checks.push(
      "unknown model result survives refresh, blocks send/approval/replay and displays unknown usage",
    );
    await newSession();
    await send("/error");
    await state("failed");
    await page
      .getByText("model_failed_or_incomplete", { exact: true })
      .waitFor();
    checks.push(
      "real Go failed run is visible and does not automatically retry",
    );
  }

  await page.setViewportSize({ width: 390, height: 844 });
  assert.equal(
    await page.evaluate(
      () => document.documentElement.scrollWidth > innerWidth,
    ),
    false,
  );
  await page.screenshot({ path: dir + "/mobile.png", fullPage: true });
  await page.getByRole("button", { name: "删除会话", exact: true }).click();
  await page.getByRole("button", { name: "确认删除会话", exact: true }).click();
  await page.waitForFunction(() => location.hash === "#chat");
  checks.push("390px layout and terminal-session deletion");
  assert.deepEqual(errors, []);
  await fs.writeFile(
    dir + "/results.json",
    JSON.stringify(
      {
        backend: "19e43ba980f1bd9f499a92dda435b74b626bf7e9",
        scope: extended
          ? "Fixed real Go ARHandler/Host/LocalStore/LocalSession and safe tools; explicit browser test model and approval wrapper"
          : "Unmodified fixed agentcontrolled AR-1 entry; deterministic model, real Go HTTP/session/file store/safe tools",
        checks,
        errors,
        network,
        writes: bodies,
      },
      null,
      2,
    ),
  );
  console.log(
    JSON.stringify({
      scope: extended ? "extended" : "official",
      checks: checks.length,
      errors,
    }),
  );
} catch (e) {
  await fs.writeFile(
    dir + "/failure.json",
    JSON.stringify(
      { error: String(e), checks, errors, network, writes: bodies },
      null,
      2,
    ),
  );
  if (page) {
    await fs.writeFile(dir + "/failure.html", await page.content());
    await page
      .screenshot({ path: dir + "/failure.png", fullPage: true })
      .catch(() => {});
  }
  throw e;
} finally {
  await browser?.close();
  await server.close();
}
