// Bounded browser checks; synthetic fetch/SSE only, no Go/model/cluster.
import { createServer } from "vite";
import { chromium } from "playwright-core";
import fs from "node:fs/promises";
import assert from "node:assert/strict";
const dir = "artifacts/review-recovery";
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
  const open = async () => {
    await page.goto(url);
    await page
      .getByRole("heading", { name: "模型目录", exact: true })
      .waitFor();
  };
  for (const outcome of ["Succeeded", "Running"]) {
    await open();
    await page.evaluate(async (outcome) => {
      const { api } = await import("/src/api/client.ts");
      const { fixtureFetch } = await import("/src/fixtures.ts");
      let original;
      window.reviewTrace = { writes: 0, operationReads: [] };
      api.fetcher = async (p, i) => {
        if (String(p).includes("/release-operations/")) {
          window.reviewTrace.operationReads.push(String(p));
          return Response.json({ ...original, state: outcome });
        }
        const response = await fixtureFetch(p, i);
        if (i?.method === "PUT") {
          window.reviewTrace.writes++;
          const ack = await response.json();
          ack.operation.state = "Unknown";
          original = structuredClone(ack.operation);
          ack.resource = null;
          return Response.json(ack, { status: 202 });
        }
        return response;
      };
    }, outcome);
    await page
      .getByRole("navigation")
      .getByRole("button", { name: "模型发布", exact: true })
      .click();
    await page.locator(".release-card").first().click();
    await page.getByRole("button", { name: "暂停发布", exact: true }).click();
    await page
      .getByText("原操作写入结果未知（202）", { exact: false })
      .waitFor();
    assert(
      await page
        .getByRole("button", { name: "编辑配置", exact: true })
        .isDisabled(),
    );
    await page.getByRole("button", { name: "查询原操作", exact: true }).click();
    await page
      .getByText(
        outcome === "Succeeded"
          ? "原操作已确认 Succeeded；"
          : "原操作尚未确认终态；",
        { exact: false },
      )
      .waitFor();
    assert(
      await page
        .getByRole("button", { name: "编辑配置", exact: true })
        .isDisabled(),
    );
    await page
      .getByRole("button", { name: "重读当前 CR", exact: true })
      .click();
    if (outcome === "Succeeded") {
      await page.getByText("当前 CR 已重读；", { exact: false }).waitFor();
      assert(
        await page
          .getByRole("button", { name: "编辑配置", exact: true })
          .isEnabled(),
      );
    } else {
      await page.getByText("写入结果未知。当前 CR", { exact: false }).waitFor();
      assert(
        await page
          .getByRole("button", { name: "编辑配置", exact: true })
          .isDisabled(),
      );
    }
    const trace = await page.evaluate(() => window.reviewTrace);
    assert.equal(trace.writes, 1);
    assert.equal(trace.operationReads.length, 1);
    checks.push({ kind: "operation", outcome, ...trace });
    await page.screenshot({
      path: `${dir}/operation-${outcome}.png`,
      fullPage: true,
    });
  }
  for (const kind of ["requests", "summary"]) {
    await open();
    await page.evaluate(async () => {
      const { api } = await import("/src/api/client.ts");
      const { fixtureFetch, fixtureError } = await import("/src/fixtures.ts");
      api.fetcher = async (p, i) => {
        if (String(p).includes("model_alias=failed-filter"))
          return fixtureError("dependency_unavailable", 503);
        return fixtureFetch(p, i);
      };
    });
    await page
      .getByRole("navigation")
      .getByRole("button", { name: "请求与用量", exact: true })
      .click();
    if (kind === "summary")
      await page.getByLabel("查询类型").selectOption("summary");
    await page.getByText("本次查询数据完整", { exact: false }).waitFor();
    await page.getByLabel("模型别名", { exact: true }).fill("failed-filter");
    await page.getByRole("button", { name: "查询", exact: true }).click();
    await page.getByRole("alert").waitFor();
    assert.equal(await page.locator("article").count(), 0);
    assert(
      !(await page.locator("body").innerText()).includes("本次查询数据完整"),
    );
    await page.screenshot({
      path: `${dir}/usage-${kind}-503.png`,
      fullPage: true,
    });
    await page.getByLabel("模型别名", { exact: true }).fill("");
    await page.getByRole("button", { name: "查询", exact: true }).click();
    await page.getByText("本次查询数据完整", { exact: false }).waitFor();
    assert.equal(await page.locator("article").count(), 1);
    checks.push({
      kind: "usage",
      query: kind,
      clearedOn503: true,
      recovered: true,
    });
  }
  for (const finalOnly of [false, true]) {
    const observed = await page.evaluate(async (finalOnly) => {
      const { Api } = await import("/src/api/client.ts");
      const { streamChat } = await import("/src/api/stream.ts");
      const { rid, lookupSample } = await import("/src/fixtures.ts");
      const frame = (choices, usage) =>
        "data: " +
        JSON.stringify({
          id: "chatcmpl-" + rid,
          object: "chat.completion.chunk",
          model: "model-a",
          created: 1,
          choices,
          ...(usage ? { usage } : {}),
        }) +
        "\n\n";
      const body =
        frame([{ index: 0, delta: {}, finish_reason: "stop" }]) +
        (finalOnly
          ? frame([], lookupSample.data[0].usage)
          : frame([
              { index: 0, delta: { content: "ILLEGAL" }, finish_reason: null },
            ])) +
        "data: [DONE]\n\n";
      const result = { chunks: [], ids: [], usages: 0, code: null };
      try {
        await streamChat(
          new Api(
            async () =>
              new Response(body, {
                headers: {
                  "Content-Type": "text/event-stream",
                  "X-Request-ID": rid,
                },
              }),
          ),
          "synthetic",
          {
            model: "model-a",
            messages: [{ role: "user", content: "synthetic" }],
            stream: true,
          },
          new AbortController().signal,
          {
            id: (v) => result.ids.push(v),
            chunk: (v) => result.chunks.push(v),
            usage: () => result.usages++,
          },
        );
      } catch (e) {
        result.code = e.code;
      }
      return result;
    }, finalOnly);
    assert.deepEqual(observed.chunks, []);
    assert.equal(observed.ids.length, 1);
    assert.equal(observed.code, finalOnly ? null : "protocol_error");
    assert.equal(observed.usages, finalOnly ? 1 : 0);
    checks.push({ kind: "stream", finalOnly, ...observed });
  }
  assert.deepEqual(errors, []);
} finally {
  await browser?.close();
  await server.close();
  await fs.writeFile(
    `${dir}/results.json`,
    JSON.stringify(
      {
        evidence:
          "Edge with synthetic fetch/SSE; actual Vue components and consumers",
        checks,
        pageerrors: errors,
      },
      null,
      2,
    ),
  );
}
console.log(
  `${checks.length} browser groups passed; pageerrors=${errors.length}`,
);
