import { createServer } from "vite";
import { chromium } from "playwright-core";
import fs from "node:fs/promises";
import assert from "node:assert/strict";
const output = "artifacts/review-browser";
await fs.mkdir(output, { recursive: true });
const server = await createServer({
  server: { host: "127.0.0.1", port: 0 },
  define: { "import.meta.env.VITE_CONSOLE_FIXTURES": JSON.stringify("true") },
});
let browser;
const results = [];
const errors = [];
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
  const fresh = async (tab) => {
    await page.goto(url);
    await page
      .getByRole("heading", { name: "模型目录", exact: true })
      .waitFor();
    if (tab) await page.getByRole("button", { name: tab, exact: true }).click();
  };
  const fillPlay = async (text) => {
    await page.getByLabel("模型").selectOption("model-a");
    await page
      .getByLabel("消费 Key", { exact: true })
      .fill("qa_fixture_only_key");
    await page.getByLabel("消息", { exact: true }).fill(text);
  };
  const state = (expr) => page.evaluate(expr);

  await fresh("平台 Key");
  await page.evaluate(async () => {
    const { api } = await import("/src/api/client.ts");
    const { fixtureFetch } = await import("/src/fixtures.ts");
    window.qaKeys =
      document.querySelector("main form").__vueParentComponent.setupState;
    api.fetcher = async (p, i) => {
      if (String(p).endsWith("/keys") && i?.method === "POST") {
        const response = await fixtureFetch(p, i);
        await new Promise((resolve) => {
          window.releaseKey = resolve;
        });
        window.qaKeyDelivered = true;
        return response;
      }
      return fixtureFetch(p, i);
    };
  });
  await page.getByLabel("名称", { exact: true }).fill("QA delayed fixture key");
  await page.getByLabel("UTC 周期").selectOption("utc_day");
  await page.getByRole("button", { name: "创建 Key", exact: true }).click();
  await page.waitForFunction(() => typeof window.releaseKey === "function");
  await page.getByRole("button", { name: "模型目录", exact: true }).click();
  assert.equal(await state(() => window.qaKeys.secret === ""), true);
  await state(() => window.releaseKey());
  await page.waitForFunction(() => window.qaKeyDelivered === true);
  await page.evaluate(() => new Promise((resolve) => setTimeout(resolve, 50)));
  assert.equal(await state(() => window.qaKeys.secret), "");
  results.push({
    id: "QA-R02",
    result: "pass",
    secretRepopulatedAfterNavigation: await state(
      () => window.qaKeys.secret !== "",
    ),
    visibleSecret: await page.getByTestId("one-time-secret").count(),
  });

  await fresh("在线试用");
  await page.evaluate(async () => {
    const { api } = await import("/src/api/client.ts");
    const { fixtureFetch, lookupSample, rid } =
      await import("/src/fixtures.ts");
    let posts = 0;
    window.qaLookupReads = 0;
    api.fetcher = async (p, i) => {
      if (String(p) === "/v1/chat/completions") {
        const id = ++posts === 1 ? rid : "00000000-0000-4000-8000-000000000022";
        const chunk = {
          id: "chatcmpl-" + id,
          object: "chat.completion.chunk",
          created: 1,
          model: "model-a",
          choices: [
            {
              index: 0,
              delta: { content: "QA synthetic request " + posts },
              finish_reason: "stop",
            },
          ],
        };
        return new Response(
          `data: ${JSON.stringify(chunk)}\n\ndata: [DONE]\n\n`,
          {
            headers: {
              "Content-Type": "text/event-stream",
              "X-Request-ID": id,
            },
          },
        );
      }
      if (String(p).includes("request_id=")) {
        window.qaLookupReads++;
        if (String(p).endsWith(rid))
          return new Promise((resolve) => {
            window.releaseLookupA = () => resolve(Response.json(lookupSample));
          });
      }
      return fixtureFetch(p, i);
    };
  });
  await fillPlay("QA first synthetic request");
  await page.getByRole("button", { name: "发送请求", exact: true }).click();
  await page.waitForFunction(() => typeof window.releaseLookupA === "function");
  await page
    .getByLabel("消息", { exact: true })
    .fill("QA second synthetic request");
  await page.getByRole("button", { name: "发送请求", exact: true }).click();
  await page.waitForFunction(() =>
    document
      .querySelector("main form")
      .__vueParentComponent.setupState.id.endsWith("0022"),
  );
  await state(() => window.releaseLookupA());
  await page.getByText("精确查询：", { exact: false }).waitFor();
  const mismatch = await state(() => {
    const s =
      document.querySelector("main form").__vueParentComponent.setupState;
    return {
      currentId: s.id,
      lookupId: s.lookup.lookup.request_id,
      lookupReads: window.qaLookupReads,
    };
  });
  assert.equal(mismatch.currentId, mismatch.lookupId);
  assert.equal(mismatch.lookupReads, 2);
  results.push({ id: "QA-R01", result: "pass", ...mismatch });
  await page.screenshot({
    path: output + "/request-race-desktop.png",
    fullPage: true,
  });

  await fresh("模型发布");
  await page.evaluate(async () => {
    const { api } = await import("/src/api/client.ts");
    const { fixtureFetch, rid } = await import("/src/fixtures.ts");
    let first;
    let writes = 0;
    api.fetcher = async (p, i) => {
      if (String(p).includes("/release-operations/"))
        return new Promise((resolve) => {
          window.releaseOperationA = () => resolve(Response.json(first));
        });
      const response = await fixtureFetch(p, i);
      if (i?.method === "PUT") {
        const data = await response.json();
        data.operation.id =
          ++writes === 1 ? rid : "00000000-0000-4000-8000-000000000022";
        data.operation.requested_generation = 2 + writes;
        data.resource.metadata.resourceVersion = String(420 + writes);
        data.resource.metadata.generation = 2 + writes;
        data.resource.spec.lifecycle.desiredState = JSON.parse(
          i.body,
        ).spec.lifecycle.desiredState;
        if (writes === 1) first = structuredClone(data.operation);
        return Response.json(data, { status: 202 });
      }
      return response;
    };
  });
  await page.locator(".release-card").click();
  await page.getByRole("button", { name: "暂停发布", exact: true }).click();
  await page.getByText("Update · Accepted", { exact: false }).waitFor();
  await page.getByRole("button", { name: "查询原操作", exact: true }).click();
  await page.waitForFunction(
    () => typeof window.releaseOperationA === "function",
  );
  await page.getByRole("button", { name: "恢复发布", exact: true }).click();
  await page
    .getByText("00000000-0000-4000-8000-000000000022", { exact: true })
    .waitFor();
  await state(() => window.releaseOperationA());
  await page.evaluate(() => new Promise((resolve) => setTimeout(resolve, 50)));
  await page
    .getByText("00000000-0000-4000-8000-000000000022", { exact: true })
    .waitFor();
  assert.equal(
    await page
      .getByText("00000000-0000-4000-8000-000000000001", { exact: true })
      .count(),
    0,
  );
  results.push({
    id: "QA-R03",
    result: "pass",
    latestAcceptedOperation: "00000000-0000-4000-8000-000000000022",
    displayedOperation: "00000000-0000-4000-8000-000000000022",
  });
  await page.screenshot({
    path: output + "/operation-race-desktop.png",
    fullPage: true,
  });

  await fresh("模型发布");
  await page.evaluate(async () => {
    const { api } = await import("/src/api/client.ts");
    const { fixtureFetch, fixtureError } = await import("/src/fixtures.ts");
    window.qaWrites = 0;
    api.fetcher = (p, i) => {
      if (i?.method === "PUT") {
        window.qaWrites++;
        return Promise.resolve(fixtureError("resource_version_conflict", 409));
      }
      return fixtureFetch(p, i);
    };
  });
  await page.locator(".release-card").click();
  await page.getByRole("button", { name: "暂停发布", exact: true }).click();
  await page
    .getByText("配置已被修改，请刷新并核对后重新提交。", { exact: true })
    .waitFor();
  assert.equal(await state(() => window.qaWrites), 1);
  results.push({
    id: "QA-B01",
    result: "pass",
    check: "release 409 is visible and no automatic write retry",
  });

  for (const [code, label] of [
    ["request_budget_exceeded", "请求次数预算不足。"],
    ["token_budget_exceeded", "Token 预算不足。"],
    ["money_budget_exceeded", "金额预算不足。"],
    ["rate_limited", "请求过于频繁，请稍后手动重试。"],
  ]) {
    await fresh("在线试用");
    await page.evaluate(async (code) => {
      const { api } = await import("/src/api/client.ts");
      const { fixtureFetch, fixtureError, rid } =
        await import("/src/fixtures.ts");
      window.qaPosts = 0;
      api.fetcher = async (p, i) => {
        if (String(p) === "/v1/chat/completions") {
          window.qaPosts++;
          const body = await fixtureError(code, 429).json();
          return Response.json(body, {
            status: 429,
            headers: { "X-Request-ID": rid },
          });
        }
        return fixtureFetch(p, i);
      };
    }, code);
    await fillPlay("QA synthetic budget error");
    await page.getByRole("button", { name: "发送请求", exact: true }).click();
    await page.getByText(label, { exact: true }).waitFor();
    await page.getByText("精确查询：", { exact: false }).waitFor();
    assert.equal(await state(() => window.qaPosts), 1);
    results.push({
      id: "QA-B02-" + code,
      result: "pass",
      check: "correct error, one POST, original ID recovery",
    });
  }

  await fresh("在线试用");
  await page.evaluate(async () => {
    const { api } = await import("/src/api/client.ts");
    const { fixtureFetch, lookupSample, rid, now } =
      await import("/src/fixtures.ts");
    api.fetcher = async (p, i) => {
      if (String(p) === "/v1/chat/completions")
        return new Response("", {
          headers: { "Content-Type": "text/event-stream", "X-Request-ID": rid },
        });
      if (String(p).includes("request_id="))
        return Response.json({
          data: lookupSample.data,
          next_cursor: null,
          generated_at: now,
          data_complete: true,
        });
      return fixtureFetch(p, i);
    };
  });
  await fillPlay("QA synthetic EOF and old service");
  await page.getByRole("button", { name: "发送请求", exact: true }).click();
  await page
    .getByText("回查未完成：服务响应不符合当前契约。", { exact: true })
    .waitFor();
  assert.equal(await page.getByText("精确查询：", { exact: false }).count(), 0);
  results.push({
    id: "QA-B03",
    result: "pass",
    check: "EOF interrupted and old lookup envelope fails closed",
  });

  await fresh("在线试用");
  await fillPlay("QA memory cleanup");
  await page.evaluate(() => {
    window.qaPlay =
      document.querySelector("main form").__vueParentComponent.setupState;
  });
  await page.getByRole("button", { name: "模型目录", exact: true }).click();
  assert.equal(
    await state(
      () =>
        window.qaPlay.key === "" &&
        window.qaPlay.prompt === "" &&
        window.qaPlay.output === "",
    ),
    true,
  );
  await page.getByRole("button", { name: "在线试用", exact: true }).click();
  await page
    .getByLabel("消费 Key", { exact: true })
    .fill("qa_fixture_only_key");
  await page.evaluate(() => {
    window.qaPlay =
      document.querySelector("main form").__vueParentComponent.setupState;
    window.dispatchEvent(new Event("maas-session-expired"));
  });
  await page
    .getByRole("heading", { name: "登录管理工作台", exact: true })
    .waitFor();
  assert.equal(await state(() => window.qaPlay.key === ""), true);
  results.push({
    id: "QA-B04",
    result: "pass",
    check: "normal navigation and session expiry clear consumer key",
  });

  await fresh();
  await page.setViewportSize({ width: 390, height: 844 });
  for (const tab of [
    "模型目录",
    "平台 Key",
    "在线试用",
    "模型发布",
    "请求与用量",
  ]) {
    await page.getByRole("button", { name: tab, exact: true }).click();
    await page.getByRole("heading", { name: tab, exact: true }).waitFor();
    assert.equal(
      await state(() => document.documentElement.scrollWidth > innerWidth),
      false,
      tab + " mobile overflow",
    );
  }
  await page.screenshot({ path: output + "/usage-mobile.png", fullPage: true });
  results.push({
    id: "QA-B05",
    result: "pass",
    check: "all five pages fit 390px without whole-page horizontal overflow",
  });
  assert.equal(
    await state(() => localStorage.length + sessionStorage.length),
    0,
  );
  assert.deepEqual(errors, []);
  await fs.writeFile(
    output + "/results.json",
    JSON.stringify(
      {
        kind: "developer_rerun_of_QA_synthetic_browser_regressions_not_independent_acceptance",
        baseline: "6d0160419156852d7dfd8f3e044f119b777a0ad4",
        browser: browser.version(),
        node: process.version,
        results,
        errors,
      },
      null,
      2,
    ),
  );
  console.log(
    JSON.stringify({
      checks: results.length,
      defectsReproduced: results.filter((x) => x.result === "defect_reproduced")
        .length,
      errors,
    }),
  );
} finally {
  await browser?.close();
  await server.close();
}
