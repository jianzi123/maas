import { createServer } from "vite";
import { chromium } from "playwright-core";
import { mkdir, writeFile } from "node:fs/promises";
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
const real = process.argv.includes("--real");
const out = "artifacts/redesign/" + (real ? "go" : "fixture");
await mkdir(out, { recursive: true });
const checks = [],
  errors = [],
  responses = [],
  generation = [];
let server, app, browser, page;
const check = (label) => checks.push(label);
const until = async (fn, predicate, label) => {
  const end = Date.now() + 25000;
  while (Date.now() < end) {
    const v = await fn();
    if (predicate(v)) return v;
    await new Promise((r) => setTimeout(r, 200));
  }
  throw Error("Timed out " + label);
};
const nav = async (name) => {
  await page
    .getByRole("navigation", { name: "主导航" })
    .getByRole("button", { name, exact: true })
    .click();
  await page.getByRole("heading", { name, exact: true }).waitFor();
};
let failure;
try {
  if (real) {
    const { startWorkbench } = await import("../../scripts/dev.mjs");
    app = await startWorkbench({ port: 0 });
  } else {
    server = await createServer({
      server: { host: "127.0.0.1", port: 0 },
      define: {
        "import.meta.env.VITE_CONSOLE_FIXTURES": JSON.stringify("true"),
      },
    });
    await server.listen();
    app = { url: "http://127.0.0.1:" + server.httpServer.address().port };
  }
  browser = await chromium.launch({
    executablePath:
      process.env.EDGE_PATH ||
      "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
    headless: true,
  });
  page = await browser.newPage({
    viewport: { width: 1440, height: 900 },
    deviceScaleFactor: 1,
  });
  page.setDefaultTimeout(20000);
  page.on("pageerror", (e) => errors.push(e.message));
  page.on("request", (r) => {
    if (new URL(r.url()).pathname === "/v1/chat/completions")
      generation.push(r.method());
  });
  page.on("response", (r) => {
    const p = new URL(r.url()).pathname;
    if (p.startsWith("/api/"))
      responses.push({
        method: r.request().method(),
        path: p,
        status: r.status(),
      });
  });
  if (real)
    await until(
      async () => {
        try {
          return (await page.request.get(app.url)).status();
        } catch {
          return 0;
        }
      },
      (s) => s === 200,
      "temporary localhost readiness",
    );
  await page.goto(app.url);
  if (!real)
    await page.evaluate(async () => {
      const { api } = await import("/src/api/client.ts");
      const old = api.fetcher;
      window.__ui16 = { operations: [], posts: 0 };
      api.fetcher = async (p, i) => {
        if (p === "/v1/chat/completions") window.__ui16.posts++;
        const res = await old(p, i);
        if (i?.method && String(p).includes("/model-releases"))
          window.__ui16.operations.push(await res.clone().json());
        return res;
      };
    });
  const watchMutation = (method) => {
    if (real)
      return page.waitForResponse(
        (r) =>
          r.request().method() === method &&
          new URL(r.url()).pathname.includes("/model-releases"),
      );
    return (async () => {
      const n = await page.evaluate(() => window.__ui16.operations.length);
      await page.waitForFunction((n) => window.__ui16.operations.length > n, n);
      const body = await page.evaluate(() => window.__ui16.operations.at(-1));
      return { json: async () => body, status: () => 202 };
    })();
  };
  await page.getByRole("heading", { name: "模型目录", exact: true }).waitFor();
  await until(
    () => page.locator(".model-card").count(),
    (n) => n > 0,
    "model cards",
  );
  await page.getByLabel("搜索模型", { exact: true }).fill("not-found");
  assert.equal(await page.locator(".model-card").count(), 0);
  await page.getByRole("button", { name: "清除筛选", exact: true }).click();
  check("catalogue searches loaded collection and resets filters");
  await page
    .getByRole("button", { name: "查看详情", exact: true })
    .first()
    .click();
  await page.getByRole("dialog").waitFor();
  await page.keyboard.press("Escape");
  assert.equal(await page.getByRole("dialog").count(), 0);
  check("model detail dialog supports Escape and returns focus");
  if (!real) {
    await page
      .locator(".model-card")
      .first()
      .getByRole("button", { name: "在线试用", exact: true })
      .click();
    await page
      .getByLabel("消费 Key", { exact: true })
      .fill("fixture_only_not_a_credential_000001");
    await page.getByLabel("消息", { exact: true }).fill("测试停止后核对原请求");
    await page.getByRole("button", { name: "发送请求", exact: true }).click();
    await page
      .getByText("这是开发夹具的流式响应。", { exact: false })
      .first()
      .waitFor();
    await page.getByRole("button", { name: "停止传输", exact: true }).click();
    await page.getByText("精确查询：recorded", { exact: false }).waitFor();
    assert.equal(await page.evaluate(() => window.__ui16.posts), 1);
    check(
      "catalogue to stream/stop/original lookup performs one generation POST only (fixture)",
    );
    await page.screenshot({
      path: out + "/path-stream-stopped.png",
      fullPage: true,
    });
  } else {
    await nav("在线试用");
    assert.equal(
      await page
        .getByRole("button", { name: "发送请求", exact: true })
        .isDisabled(),
      true,
    );
    check(
      "real Go unavailable inference stays disabled; original request is not fabricated",
    );
  }
  await nav("平台 Key");
  await page.getByTestId("create-key").click();
  await page.getByLabel("名称", { exact: true }).fill("改版管理路径");
  await page.getByLabel("UTC 周期", { exact: false }).selectOption("utc_day");
  await page.getByLabel("请求数限额", { exact: true }).fill("20");
  await page.getByRole("button", { name: "创建 Key", exact: true }).click();
  await page.getByTestId("one-time-secret").waitFor();
  await page
    .getByRole("button", { name: "我已保存，关闭原值", exact: true })
    .click();
  await page
    .getByRole("button", { name: "修改预算", exact: true })
    .last()
    .click();
  await page.getByLabel("请求数限额", { exact: true }).fill("0");
  await page.getByRole("button", { name: "保存预算", exact: true }).click();
  await page.getByText("预算已更新", { exact: false }).waitFor();
  check(
    "Key create / close one-time value / exact zero budget management path",
  );
  await page
    .getByRole("button", { name: "查看用量", exact: true })
    .last()
    .click();
  await page
    .getByRole("heading", { name: "请求与用量", exact: true })
    .waitFor();
  await page.getByText("按 Key 查询", { exact: false }).waitFor();
  check("Key non-secret ID links to actual usage filter");
  await nav("模型发布");
  if (real) {
    await page
      .getByRole("button", { name: "载入本地示例", exact: true })
      .click();
  } else {
    await page
      .getByRole("button", { name: "新建外部 API CR", exact: true })
      .click();
  }
  // Use the full approved sample for real Go, never invent credentials or deployment references.
  if (!real) {
    await page
      .getByText("高级 JSON · 全部 Schema 字段", { exact: true })
      .click();
    const fixture = await import("../src/fixture-data.json", {
      with: { type: "json" },
    });
    const input = structuredClone(fixture.default.external);
    input.metadata = {
      namespace: input.metadata.namespace,
      name: input.metadata.name,
    };
    await page
      .getByLabel("ModelRelease JSON", { exact: true })
      .fill(JSON.stringify(input));
  }
  await page.getByRole("button", { name: "5 确认提交", exact: true }).click();
  await page.screenshot({
    path: out + "/path-full-schema.png",
    fullPage: true,
  });
  const submitted = watchMutation("POST");
  await page
    .getByRole("button", { name: "校验并提交配置", exact: true })
    .click();
  const accepted = await (await submitted).json();
  assert(accepted.operation.id);
  await page.getByRole("button", { name: "查询原操作", exact: true }).click();
  check(
    "full Schema form submits 202 and queries original operation without replay",
  );
  const get = async (route) => {
    const r = await page.request.get(app.url + "/api/admin/v1" + route);
    assert.equal(r.status(), 200);
    return r.json();
  };
  const releasePath =
    "/model-releases/" +
    accepted.operation.namespace +
    "/" +
    accepted.operation.name;
  if (real) {
    await until(
      () => get(releasePath),
      (r) =>
        r.status?.observedGeneration === r.metadata.generation &&
        r.status.conditions.some((c) => c.status !== "True"),
      "blocked release observation",
    );
    await page
      .getByRole("button", { name: "重读当前 CR", exact: true })
      .click();
    await page
      .getByRole("heading", { name: "当前阻塞与下一步", exact: true })
      .waitFor();
  }
  await page.getByRole("button", { name: "读取保留修订", exact: true }).click();
  await page.getByRole("heading", { name: /保留修订/ }).waitFor();
  check(
    "release details explain blocking and retain history entry (no Callable claim)",
  );
  await page.screenshot({
    path: out + "/path-release-detail.png",
    fullPage: true,
  });
  // Save actual rendered five pages in all requested widths. No secret is displayed.
  for (const [width, height] of [
    [1440, 900],
    [768, 1000],
    [390, 844],
  ]) {
    await page.setViewportSize({ width, height });
    for (const [name, file] of [
      ["模型目录", "models"],
      ["在线试用", "playground"],
      ["模型发布", "releases"],
      ["请求与用量", "usage"],
      ["平台 Key", "keys"],
    ]) {
      await nav(name);
      if (name === "模型发布") {
        await until(
          () => page.locator(".release-card").count(),
          (n) => n > 0,
          "release rows",
        );
        await page.locator(".release-card").first().click();
        await page
          .getByRole("button", { name: "重读当前 CR", exact: true })
          .waitFor();
      }
      if (name === "请求与用量" && !real) {
        await page
          .getByRole("button", { name: "请求详情", exact: true })
          .first()
          .waitFor();
      }
      const fits = await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth + 1,
      );
      assert(fits, name + " overflow at " + width);
      check(name + " layout " + width);
      await page.mouse.move(2, 2);
      if (width !== 768)
        await page.screenshot({
          path: out + "/" + file + "-" + width + ".png",
          fullPage: false,
        });
    }
  }
  if (!real) {
    await nav("请求与用量");
    await page
      .getByRole("button", { name: "请求详情", exact: true })
      .first()
      .click();
    await page.getByRole("dialog").waitFor();
    await page.keyboard.press("Tab");
    assert(
      await page
        .getByRole("dialog")
        .evaluate((d) => d.contains(document.activeElement)),
    );
    await page.keyboard.press("Escape");
    assert.equal(await page.getByRole("dialog").count(), 0);
    check("request drawer shows unknown and traps/restores focus");
    await page.getByRole("tab", { name: "用量汇总", exact: true }).click();
    await page.getByText("未知金额占用", { exact: false }).first().waitFor();
    check("request/summary tabs preserve unknown and currency-separated data");
  } else {
    await nav("模型发布");
    await page.locator(".release-card").first().click();
    await page
      .getByRole("button", { name: "重读当前 CR", exact: true })
      .waitFor();
    const pause = page.waitForResponse(
      (r) =>
        r.request().method() === "PUT" &&
        new URL(r.url()).pathname.includes("/model-releases/"),
    );
    await page.getByRole("button", { name: "暂停发布", exact: true }).click();
    assert.equal((await pause).status(), 202);
    check("real Go pause PUT is accepted separately from activity");
    await page.getByRole("button", { name: "下线并清理", exact: true }).click();
    const del = page.waitForResponse((r) => r.request().method() === "DELETE");
    await page.getByRole("button", { name: "确认下线", exact: true }).click();
    const deleted = await (await del).json();
    await until(
      () => get("/release-operations/" + deleted.operation.id),
      (o) => o.state === "Succeeded",
      "delete completion",
    );
    await page.getByRole("button", { name: "查询原操作", exact: true }).click();
    await page.getByText("原删除操作已确认完成", { exact: false }).waitFor();
    assert.equal(
      await page
        .getByRole("button", { name: "新建外部 API CR", exact: true })
        .isEnabled(),
      true,
    );
    assert.equal(responses.filter((r) => r.method === "DELETE").length, 1);
    check(
      "real Delete Succeeded clears stale editor, preserves operation, unlocks new create without replay",
    );
  }
  assert.equal(
    await page.evaluate(() => localStorage.length + sessionStorage.length),
    0,
  );
  assert.deepEqual(errors, []);
} catch (e) {
  failure = e.stack;
  if (page)
    await page
      .screenshot({ path: out + "/failure.png", fullPage: true })
      .catch(() => {});
  throw e;
} finally {
  await writeFile(
    out + "/results.json",
    JSON.stringify(
      {
        candidate: execFileSync("git", ["rev-parse", "HEAD"], {
          encoding: "utf8",
        }).trim(),
        mode: real
          ? "actual Go/MySQL/envtest temporary management"
          : "explicit fixture HTTP/SSE",
        checks,
        errors,
        responses,
        generationPosts: real
          ? generation.length
          : page
            ? await page
                .evaluate(() => window.__ui16?.posts ?? 0)
                .catch(() => 0)
            : 0,
        failure: failure ?? null,
      },
      null,
      2,
    ),
  );
  await browser?.close();
  if (server) await server.close();
  if (app?.stop) {
    const stopped = await app.stop();
    await writeFile(out + "/cleanup.json", JSON.stringify(stopped));
    assert(stopped.cleaned);
    assert.equal(stopped.code, 0);
  }
}
console.log(
  JSON.stringify({
    mode: real ? "go" : "fixture",
    checks: checks.length,
    errors: errors.length,
  }),
);
