import fs from "node:fs/promises";
import path from "node:path";
import { spawn, execFileSync } from "node:child_process";
import { once } from "node:events";
import assert from "node:assert/strict";
const backend = path.resolve(
  process.env.MAAS_AR1_BACKEND_ROOT || "../../ar1-backend",
);
if (
  process.env.MAAS_AR1_BROWSER_PROFILE &&
  !["official", "extended"].includes(process.env.MAAS_AR1_BROWSER_PROFILE)
)
  throw Error("MAAS_AR1_BROWSER_PROFILE must be official or extended.");
const expected = "19e43ba980f1bd9f499a92dda435b74b626bf7e9";
assert.equal(
  execFileSync("git", ["rev-parse", "HEAD"], {
    cwd: backend,
    encoding: "utf8",
  }).trim(),
  expected,
);
const artifacts = path.resolve("artifacts/chat-ar1");
await fs.mkdir(artifacts, { recursive: true });
const build = async (args) => {
  const p = spawn("go", args, {
    cwd: backend,
    windowsHide: true,
    stdio: "inherit",
    env: { ...process.env, GOCACHE: path.join(backend, ".cache/go-build") },
  });
  const [code] = await once(p, "exit");
  assert.equal(code, 0, "controlled Go build failed");
};
const official = path.join(backend, ".cache/ar1-headless.exe");
await build([
  "build",
  "-tags",
  "agentcontrolled",
  "-o",
  official,
  "./cmd/agent-headless",
]);
const harnessDir = path.join(backend, ".cache/chat-browser-source");
await fs.mkdir(harnessDir, { recursive: true });
let http = await fs.readFile(
  path.join(backend, "cmd/agent-headless/http.go"),
  "utf8",
);
const registry = "a.NewRegistry(a.Calculator{},";
assert.equal(http.split(registry).length, 2);
http = http.replace(registry, "a.NewRegistry(approvalTool{a.Calculator{}},");
const permission = '"models.read": true}';
assert.equal(http.split(permission).length, 2);
http = http.replace(permission, '"models.read": true, "tools.approve": true}');
const lifecycle = "defer stop()";
assert.equal(http.split(lifecycle).length, 2);
http = http.replace(
  lifecycle,
  lifecycle +
    '\n go func() { var line string; fmt.Fscanln(os.Stdin, &line); if line == "stop" { stop() } }()',
);
await fs.writeFile(path.join(harnessDir, "http.go"), http);
await fs.copyFile(
  "scripts/ar1-browser-model.go.txt",
  path.join(harnessDir, "main.go"),
);
const harness = path.join(backend, ".cache/ar1-browser.exe");
await build([
  "build",
  "-tags",
  "agentcontrolled",
  "-o",
  harness,
  "./.cache/chat-browser-source",
]);
const handles = [];
for (const [profile, exe, port] of [
  ["official", official, 4188],
  ["extended", harness, 4189],
]) {
  if (
    process.env.MAAS_AR1_BROWSER_PROFILE &&
    profile !== process.env.MAAS_AR1_BROWSER_PROFILE
  )
    continue;
  const stateDir = path.join(
    backend,
    ".cache/chat-ar1-" + profile + "-" + Date.now(),
  );
  const child = spawn(
    exe,
    [
      "--state-dir",
      stateDir,
      "--owner-id",
      "4c421973-919f-4b8a-997f-909fc6fd010a",
      "--listen",
      "127.0.0.1:" + port,
    ],
    { cwd: backend, windowsHide: true, stdio: ["pipe", "pipe", "pipe"] },
  );
  const exited = once(child, "exit");
  let logs = "";
  child.stdout.on("data", (b) => {
    logs += b.toString();
  });
  child.stderr.on("data", (b) => {
    logs += b.toString();
  });
  const handle = {
    profile,
    pid: child.pid,
    port,
    stateDir,
    backend: expected,
    stopped: false,
    cleanup: "",
  };
  handles.push(handle);
  try {
    let ready = false;
    for (let attempt = 0; attempt < 100; attempt++) {
      if (child.exitCode !== null)
        throw Error("AR-1 exited before readiness: " + logs);
      try {
        const r = await fetch(
          "http://127.0.0.1:" + port + "/api/agent/v1/capabilities",
          { signal: AbortSignal.timeout(300) },
        );
        ready = r.status === 401;
      } catch {}
      if (ready) break;
      await new Promise((resolve) => setTimeout(resolve, 100));
    }
    assert(ready, "Go AR-1 was not ready");
    const browser = spawn(process.execPath, ["scripts/chat-ar1-browser.mjs"], {
      cwd: process.cwd(),
      windowsHide: true,
      stdio: "inherit",
      env: {
        ...process.env,
        MAAS_AR1_BROWSER_API: "http://127.0.0.1:" + port,
        MAAS_AR1_BROWSER_EXTENDED: profile === "extended" ? "1" : "0",
      },
    });
    const [code] = await once(browser, "exit");
    assert.equal(code, 0, profile + " browser checks failed");
  } finally {
    if (child.exitCode === null && profile === "extended") {
      child.stdin.write("stop\n");
      await Promise.race([
        exited,
        new Promise((resolve) => setTimeout(resolve, 5000)),
      ]);
    }
    if (child.exitCode === null) {
      // Windows has no portable SIGINT for a non-console child. Terminate ONLY
      // this owned child handle; never an executable name or the daemon.
      child.kill();
      handle.cleanup =
        "owned child handle terminated; original state retained (no lock stealing)";
    } else handle.cleanup = "stdin-requested graceful Go Host/HTTP shutdown";
    await exited;
    await fs.writeFile(path.join(artifacts, profile + "-server.log"), logs);
    try {
      await fetch("http://127.0.0.1:" + port + "/api/agent/v1/capabilities", {
        signal: AbortSignal.timeout(400),
      });
      throw Error("Owned AR-1 listener still available after cleanup");
    } catch (e) {
      if (e.message?.includes("still available")) throw e;
      handle.stopped = true;
    }
    await fs.writeFile(
      path.join(artifacts, profile + "-process.json"),
      JSON.stringify(handle, null, 2),
    );
    await fs.writeFile(
      path.join(artifacts, "process-handles.json"),
      JSON.stringify(handles, null, 2),
    );
  }
}
