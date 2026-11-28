// Explicit restart acceptance for an owned offline Compose project, never a provider.
import fs from "node:fs/promises";
import path from "node:path";
import { spawnSync } from "node:child_process";
import assert from "node:assert/strict";
import { chromium } from "playwright-core";
import { verifyControlledRecord } from "./deployed-workbench.mjs";
assert.equal(
  process.env.MAAS_SMOKE_RESTART,
  "1",
  "Explicit owned-service restart opt-in required",
);
const root = process.env.MAAS_COMPOSE_DIRECTORY,
  expectedProject = process.env.MAAS_COMPOSE_PROJECT,
  raw = process.env.MAAS_CONSOLE_URL,
  file = process.env.MAAS_SMOKE_VERIFY_RECORD;
assert(
  root &&
    expectedProject &&
    raw &&
    file &&
    process.env.MAAS_SMOKE_USERNAME &&
    process.env.MAAS_SMOKE_PASSWORD,
);
const origin = new URL(raw);
assert(
  ["localhost", "127.0.0.1", "[::1]"].includes(origin.hostname) &&
    !origin.username &&
    !origin.password &&
    origin.pathname === "/",
);
const privateConfig = JSON.parse(
  await fs.readFile(path.join(root, "config/product.json"), "utf8"),
);
assert(
  privateConfig.offline_controlled?.enabled === true &&
    privateConfig.origin === origin.origin,
);
const installEnv = await fs.readFile(path.join(root, ".env"), "utf8");
assert(
  installEnv.split(/\r?\n/).includes("COMPOSE_PROJECT_NAME=" + expectedProject),
);
const dir = process.env.MAAS_SMOKE_OUTPUT || "artifacts/deployed-restart";
await fs.mkdir(dir, { recursive: true });
const network = [],
  checks = [],
  phases = [];
let browser;
const docker = (args) => {
  const r = spawnSync(
    process.platform === "win32" ? "docker.exe" : "docker",
    ["compose", "--project-directory", root, ...args],
    { encoding: "utf8", windowsHide: true },
  );
  if (r.status !== 0)
    throw Error("Owned Compose command failed: " + args.join(" "));
  return r.stdout;
};
function sqlCounts() {
  const text = docker([
    "run",
    "--rm",
    "--no-deps",
    "--entrypoint",
    "mysql",
    "migrate",
    "--defaults-extra-file=/run/secrets/mysql-client.cnf",
    "-N",
    "-B",
    "-D",
    "maas",
    "-e",
    "SELECT (SELECT COUNT(*) FROM generation_requests),(SELECT COUNT(*) FROM usage_events)",
  ]);
  const parts = text.trim().split(/\s+/).map(Number);
  assert(parts.length === 2 && parts.every(Number.isFinite));
  return { requests: parts[0], usages: parts[1] };
}
async function ready() {
  for (let i = 0; i < 120; i++) {
    try {
      const r = await fetch(origin.origin + "/readyz");
      if (r.ok) {
        const v = await r.json();
        assert.equal(v.persistence, "mysql");
        assert.equal(v.profile, "offline-controlled");
        return;
      }
    } catch {}
    await new Promise((resolve) => setTimeout(resolve, 500));
  }
  throw Error("Owned Go/MySQL did not recover readiness");
}
try {
  await ready();
  const containers = docker(["ps", "--format", "json"])
    .trim()
    .split(/\r?\n/)
    .map((line) => JSON.parse(line));
  assert(
    containers.length >= 3 &&
      containers.every((c) => c.Project === expectedProject),
  );
  const before = sqlCounts();
  browser = await chromium.launch({
    executablePath:
      process.env.EDGE_PATH ||
      "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
    headless: true,
  });
  const page = await browser.newPage({
    viewport: { width: 1440, height: 1000 },
  });
  page.on("request", (r) => {
    const u = new URL(r.url());
    if (u.pathname.startsWith("/api/"))
      network.push({ method: r.method(), path: u.pathname });
  });
  await page.goto(origin.origin + "/#chat");
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
  const session = async () => {
    const r = await page
      .context()
      .request.get(origin.origin + "/api/admin/v1/session", {
        maxRedirects: 0,
      });
    assert.equal(r.status(), 200);
    return r.json();
  };
  const original = await session();
  const cookie = (await page.context().cookies()).find(
    (c) => c.name === "maas_session",
  );
  assert(cookie?.httpOnly);
  await verifyControlledRecord({ page, origin: origin.origin, file, checks });
  const start = network.length;
  for (const service of ["maas", "mysql"]) {
    docker(["restart", service]);
    await ready();
    await verifyControlledRecord({ page, origin: origin.origin, file, checks });
    const current = await session(),
      now = (await page.context().cookies()).find(
        (c) => c.name === "maas_session",
      );
    assert(current.admin_id === original.admin_id);
    assert(current.csrf_token === original.csrf_token);
    assert(now?.value === cookie.value);
    phases.push({
      service,
      originalPrincipal: true,
      originalCookie: true,
      originalCSRF: true,
      originalRecords: true,
    });
    await page.screenshot({
      path: dir + "/" + service + "-recovered.png",
      fullPage: false,
    });
  }
  assert(network.slice(start).every((r) => r.method === "GET"));
  const after = sqlCounts();
  assert.deepEqual(after, before);
  await page.getByRole("button", { name: "退出会话", exact: true }).click();
  await fs.writeFile(
    dir + "/results.json",
    JSON.stringify(
      {
        scope: "Owned normal Go/MySQL offline-controlled; no real provider",
        project: expectedProject,
        phases,
        before,
        after,
        generationPostIncrement: 0,
        checks,
        network,
      },
      null,
      2,
    ),
  );
  console.log(
    JSON.stringify({
      phases: phases.length,
      generationPostIncrement: 0,
      unchangedLedger: true,
    }),
  );
} catch (e) {
  const safe = String(e.message)
    .split(process.env.MAAS_SMOKE_PASSWORD)
    .join("[REDACTED]");
  await fs.writeFile(
    dir + "/failure.json",
    JSON.stringify({ message: safe, phases, checks, network }, null, 2),
  );
  console.error(safe);
  process.exitCode = 1;
} finally {
  await browser?.close();
}
