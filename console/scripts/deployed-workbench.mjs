// Browser operations on the normal Go/MySQL offline profile. Not a model mock.
import fs from "node:fs/promises";
import assert from "node:assert/strict";
import { createHash, randomUUID } from "node:crypto";
function canonical(v) {
  if (Array.isArray(v)) return "[" + v.map(canonical).join(",") + "]";
  if (v && typeof v === "object")
    return (
      "{" +
      Object.keys(v)
        .sort()
        .map((k) => JSON.stringify(k) + ":" + canonical(v[k]))
        .join(",") +
      "}"
    );
  return JSON.stringify(v);
}
// Matches the existing Python installer verifier's JSON hashes, including Unicode.
const hash = (v) =>
  createHash("sha256")
    .update(
      canonical(v).replace(
        /[\u007f-\uffff]/g,
        (c) => "\\u" + c.charCodeAt(0).toString(16).padStart(4, "0"),
      ),
    )
    .digest("hex");
export async function controlledWorkbench({
  page,
  origin,
  config,
  caps,
  network,
  checks,
  dir,
  flow,
}) {
  const url = new URL(origin),
    model = process.env.MAAS_SMOKE_MODEL;
  assert(
    ["localhost", "127.0.0.1", "[::1]"].includes(url.hostname),
    "Owned loopback only",
  );
  if (flow === "tool-page")
    assert.equal(
      process.env.MAAS_SMOKE_MUTATE_TITLE,
      "1",
      "Explicit metadata mutation opt-in required",
    );
  else
    assert.equal(
      process.env.MAAS_SMOKE_SEND,
      "1",
      "Explicit controlled generation opt-in required",
    );
  assert(
    [
      "workbench",
      "cancel",
      "tool-page",
      "reject",
      "approve",
      "disconnect",
    ].includes(flow),
  );
  const context = page.context();
  async function get(path) {
    const r = await context.request.get(origin + path, { maxRedirects: 0 });
    assert.equal(r.status(), 200, "GET " + path);
    return r.json();
  }
  const ready = await get("/readyz");
  assert.equal(ready.profile, "offline-controlled");
  assert.equal(ready.persistence, "mysql");
  const selected = caps.model_modes.find((x) => x.model_alias === model);
  assert(selected && selected.approval_state === "controlled");
  if (flow === "workbench" || flow === "reject" || flow === "approve") {
    assert.equal(selected.tools_protocol, "tools-v1");
    assert.equal(
      process.env.MAAS_SMOKE_APPROVE_SAFE_TOOLS,
      "1",
      "Explicit safe-tool approval opt-in required",
    );
  }
  const file = dir + "/record.json";
  try {
    await fs.access(file);
    throw Error(
      "Existing flow record: inspect original IDs; never replay this flow",
    );
  } catch (e) {
    if (e.code !== "ENOENT") throw e;
  }
  const session = await get("/api/admin/v1/session"),
    csrf = session.csrf_token;
  const record = {
    scope: "normal-Go-MySQL-offline-controlled",
    flow,
    sessionId: null,
    runs: [],
    operations: [],
    setupRunPosts: 0,
    explicitReconnects: 0,
  };
  let queue = Promise.resolve();
  function save() {
    const data = JSON.stringify(record, null, 2) + "\n";
    queue = queue.then(() => fs.writeFile(file, data));
    return queue;
  }
  const listener = (r) => {
    const p = new URL(r.url()).pathname;
    if (r.method() !== "POST" || !p.startsWith("/api/agent/v1/")) return;
    const body = r.postDataJSON() ?? {};
    const item = {
      method: "POST",
      path: p,
      client_operation_id: body.client_operation_id,
      decision_id: body.decision_id,
      csrfMatches: r.headers()["x-csrf-token"] === csrf,
    };
    record.operations.push(item);
    record.pendingCommand = { ...item };
    void save();
  };
  page.on("request", listener);
  await save();
  let sp;
  const terminal = new Set([
    "completed",
    "cancelled",
    "failed",
    "limit_reached",
    "needs_confirmation",
  ]);
  const runPosts = () =>
    network.filter((x) => x.method === "POST" && x.path.endsWith("/runs"))
      .length;
  async function create() {
    const response = page.waitForResponse(
      (r) =>
        r.request().method() === "POST" &&
        new URL(r.url()).pathname === "/api/agent/v1/sessions",
    );
    await page
      .getByRole("button", { name: "＋ 新建会话", exact: true })
      .click();
    const r = await response;
    assert.equal(r.status(), 201);
    record.sessionId = (await r.json()).id;
    sp = "/api/agent/v1/sessions/" + record.sessionId;
    await page.waitForFunction(
      (id) => location.hash === "#chat/" + id,
      record.sessionId,
    );
    delete record.pendingCommand;
    await save();
  }
  async function reconnect() {
    if (
      await page
        .getByRole("button", { name: "只读重连", exact: true })
        .isVisible()
    ) {
      record.explicitReconnects++;
      (record.reconnectReasons ??= []).push(
        await page.locator("[role=alert]").allTextContents(),
      );
      await page.getByRole("button", { name: "只读重连", exact: true }).click();
      await save();
    }
  }
  async function waitUI(state) {
    await reconnect();
    await page.waitForFunction(
      (s) => document.querySelector(".chat-controls .badge")?.textContent === s,
      state,
      { timeout: 12000 },
    );
  }
  async function send(mode, text) {
    await page.locator(".chat-controls select").nth(1).selectOption(model);
    await page.locator(".chat-controls select").nth(0).selectOption(mode);
    await page.getByLabel("消息", { exact: true }).fill(text);
    const response = page.waitForResponse(
      (r) =>
        r.request().method() === "POST" &&
        new URL(r.url()).pathname === sp + "/runs",
    );
    await page.getByRole("button", { name: "发送消息", exact: true }).click();
    const r = await response;
    assert.equal(r.status(), 202);
    const ack = await r.json();
    record.pendingCommand.run_id = ack.run.id;
    await save();
    return ack.run.id;
  }
  async function settled(rid, approve = false) {
    const base = sp + "/runs/" + rid,
      decided = new Set();
    for (let i = 0; i < 350; i++) {
      const run = await get(base);
      if (
        !terminal.has(run.state) &&
        (await page.locator(".chat-controls .badge").first().textContent()) ===
          "running" &&
        (await page.locator(".chat-message.assistant").count())
      ) {
        const text = await page
          .locator(".chat-message.assistant")
          .last()
          .textContent();
        if (text?.includes("离线受控模型")) record.streamingObserved = true;
      }
      if (terminal.has(run.state)) return run;
      if (run.state === "waiting_approval") {
        assert(approve, "Unexpected approval; no automatic decision");
        await waitUI("waiting_approval");
        const calls = (await get(base + "/tool-calls?page_size=100")).data;
        for (const call of calls.filter(
          (c) => c.state === "waiting_approval" && !decided.has(c.id),
        )) {
          assert(
            ["bounded_arithmetic", "list_visible_models"].includes(call.name),
          );
          assert(["pure", "read_only"].includes(call.effect));
          assert.equal(call.attempt, 0);
          assert.deepEqual(
            call.arguments,
            call.name === "bounded_arithmetic"
              ? { a: 6, b: 7, op: "multiply" }
              : {},
          );
          const card = page
            .locator(".approval-card")
            .filter({ has: page.getByText(call.name + "@1", { exact: true }) });
          await card.waitFor();
          assert.deepEqual(
            JSON.parse(await card.locator("pre").textContent()),
            call.arguments,
          );
          await page.screenshot({
            path: dir + "/approval-" + call.name + ".png",
            fullPage: false,
          });
          const response = page.waitForResponse(
            (r) =>
              r.request().method() === "POST" &&
              new URL(r.url()).pathname.startsWith(base + "/approvals/") &&
              new URL(r.url()).pathname.endsWith("/decision"),
          );
          await card
            .getByRole("button", {
              name: approve === "deny" ? "拒绝" : "批准此次工具",
              exact: true,
            })
            .click();
          assert.equal((await response).status(), 200);
          decided.add(call.id);
          delete record.pendingCommand;
          await save();
          if (approve === "deny") return get(base);
        }
      }
      await page.waitForTimeout(100);
    }
    throw Error(
      "Run did not reach terminal; preserve the original operation and run IDs",
    );
  }
  async function capture(run, mode) {
    const base = sp + "/runs/" + run.id,
      events = await get(base + "/events?page_size=100"),
      tools = await get(base + "/tool-calls?page_size=100"),
      usages = [];
    for (const child of run.child_request_ids) {
      const row = await get(
        "/api/admin/v1/usage/requests?request_id=" + encodeURIComponent(child),
      );
      assert.equal(row.data.length, 1);
      assert.notEqual(
        row.data[0].status,
        "in_progress",
        "Controlled child accounting must reach its observed terminal before hashing",
      );
      usages.push(hash(row.data));
    }
    assert(run.child_request_ids.length > 0);
    record.runs.push({
      id: run.id,
      mode,
      state: run.state,
      eventsHash: hash(events),
      toolsHash: hash(tools),
      children: run.child_request_ids,
      usageHashes: usages,
      lastSeq: run.last_event_seq,
    });
    delete record.pendingCommand;
    await save();
    return tools;
  }
  try {
    if (flow === "tool-page") {
      const file = process.env.MAAS_SMOKE_ORIGINAL_RECORD;
      assert(file, "Original controlled workbench record required");
      const original = JSON.parse(await fs.readFile(file, "utf8"));
      await verifyControlledRecord({ page, origin, file, checks });
      const saved = original.runs.at(-1);
      assert.equal(saved.mode, "agent");
      record.sessionId = original.sessionId;
      record.runs = original.runs;
      sp = "/api/agent/v1/sessions/" + record.sessionId;
      const beforeSnapshot = await get(sp);
      assert.equal(beforeSnapshot.runs.at(-1).id, saved.id);
      const base = sp + "/runs/" + saved.id;
      let first = false,
        expired = false;
      const matcher = (url) => url.pathname === base + "/tool-calls";
      await page.route(matcher, async (route) => {
        const url = new URL(route.request().url());
        if (!first && !url.searchParams.has("cursor")) {
          first = true;
          url.searchParams.set("page_size", "1");
          const response = await route.fetch({
            url: url.href,
            maxRedirects: 0,
          });
          assert.equal(response.status(), 200);
          assert((await response.json()).next_cursor);
          await route.fulfill({ response });
          return;
        }
        if (url.searchParams.has("cursor") && !expired) {
          expired = true;
          const current = await get(sp);
          record.pendingCommand = {
            kind: "title-mutation",
            sessionId: record.sessionId,
          };
          await save();
          const changed = await context.request.patch(origin + sp, {
            headers: {
              Origin: origin,
              "X-CSRF-Token": csrf,
              "If-Match": '"' + current.conversation.revision + '"',
            },
            data: { title: "正式站点工具分页恢复" },
            maxRedirects: 0,
          });
          assert.equal(changed.status(), 200);
          record.metadataMutations = 1;
          delete record.pendingCommand;
          await save();
        }
        const response = await route.fetch({ maxRedirects: 0 });
        if (response.status() === 410) {
          const e = (await response.json()).error;
          assert.equal(e.code, "cursor_expired");
          assert.equal(e.snapshot_required, true);
          assert.equal(e.retryable, false);
          record.realPage410 = (record.realPage410 ?? 0) + 1;
        }
        await route.fulfill({ response });
      });
      const before = runPosts();
      await page.reload();
      await page.waitForFunction(
        () =>
          document.querySelector(".chat-controls .badge")?.textContent ===
          "completed",
        null,
        { timeout: 15000 },
      );
      assert.equal(runPosts(), before);
      assert.equal(record.realPage410, 1);
      await page.unroute(matcher);
      assert.equal(
        await page
          .locator(".agent-trace article")
          .filter({ hasText: "bounded_arithmetic@1" })
          .count(),
        1,
      );
      assert.equal(
        await page
          .locator(".agent-trace article")
          .filter({ hasText: "list_visible_models@1" })
          .count(),
        1,
      );
      const afterSnapshot = await get(sp);
      assert.equal(afterSnapshot.resume_cursor, beforeSnapshot.resume_cursor);
      record.eventCursorPreserved = true;
      await verifyControlledRecord({ page, origin, file, checks });
      checks.push(
        "Actual Go ToolCallPage revision 410 rebuilds a complete batch; metadata mutation once, recovery zero Run POST",
      );
    } else {
      await create();
      // Same authenticated origin, deliberately wrong CSRF. No model operation.
      const denied = await context.request.post(
        origin + "/api/agent/v1/sessions",
        {
          headers: { Origin: origin, "X-CSRF-Token": "invalid-test-csrf" },
          data: {
            client_operation_id: randomUUID(),
            title: "CSRF negative",
            model_alias: model,
          },
          maxRedirects: 0,
        },
      );
      assert.equal(denied.status(), 403);
      record.csrfRejectedStatus = denied.status();
      checks.push("Go rejects authenticated write with wrong CSRF");
      if (flow === "workbench" || flow === "approve") {
        let rid, run;
        if (flow === "workbench") {
          rid = await send("chat", "中文🙂：验证正式站点的受控流式输出");
          run = await settled(rid);
          assert.equal(run.state, "completed");
          await waitUI("completed");
          assert(
            (
              await page.locator(".chat-message.assistant").last().textContent()
            ).includes("离线受控模型"),
          );
          await capture(run, "chat");
          checks.push(
            "Normal Go/MySQL Chat, streamed Chinese/emoji and original child usage",
          );
        }
        rid = await send("agent", "请计算6×7，再列出当前授权模型。");
        run = await settled(rid, true);
        assert.equal(run.state, "completed");
        await waitUI("completed");
        if (flow === "approve")
          assert.equal(
            record.explicitReconnects,
            0,
            "Approval must publish terminal without manual reconnect",
          );
        const tools = await capture(run, "agent");
        assert.deepEqual(tools.data.map((c) => c.name).sort(), [
          "bounded_arithmetic",
          "list_visible_models",
        ]);
        assert(
          tools.data.every((c) => c.state === "succeeded" && c.attempt === 1),
        );
        assert(
          (await page.locator(".agent-trace").textContent()).includes(
            "实际尝试 1",
          ),
        );
        assert(
          (await page.locator(".agent-trace").textContent()).includes("42"),
        );
        checks.push(
          "Two real safe tools, exact arguments, explicit approval and actual result/attempt",
        );
      } else if (flow === "reject") {
        const rid = await send("agent", "拒绝此受控工具申请，不重新执行");
        const run = await settled(rid, "deny");
        assert.equal(run.state, "failed");
        assert.equal(run.reason, "approval_denied");
        await waitUI("failed");
        const calls = await capture(run, "agent-rejected");
        assert(calls.data.every((c) => c.attempt === 0));
        record.terminalToolClaimsWaiting = (
          await page.locator(".agent-trace").textContent()
        ).includes("等待结果");
        checks.push(
          "Explicit denial preserves failed/approval_denied with zero tool attempts",
        );
      } else if (flow === "disconnect") {
        const rid = await send("chat", "只断开事件连接，保留原运行与用量"),
          base = sp + "/runs/" + rid;
        let admitted;
        for (let i = 0; i < 100; i++) {
          const run = await get(base);
          assert(!terminal.has(run.state));
          if (run.child_request_ids.length) {
            const row = await get(
              "/api/admin/v1/usage/requests?request_id=" +
                run.child_request_ids[0],
            );
            if (row.data[0]?.status === "in_progress") {
              admitted = run;
              break;
            }
          }
          await page.waitForTimeout(50);
        }
        assert(admitted);
        const before = runPosts();
        await page
          .getByRole("button", { name: "断开事件连接", exact: true })
          .click();
        await page
          .getByRole("button", { name: "只读重连", exact: true })
          .waitFor();
        const ongoing = await get(base);
        assert(!terminal.has(ongoing.state));
        assert.deepEqual(ongoing.child_request_ids, admitted.child_request_ids);
        await page
          .getByRole("button", { name: "只读重连", exact: true })
          .click();
        record.intentionalReadReconnects = 1;
        const run = await settled(rid);
        assert.equal(run.state, "completed");
        await waitUI("completed");
        assert.equal(runPosts(), before);
        assert(!record.operations.some((x) => x.path.endsWith("/cancel")));
        await capture(run, "chat-disconnect");
        checks.push(
          "Disconnect only aborts event GET; same admitted child completes after explicit read-only reconnect, zero replay/cancel",
        );
      } else {
        const rid = await send("chat", "受控已准入停止复验"),
          base = sp + "/runs/" + rid;
        let admitted = false;
        for (let i = 0; i < 150; i++) {
          const run = await get(base);
          assert(
            !terminal.has(run.state),
            "Natural completion is not cancellation success; preserve original ID",
          );
          for (const child of run.child_request_ids) {
            const row = await get(
              "/api/admin/v1/usage/requests?request_id=" +
                encodeURIComponent(child),
            );
            if (row.data.length === 1 && row.data[0].status === "in_progress")
              admitted = true;
          }
          if (admitted) break;
          await page.waitForTimeout(50);
        }
        assert(admitted, "No admitted child; do not claim cancellation");
        const response = page.waitForResponse(
          (r) =>
            r.request().method() === "POST" &&
            new URL(r.url()).pathname === base + "/cancel",
        );
        await page
          .getByRole("button", { name: "停止运行", exact: true })
          .click();
        assert.equal((await response).status(), 202);
        const run = await settled(rid);
        assert.equal(run.state, "cancelled");
        await waitUI("cancelled");
        assert.equal(
          record.explicitReconnects,
          0,
          "Stop must publish terminal without manual reconnect",
        );
        await capture(run, "chat");
        record.admittedBeforeCancel = true;
        checks.push(
          "UI stop after actual child in_progress reaches authoritative cancelled",
        );
      }
    }
    const before = runPosts();
    await page.reload();
    await page
      .getByRole("button", { name: "＋ 新建会话", exact: true })
      .waitFor();
    assert.equal(runPosts(), before);
    checks.push(
      "Refresh reads the same session/run and never resends generation",
    );
    assert(record.operations.every((x) => x.csrfMatches));
    const cookies = await context.cookies();
    const own = cookies.filter((c) => c.name === "maas_session");
    assert.equal(own.length, 1);
    assert(own[0].httpOnly);
    record.cookie = {
      name: "maas_session",
      httpOnly: true,
      sameSite: own[0].sameSite,
    };
    await page.screenshot({ path: dir + "/workbench.png", fullPage: false });
    await save();
    return {
      flow,
      profile: ready.profile,
      setupRunPosts: record.setupRunPosts,
      runCount: record.runs.length,
    };
  } finally {
    page.off("request", listener);
    await queue;
  }
}

