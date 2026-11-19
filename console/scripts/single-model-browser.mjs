import { createServer } from "vite";
import { chromium } from "playwright-core";
import fs from "node:fs/promises";
import assert from "node:assert/strict";
const dir = "artifacts/single-model";
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
  page.setDefaultTimeout(10000);
  page.on("pageerror", (e) => errors.push(e.message));
  for (const mode of ["known", "unknown", "eof", "error", "stop"]) {
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
      const { fixtureFetch, fixtureError, lookupSample, rid } =
        await import("/src/fixtures.ts");
      window.singlePosts = 0;
      window.singleReads = [];
      const known = {
        input_tokens: 12,
        output_tokens: 7,
        total_tokens: 19,
        input_cached_tokens: 4,
        reasoning_tokens: 3,
        source: "upstream",
        missing_reason: null,
      };
      const page = structuredClone(lookupSample);
      page.data[0].status = ["known", "unknown"].includes(mode)
        ? "succeeded"
        : mode === "stop"
          ? "cancelled"
          : "interrupted";
      if (mode === "known") page.data[0].usage = known;
      api.fetcher = async (p, i) => {
        if (String(p).includes("request_id=")) {
          window.singleReads.push(
            new URL(p, location.origin).searchParams.get("request_id"),
          );
          return Response.json(page);
        }
        if (String(p) !== "/v1/chat/completions") return fixtureFetch(p, i);
        window.singlePosts++;
        const event = (text, finish, usage) =>
          "data: " +
          JSON.stringify({
            id: "chatcmpl-" + rid,
            object: "chat.completion.chunk",
            created: 1,
            model: "model-a",
            choices: [
              {
                index: 0,
                delta: { content: text },
                finish_reason: finish ? "stop" : null,
              },
            ],
            ...(usage ? { usage } : {}),
          }) +
          "\n\n";
        const initial = event("单模型受控响应", false);
        if (mode === "stop")
          return new Response(
            new ReadableStream({
              start(c) {
                c.enqueue(new TextEncoder().encode(initial));
                i.signal.addEventListener(
                  "abort",
                  () => c.error(new DOMException("Aborted", "AbortError")),
                  { once: true },
                );
              },
            }),
            {
              headers: {
                "Content-Type": "text/event-stream",
                "X-Request-ID": rid,
              },
            },
          );
        const error = await fixtureError("upstream_error").json();
        const ending =
          mode === "eof"
            ? ""
            : mode === "error"
              ? "event: error\ndata: " + JSON.stringify(error) + "\n\n"
              : event(
                  "完成",
                  true,
                  mode === "known" ? known : page.data[0].usage,
                ) + "data: [DONE]\n\n";
        return new Response(initial + ending, {
          headers: { "Content-Type": "text/event-stream", "X-Request-ID": rid },
        });
      };
    }, mode);
    await page.getByLabel("模型", { exact: false }).selectOption("model-a");
    await page.getByLabel("消费 Key", { exact: true }).fill("fixture-key-only");
    await page.getByLabel("消息", { exact: true }).fill("单模型可重放输入");
    await page.getByRole("button", { name: "发送请求", exact: true }).click();
    if (mode === "stop") {
      await page.getByText("单模型受控响应", { exact: true }).waitFor();
      await page.getByRole("button", { name: "停止传输", exact: true }).click();
    }
    await page.getByText("精确查询：recorded", { exact: false }).waitFor();
    const state =
      mode === "known" || mode === "unknown"
        ? "completed"
        : mode === "stop"
          ? "stopped"
          : "interrupted";
    assert(
      (await page
        .locator("code")
        .filter({ hasText: new RegExp("^" + state + "$") })
        .count()) > 0,
    );
    assert.deepEqual(await page.evaluate(() => window.singleReads), [
      "00000000-0000-4000-8000-000000000001",
    ]);
    assert.equal(await page.evaluate(() => window.singlePosts), 1);
    if (mode === "known")
      await page.getByText("Token：19", { exact: false }).last().waitFor();
    else
      await page
        .getByText("Token：未知 / 不可获取", { exact: false })
        .last()
        .waitFor();
    await page.screenshot({ path: dir + "/" + mode + ".png", fullPage: true });
    checks.push(mode);
  }
  assert.deepEqual(errors, []);
  await fs.writeFile(
    dir + "/results.json",
    JSON.stringify(
      {
        scope:
          "Synthetic replay in actual Vue/Edge; no real Go/Higress/provider inference",
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
