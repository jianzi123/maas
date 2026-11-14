import { createServer } from "vite";
import { chromium } from "playwright-core";
import fs from "node:fs/promises";
import assert from "node:assert/strict";
const dir = "artifacts/consumer-binding";
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
    viewport: { width: 1440, height: 1050 },
  });
  page.setDefaultTimeout(10000);
  page.on("pageerror", (e) => errors.push(e.message));
  for (const mode of [
    "same-created",
    "changed-created",
    "wrong-http-id",
    "matching-http-id",
    "missing-http-id",
  ]) {
    await page.goto(url);
    await page
      .getByRole("heading", { name: "模型目录", exact: true })
      .waitFor();
    await page
      .getByRole("navigation")
      .getByRole("button", { name: "在线试用", exact: true })
      .click();
    await page.evaluate(async (mode) => {
      const { api } = await import("/src/api/client.ts");
      const { fixtureFetch, fixtureError, rid } =
        await import("/src/fixtures.ts");
      window.consumerReads = [];
      window.consumerPosts = 0;
      api.fetcher = async (p, i) => {
        if (String(p).includes("request_id="))
          window.consumerReads.push(
            new URL(String(p), location.origin).searchParams.get("request_id"),
          );
        if (String(p) !== "/v1/chat/completions") return fixtureFetch(p, i);
        window.consumerPosts++;
        if (mode.includes("http-id")) {
          const body = await fixtureError("token_budget_exceeded", 429).json();
          body.error.request_id =
            mode === "wrong-http-id"
              ? "00000000-0000-4000-8000-000000000022"
              : rid;
          body.error.retry_after_seconds = 7;
          return Response.json(body, {
            status: 429,
            headers: mode === "missing-http-id" ? {} : { "X-Request-ID": rid },
          });
        }
        const frame = (created, content, finish) =>
          "data: " +
          JSON.stringify({
            id: "chatcmpl-" + rid,
            object: "chat.completion.chunk",
            model: "model-a",
            created,
            choices: [
              {
                index: 0,
                delta: { content },
                finish_reason: finish ? "stop" : null,
              },
            ],
          }) +
          "\r\n\r\n";
        return new Response(
          frame(0, "首片可见", false) +
            frame(mode === "changed-created" ? 1 : 0, "后片内容", true) +
            "data: [DONE]\n\n",
          {
            headers: {
              "Content-Type": "text/event-stream",
              "X-Request-ID": rid,
            },
          },
        );
      };
    }, mode);
    await page.getByLabel("模型", { exact: false }).selectOption("model-a");
    await page.getByLabel("消费 Key", { exact: true }).fill("fixture-only-key");
    await page.getByLabel("消息", { exact: true }).fill("消费者关联验证");
    await page.getByRole("button", { name: "发送请求", exact: true }).click();
    const state = mode === "same-created" ? "completed" : "interrupted";
    await page
      .locator(".title-row .badge")
      .filter({ hasText: state })
      .waitFor();
    if (mode === "missing-http-id") {
      await page
        .getByText("未收到可信原请求 ID，结果未知。", { exact: false })
        .waitFor();
      assert.deepEqual(await page.evaluate(() => window.consumerReads), []);
    } else {
      await page.getByText("精确查询：recorded", { exact: false }).waitFor();
      assert.deepEqual(await page.evaluate(() => window.consumerReads), [
        "00000000-0000-4000-8000-000000000001",
      ]);
    }
    if (mode === "changed-created") {
      assert.equal(await page.locator(".answer pre").textContent(), "首片可见");
      await page
        .getByText("服务响应不符合当前契约。", { exact: false })
        .waitFor();
    }
    if (mode === "wrong-http-id") {
      await page
        .getByText("服务响应不符合当前契约。", { exact: false })
        .waitFor();
      assert.equal(
        await page.getByText("Token 预算不足。", { exact: false }).count(),
        0,
      );
    }
    if (mode === "matching-http-id") {
      await page.getByText("Token 预算不足。", { exact: false }).waitFor();
      await page.getByText("7 秒", { exact: false }).waitFor();
    }
    assert.equal(await page.evaluate(() => window.consumerPosts), 1);
    await page.screenshot({ path: dir + "/" + mode + ".png", fullPage: true });
    checks.push(mode);
  }
  assert.deepEqual(errors, []);
  await fs.writeFile(
    dir + "/results.json",
    JSON.stringify(
      {
        scope:
          "Development synthetic HTTP/SSE responses in real Edge browser; no Go or model inference",
        checks,
        errors,
      },
      null,
      2,
    ),
  );
  console.log(
    JSON.stringify({ checks: checks.length, pageErrors: errors.length }),
  );
} finally {
  await browser?.close();
  await server.close();
}