// Read-only replay of already completed/cancelled or explicitly denied operations.
export async function verifyControlledRecord({ page, origin, file, checks }) {
  const record = JSON.parse(await fs.readFile(file, "utf8"));
  assert(
    !record.pendingCommand &&
      !record.pendingApproval &&
      record.sessionId &&
      record.runs.length,
    "Incomplete original operation; inspect its command, never regenerate",
  );
  const context = page.context();
  async function get(path) {
    const r = await context.request.get(origin + path, { maxRedirects: 0 });
    assert.equal(r.status(), 200, "GET " + path);
    return r.json();
  }
  const ready = await get("/readyz");
  assert.equal(ready.persistence, "mysql");
  assert.equal(ready.profile, "offline-controlled");
  for (const saved of record.runs) {
    const base =
        "/api/agent/v1/sessions/" + record.sessionId + "/runs/" + saved.id,
      run = await get(base);
    assert(["completed", "cancelled", "failed"].includes(saved.state));
    assert.equal(run.state, saved.state);
    assert.deepEqual(run.child_request_ids, saved.children);
    assert.equal(run.last_event_seq, saved.lastSeq);
    if (run.state === "failed") assert.equal(run.reason, "approval_denied");
    assert.equal(
      hash(await get(base + "/events?page_size=100")),
      saved.eventsHash,
    );
    assert.equal(
      hash(await get(base + "/tool-calls?page_size=100")),
      saved.toolsHash,
    );
    for (let i = 0; i < saved.children.length; i++) {
      const row = await get(
        "/api/admin/v1/usage/requests?request_id=" +
          encodeURIComponent(saved.children[i]),
      );
      assert.equal(row.data.length, 1);
      assert.equal(hash(row.data), saved.usageHashes[i]);
    }
  }
  await page.goto(origin + "/#chat/" + record.sessionId);
  await page.reload();
  await page.waitForFunction(
    (state) =>
      document.querySelector(".chat-controls .badge")?.textContent === state,
    record.runs.at(-1).state,
    { timeout: 15000 },
  );
  checks.push(
    "Read-only original run/child/event/tool/usage hashes match; " +
      record.runs.length +
      " original runs",
  );
  if (record.runs.at(-1).state === "cancelled")
    assert(
      !(await page.locator(".chat-controls").textContent()).includes(
        "等待实际终止",
      ),
    );
  if (record.flow === "reject") {
    const trace = await page.locator(".agent-trace").textContent();
    assert(!trace.includes("等待结果"));
    assert(trace.includes("未返回结果"));
    assert(
      (await page.locator("body").textContent()).includes(
        "工具执行申请已被拒绝",
      ),
    );
  }
  return { verifiedRuns: record.runs.length, sessionId: record.sessionId };
}

