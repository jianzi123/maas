// Explicit HTTP fixtures for the built-artifact check. Never imported into product code.
import fs from "node:fs/promises";
import path from "node:path";
import http from "node:http";
import assert from "node:assert/strict";
import { chromium } from "playwright-core";
const output = "artifacts/deployed-console";
await fs.mkdir(output, { recursive: true });
const enabled = JSON.parse(
  await fs.readFile("examples/console-config.controlled.json", "utf8"),
);
let configuration = enabled,
  expired = false,
  streamed = false,
  authenticated = false;
const sid = "10000000-0000-4000-8000-000000000001",
  rid = "10000000-0000-4000-8000-000000000002",
  mid = "10000000-0000-4000-8000-000000000003",
  owner = "10000000-0000-4000-8000-000000000004",
  eid = "10000000-0000-4000-8000-000000000005";
const date = "2026-11-23T14:00:00Z",
  csrf = "fixture-not-a-real-secret-".repeat(2),
  network = [],
  checks = [],
  pageErrors = [];
let origin;
const root = "/api/agent/v1/sessions/" + sid;
function snapshot() {
  const revision = streamed ? "3" : expired ? "2" : "1",
    cursor = streamed ? "cursor-B" : "cursor-A",
    seq = streamed ? "2" : "1";
  return {
    conversation: {
      id: sid,
      owner_id: owner,
      title: "静态产物 HTTP 夹具",
      model_alias: "tools-fixture",
      revision,
      active_run_id: streamed ? null : rid,
      created_at: date,
      updated_at: date,
      deleted_at: null,
    },
    messages: [
      {
        id: mid,
        session_id: sid,
        position: "1",
        role: "assistant",
        parts: [{ type: "text", text: streamed ? "你好🙂" : "你" }],
        status: streamed ? "committed" : "partial",
        run_id: rid,
        supersedes_message_id: null,
        created_at: date,
      },
    ],
    runs: [
      {
        id: rid,
        session_id: sid,
        client_operation_id: eid,
        mode: "chat",
        state: streamed ? "completed" : "running",
        revision: "1",
        fence: "1",
        input_head_message_id: mid,
        model_alias: "tools-fixture",
        protocol_revision: "text-v1",
        limits: { ...enabled.chat.limits, max_model_calls: 1 },
        cancel_requested: false,
        step_count: 1,
        child_request_ids: [eid],
        usage_groups: [],
        aggregation_complete: false,
        last_event_seq: seq,
        resume_cursor: cursor,
        reason: null,
        created_at: date,
        deadline_at: "2026-11-23T14:00:10Z",
        finished_at: streamed ? date : null,
      },
    ],
    last_event_seq: seq,
    event_run_id: rid,
    resume_cursor: cursor,
    messages_next_cursor: expired ? "" : "page-old",
  };
}
const mime = {
  ".html": "text/html",
  ".js": "application/javascript",
  ".css": "text/css",
  ".json": "application/json",
};
const server = http.createServer(async (req, res) => {
  try {
    const u = new URL(req.url, origin),
      p = u.pathname;
    network.push({
      method: req.method,
      path: p,
      cookiePresent: !!req.headers.cookie,
      csrfMatches: req.headers["x-csrf-token"] === csrf,
    });
    const json = (value, status = 200, headers = {}) => {
      res.writeHead(status, {
        "Content-Type": "application/json",
        "Cache-Control": "no-store",
        ...headers,
      });
      res.end(JSON.stringify(value));
    };
    if (p === "/favicon.ico") {
      res.writeHead(404);
      res.end();
      return;
    }
    if (p === "/console-config.json") {
      json(configuration);
      return;
    }
    if (p.startsWith("/api/")) {
      if (p === "/api/admin/v1/session") {
        if (req.method === "POST") {
          assert.equal(req.headers.origin, origin);
          authenticated = true;
          json(
            {
              admin_id: owner,
              expires_at: "2099-01-01T00:00:00Z",
              csrf_token: csrf,
            },
            200,
            {
              "Set-Cookie":
                "fixture_session=one-service; HttpOnly; SameSite=Strict; Path=/",
            },
          );
          return;
        }
        if (req.method === "DELETE") {
          assert.equal(req.headers["x-csrf-token"], csrf);
          assert(req.headers.cookie?.includes("fixture_session=one-service"));
          authenticated = false;
          res.writeHead(204, {
            "Set-Cookie": "fixture_session=; Max-Age=0; Path=/",
          });
          res.end();
          return;
        }
        if (authenticated) {
          json({
            admin_id: owner,
            expires_at: "2099-01-01T00:00:00Z",
            csrf_token: csrf,
          });
          return;
        }
        json(
          {
            error: {
              code: "unauthenticated",
              message: "Fixture only",
              request_id: eid,
              reset_at: null,
              retry_after_seconds: null,
            },
          },
          401,
          { "X-Request-ID": eid },
        );
        return;
      }
      assert(
        authenticated &&
          req.headers.cookie?.includes("fixture_session=one-service"),
      );
      assert.equal(
        req.method,
        "GET",
        "static fixture check must never submit generation",
      );
      if (p === "/api/agent/v1/capabilities") {
        json({
          protocol_revision: "ar.api/1.0",
          event_versions: ["ar.session.event/1.0"],
          model_modes: [
            {
              model_alias: "tools-fixture",
              text_protocol: "text-v1",
              tools_protocol: "tools-v1",
              capability_revision: "fixture-1",
              approval_state: "controlled",
            },
            {
              model_alias: "text-only",
              text_protocol: "text-v1",
              tools_protocol: null,
              capability_revision: "fixture-1",
              approval_state: "controlled",
            },
          ],
          tools: [],
          attachments_enabled: false,
        });
        return;
      }
      if (p === "/api/agent/v1/sessions") {
        json({ data: [snapshot().conversation], next_cursor: null });
        return;
      }
      if (p === root) {
        const s = snapshot();
        if (!s.messages_next_cursor) s.messages_next_cursor = null;
        json(s, 200, { ETag: '"' + s.conversation.revision + '"' });
        return;
      }
      if (p === root + "/messages") {
        expired = true;
        json(
          {
            error: {
              code: "cursor_expired",
              message: "Fixture revision changed",
              http_request_id: eid,
              run_id: rid,
              child_request_id: null,
              retryable: false,
              snapshot_required: true,
            },
          },
          410,
          { "X-Request-ID": eid },
        );
        return;
      }
      if (p.endsWith("/steps") || p.endsWith("/tool-calls")) {
        json({ data: [], next_cursor: null }, 200, {
          ETag: '"' + snapshot().conversation.revision + '"',
        });
        return;
      }
      if (p.endsWith("/events/stream")) {
        assert.equal(u.searchParams.get("after"), "cursor-A");
        streamed = true;
        res.writeHead(200, {
          "Content-Type": "text/event-stream",
          "Cache-Control": "no-store",
        });
        res.end(
          "id: cursor-B\nevent: message.delta\ndata: " +
            JSON.stringify({
              version: "ar.session.event/1.0",
              id: eid,
              session_id: sid,
              run_id: rid,
              seq: "2",
              cursor: "cursor-B",
              created_at: date,
              type: "message.delta",
              data: { message_id: mid, offset: "3", text: "好🙂" },
            }) +
            "\n\n",
        );
        return;
      }
      if (p === "/api/admin/v1/models") {
        json({ data: [], next_cursor: null });
        return;
      }
      throw Error("Unexpected fixture API " + p);
    }
    const file = path.resolve("dist", p === "/" ? "index.html" : "." + p);
    assert(file.startsWith(path.resolve("dist") + path.sep));
    res.writeHead(200, {
      "Content-Type": mime[path.extname(file)] || "application/octet-stream",
    });
    res.end(await fs.readFile(file));
  } catch (e) {
    res.writeHead(500);
    res.end("Explicit fixture error");
    pageErrors.push(e.message);
  }
});
let browser, page;
try {
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  origin = "http://127.0.0.1:" + server.address().port;
  browser = await chromium.launch({
    executablePath:
      process.env.EDGE_PATH ||
      "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
    headless: true,
  });
  page = await browser.newPage({
    viewport: { width: 1440, height: 1000 },
  });
  page.on("pageerror", (e) => pageErrors.push(e.message));
  await page.goto(origin + "/#chat/" + sid);
  await page.getByLabel("管理员账号", { exact: true }).fill("fixture");
  await page
    .getByLabel("密码", { exact: true })
    .fill("fixture-password-not-real");
  await page.getByRole("button", { name: "登录", exact: true }).click();
  await page.getByText("你好🙂", { exact: true }).waitFor();
  assert(expired && streamed);
  checks.push(
    "Production dist loads runtime config, same-origin session cookie and SSE; 410 GET reconstruction",
  );
  const runWrites = () =>
    network.filter((x) => x.method === "POST" && x.path.endsWith("/runs"))
      .length;
  assert.equal(runWrites(), 0);
  await page.reload();
  await page.getByText("你好🙂", { exact: true }).waitFor();
  assert.equal(runWrites(), 0);
  checks.push(
    "Reload restores original Run/child usage association without generation",
  );
  await page.locator(".chat-controls select").nth(1).selectOption("text-only");
  await page.locator(".chat-controls select").nth(0).selectOption("agent");
  await page
    .getByLabel("消息", { exact: true })
    .fill("不得调用无工具能力的模型");
  await page
    .getByText("没有支持所选模式的获准模型", { exact: false })
    .waitFor();
  assert(
    await page
      .getByRole("button", { name: "发送消息", exact: true })
      .isDisabled(),
  );
  assert.equal(runWrites(), 0);
  checks.push("Text-only model rejects Agent before POST");
  await page.screenshot({
    path: output + "/built-console.png",
    fullPage: false,
  });
  await page.getByRole("button", { name: "退出会话", exact: true }).click();
  await page.getByRole("button", { name: "登录", exact: true }).waitFor();
  assert(
    network.some(
      (x) =>
        x.method === "DELETE" &&
        x.path === "/api/admin/v1/session" &&
        x.cookiePresent &&
        x.csrfMatches,
    ),
  );
  checks.push("Single-service Cookie/CSRF logout");
  configuration = { ...enabled, api_url: "https://invalid.example" };
  const logins = network.filter(
    (x) => x.method === "POST" && x.path === "/api/admin/v1/session",
  ).length;
  await page.reload();
  await page.getByText("控制台部署配置不可用", { exact: false }).waitFor();
  await page.getByLabel("管理员账号", { exact: true }).fill("fixture");
  await page
    .getByLabel("密码", { exact: true })
    .fill("fixture-password-not-real");
  await page.getByRole("button", { name: "登录", exact: true }).click();
  await page.getByText("控制台部署配置不可用", { exact: false }).waitFor();
  assert.equal(
    network.filter(
      (x) => x.method === "POST" && x.path === "/api/admin/v1/session",
    ).length,
    logins,
  );
  checks.push(
    "Invalid deployment config fails before authentication or generation",
  );
  assert(
    !network.some(
      (x) => x.path.startsWith("/__maas") || x.path.startsWith("/src"),
    ),
  );
  assert.deepEqual(pageErrors, []);
  await fs.writeFile(
    output + "/built-results.json",
    JSON.stringify(
      {
        scope:
          "Production static dist + explicit HTTP fixtures only; NOT Go/MySQL/model/deployment acceptance",
        checks,
        pageErrors,
        network,
      },
      null,
      2,
    ),
  );
  console.log(
    JSON.stringify({ checks: checks.length, pageErrors: pageErrors.length }),
  );
} catch (error) {
  await fs.writeFile(
    output + "/failure.json",
    JSON.stringify(
      { message: error.message, checks, pageErrors, network },
      null,
      2,
    ),
  );
  await page?.screenshot({ path: output + "/failure.png" }).catch(() => {});
  throw error;
} finally {
  await browser?.close();
  await new Promise((resolve) => server.close(resolve));
}
