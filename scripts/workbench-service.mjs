// Windows/local fallback for a requested persistent workbench handoff.
// Lifecycle belongs to this detached host, not the coding-agent run.
import { startWorkbench, root } from "./dev.mjs";
import { mkdir, readFile, writeFile, open, unlink } from "node:fs/promises";
import path from "node:path";
import { randomUUID } from "node:crypto";

const directory = path.join(root, ".cache", "workbench-service");
const statusPath = path.join(directory, "status.json");
const stopPath = path.join(directory, "stop.json");
const lockPath = path.join(directory, "host.lock");
await mkdir(directory, { recursive: true });
const command = process.argv[2] || "start";
if (command === "status") {
  console.log(await readFile(statusPath, "utf8"));
} else if (command === "stop") {
  const status = JSON.parse(await readFile(statusPath, "utf8"));
  if (!["starting", "ready"].includes(status.state)) throw Error("Workbench is already stopped.");
  await writeFile(stopPath, JSON.stringify({ id: status.id }));
  console.log("Stop requested; wait for status.cleaned=true before starting again.");
} else if (command === "start") {
  const lock = await open(lockPath, "wx");
  const id = randomUUID();
  const started = new Date();
  const expires = new Date(started.getTime() + 8 * 3600000);
  let app, timer, watcher, stopping = false;
  const status = { id, pid: process.pid, state: "starting", started_at: started.toISOString(), expires_at: expires.toISOString(), url: null, cleaned: false };
  const save = () => writeFile(statusPath, JSON.stringify(status, null, 2));
  const stop = async () => { if (!stopping) { stopping = true; if (app) await app.stop(); } };
  try {
    await save();
    // A pre-ready stop is remembered and applied as soon as startup completes.
    watcher = setInterval(async () => {
      try { const request = JSON.parse(await readFile(stopPath, "utf8")); if (request.id === id) await stop(); } catch {}
    }, 500);
    timer = setTimeout(() => { void stop(); }, 8 * 3600000);
    app = await startWorkbench({ port: Number(process.env.MAAS_LOCAL_SERVICE_PORT || 4179) });
    status.url = app.url; status.state = "ready"; await save();
    console.log(JSON.stringify({ event: "ready", url: app.url, expires_at: expires.toISOString(), pid: process.pid }));
    if (stopping) await app.stop();
    const result = await app.exited;
    status.state = result.code ? "failed" : "stopped"; status.cleaned = result.cleaned;
    status.exit_code = result.code;
  } catch (error) {
    status.state = "failed"; status.error = error.message;
    if (app) { const result = await app.stop(); status.cleaned = result.cleaned; }
    console.error(error.message); process.exitCode = 1;
  } finally {
    clearTimeout(timer); clearInterval(watcher); await save(); await lock.close(); await unlink(lockPath);
  }
} else throw Error("Use start, status or stop.");