// Completes this harness's known denied operation using only its original IDs.
// The input failure record is immutable; no request or decision is resubmitted.
export async function recoverDeniedRecord({
  page,
  origin,
  file,
  output,
  checks,
}) {
  const original = JSON.parse(await fs.readFile(file, "utf8"));
  assert.equal(original.flow, "reject");
  assert(original.sessionId && original.runs.length === 0);
  const operation = original.operations.find((x) => x.path.endsWith("/runs"));
  assert(operation?.client_operation_id);
  const get = async (path) => {
    const r = await page
      .context()
      .request.get(origin + path, { maxRedirects: 0 });
    assert.equal(r.status(), 200, "GET " + path);
    return r.json();
  };
  const sp = "/api/agent/v1/sessions/" + original.sessionId,
    command = await get(sp + "/commands/" + operation.client_operation_id);
  assert.equal(command.state, "accepted");
  assert.equal(command.client_operation_id, operation.client_operation_id);
  assert(command.run_id);
  const base = sp + "/runs/" + command.run_id,
    run = await get(base);
  assert.equal(run.client_operation_id, operation.client_operation_id);
  assert.equal(run.state, "failed");
  assert.equal(run.reason, "approval_denied");
  const decision = original.operations.find((x) =>
    x.path.endsWith("/decision"),
  );
  assert(decision && decision.path.includes("/runs/" + run.id + "/"));
  const approval = await get(decision.path.slice(0, -"/decision".length));
  assert.equal(approval.state, "denied");
  const events = await get(base + "/events?page_size=100"),
    tools = await get(base + "/tool-calls?page_size=100"),
    usages = [];
  assert(tools.data.every((c) => c.attempt === 0));
  for (const child of run.child_request_ids) {
    const row = await get(
      "/api/admin/v1/usage/requests?request_id=" + encodeURIComponent(child),
    );
    assert.equal(row.data.length, 1);
    usages.push(hash(row.data));
  }
  const recovered = {
    ...original,
    recoveredReadOnly: true,
    runs: [
      {
        id: run.id,
        mode: "agent-rejected",
        state: run.state,
        eventsHash: hash(events),
        toolsHash: hash(tools),
        children: run.child_request_ids,
        usageHashes: usages,
        lastSeq: run.last_event_seq,
      },
    ],
  };
  delete recovered.pendingCommand;
  delete recovered.pendingApproval;
  const target = output + "/recovered-record.json";
  try {
    await fs.access(target);
    throw Error("Existing recovery evidence: choose a new output directory");
  } catch (e) {
    if (e.code !== "ENOENT") throw e;
  }
  await fs.writeFile(target, JSON.stringify(recovered, null, 2) + "\n");
  const result = await verifyControlledRecord({
    page,
    origin,
    file: target,
    checks,
  });
  const trace = await page.locator(".agent-trace").textContent();
  assert(
    !trace.includes("等待结果"),
    "Ended tool must not promise a future result",
  );
  assert(trace.includes("未返回结果"));
  assert(
    (await page.locator("body").textContent()).includes("工具执行申请已被拒绝"),
  );
  checks.push(
    "Original denied command/approval recovered by GET only; no stale waiting, no second decision",
  );
  return { ...result, recoveredReadOnly: true };
}
