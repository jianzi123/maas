// Read-only by default. Run against an explicitly authorized installed site.
import { chromium } from "playwright-core";
import fs from "node:fs/promises";
import assert from "node:assert/strict";
const raw = process.env.MAAS_CONSOLE_URL;
if (!raw)
  throw Error("Set MAAS_CONSOLE_URL to the authorized installed origin");
const origin = new URL(raw);
if (
  !["http:", "https:"].includes(origin.protocol) ||
  origin.username ||
  origin.password ||
  origin.pathname !== "/" ||
  origin.search ||
  origin.hash
)
  throw Error(
    "MAAS_CONSOLE_URL must be one HTTP(S) origin, without credentials or a path",
  );
if (!process.env.MAAS_SMOKE_USERNAME || !process.env.MAAS_SMOKE_PASSWORD)
  throw Error(
    "Set temporary administrator credentials in MAAS_SMOKE_USERNAME/PASSWORD; never put them in CLI args or logs",
  );
const dir = "artifacts/deployed-site";
await fs.mkdir(dir, { recursive: true });
const checks = [],
  network = [],
  errors = [];
let browser, page;
try {
  browser = await chromium.launch({
    executablePath:
      process.env.EDGE_PATH ||
      "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
    headless: true,
  });
  page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  page.on("pageerror", (e) => errors.push(e.message));
  page.on("request", (r) => {
    const u = new URL(r.url());
    if (u.origin === origin.origin && u.pathname.startsWith("/api/"))
      network.push({ method: r.method(), path: u.pathname });
  });
  const sid = process.env.MAAS_SMOKE_SESSION_ID;
  await page.goto(
    origin.origin + "/#chat" + (sid ? "/" + encodeURIComponent(sid) : ""),
  );
  await page
    .getByLabel("管理员账号", { exact: true })
    .fill(process.env.MAAS_SMOKE_USERNAME);
  await page
    .getByLabel("密码", { exact: true })
    .fill(process.env.MAAS_SMOKE_PASSWORD);
  await page.getByRole("button", { name: "登录", exact: true }).click();
  await page
    .getByRole("button", { name: "＋ 新建会话", exact: true })
    .waitFor();
  const config = await page.evaluate(async () => {
    const r = await fetch("/console-config.json", {
      cache: "no-store",
      redirect: "error",
    });
    return { status: r.status, value: await r.json() };
  });
  assert.equal(config.status, 200);
  assert.equal(config.value.chat.enabled, true);
  const caps = await page.evaluate(async () => {
    const r = await fetch("/api/agent/v1/capabilities", {
      cache: "no-store",
      redirect: "error",
    });
    if (!r.ok) throw Error("Capabilities unavailable: " + r.status);
    return r.json();
  });
  assert.equal(caps.protocol_revision, "ar.api/1.0");
  checks.push(
    "Installed runtime config, real same-origin login and AR-1 capabilities",
  );
  const runPosts = () =>
    network.filter((r) => r.method === "POST" && r.path.endsWith("/runs"))
      .length;
  if (process.env.MAAS_SMOKE_SEND === "1") {
    // This switch is an action request, never an authorization for a paid provider.
    if (!process.env.MAAS_SMOKE_MODEL)
      throw Error("Generation requires an explicit approved MAAS_SMOKE_MODEL");
    const created = page.waitForResponse(
      (r) =>
        r.request().method() === "POST" &&
        new URL(r.url()).pathname === "/api/agent/v1/sessions",
    );
    await page
      .getByRole("button", { name: "＋ 新建会话", exact: true })
      .click();
    const newSession = await created;
    assert.equal(newSession.status(), 201);
    const createdId = (await newSession.json()).id;
    await page.waitForFunction(
      (id) => location.hash === "#chat/" + encodeURIComponent(id),
      createdId,
    );
    await page.getByLabel("消息", { exact: true }).waitFor();
    await page
      .locator(".chat-controls select")
      .nth(1)
      .selectOption(process.env.MAAS_SMOKE_MODEL);
    const mode = process.env.MAAS_SMOKE_MODE || "chat";
    assert(["chat", "agent"].includes(mode));
    await page.locator(".chat-controls select").nth(0).selectOption(mode);
    await page
      .getByLabel("消息", { exact: true })
      .fill(
        process.env.MAAS_SMOKE_PROMPT || "请用中文确认连接正常，并输出一个🙂。",
      );
    await page.getByRole("button", { name: "发送消息", exact: true }).click();
    await page.waitForFunction(
      () =>
        [
          "completed",
          "failed",
          "cancelled",
          "limit_reached",
          "waiting_approval",
          "needs_confirmation",
        ].includes(
          document.querySelector(".chat-controls .badge")?.textContent,
        ),
      null,
      { timeout: 90000 },
    );
    const state = await page
      .locator(".chat-controls .badge")
      .first()
      .textContent();
    assert.equal(
      runPosts(),
      1,
      "one explicitly requested generation, no retry",
    );
    checks.push(
      "Explicit " + mode + " Run reaches authoritative state: " + state,
    );
    if (state === "waiting_approval")
      checks.push(
        "Approval displayed only; this smoke never approves or reruns unknown tools",
      );
  } else if (!sid && (await page.locator(".chat-session").count())) {
    await page.locator(".chat-session").first().click();
    await page.waitForFunction(() => location.hash.startsWith("#chat/"));
  }
  const before = runPosts(),
    hash = new URL(page.url()).hash;
  await page.reload();
  await page
    .getByRole("button", { name: "＋ 新建会话", exact: true })
    .waitFor();
  assert.equal(new URL(page.url()).hash, hash);
  assert.equal(runPosts(), before);
  checks.push(
    "Installed refresh keeps session URL; GET recovery adds no generation",
  );
  await page.screenshot({ path: dir + "/console.png", fullPage: false });
  await page.getByRole("button", { name: "退出会话", exact: true }).click();
  await page.getByRole("button", { name: "登录", exact: true }).waitFor();
  checks.push(
    "Temporary application session logged out with the same CSRF source",
  );
  assert.deepEqual(errors, []);
  await fs.writeFile(
    dir + "/results.json",
    JSON.stringify(
      {
        scope:
          "Installed site browser smoke; profile and SQL/restart evidence must be supplied by the delivery owner",
        origin: origin.origin,
        checks,
        errors,
        network,
        generationEnabled: process.env.MAAS_SMOKE_SEND === "1",
        notExecuted: [
          "Application/MySQL restarts",
          "Independent QA",
          "Paid/real provider acceptance unless separately authorized and recorded",
        ],
      },
      null,
      2,
    ),
  );
  console.log(
    JSON.stringify({
      checks: checks.length,
      pageErrors: errors.length,
      runPosts: runPosts(),
    }),
  );
} finally {
  await browser?.close();
}
