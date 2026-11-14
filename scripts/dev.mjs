import { spawn } from "node:child_process";
import { createInterface } from "node:readline";
import { fileURLToPath } from "node:url";
import { access, mkdir } from "node:fs/promises";
import path from "node:path";
import { createRequire } from "node:module";

export const root = fileURLToPath(new URL("../", import.meta.url));
function npm(args, environment = {}) {
  return new Promise((resolve, reject) => {
    const child = spawn(
      process.platform === "win32" ? "npm.cmd" : "npm",
      args,
      {
        cwd: path.join(root, "console"),
        stdio: "inherit",
        shell: process.platform === "win32",
        env: {
          ...process.env,
          ...environment,
          npm_config_cache: path.join(root, ".cache", "npm"),
        },
      },
    );
    child.once("error", reject);
    child.once("exit", (code) =>
      code === 0 ? resolve() : reject(Error(`Frontend command exited ${code}`)),
    );
  });
}

export async function startWorkbench({
  port = 4179,
  build = true,
  quiet = false,
} = {}) {
  if (!Number.isInteger(port) || port < 0 || port > 65535)
    throw Error("Invalid local port");
  await mkdir(path.join(root, ".cache"), { recursive: true });
  try {
    await access(path.join(root, "console/node_modules/vite/package.json"));
  } catch {
    await npm([
      "ci",
      "--include=optional",
      "--fetch-retries=5",
      "--no-audit",
      "--no-fund",
    ]);
  }
  const require = createRequire(path.join(root, "console", "package.json"));
  try {
    require("lightningcss");
  } catch {
    await npm([
      "ci",
      "--include=optional",
      "--fetch-retries=5",
      "--no-audit",
      "--no-fund",
    ]);
  }
  if (build) await npm(["run", "build", "--", "--mode", "workbench"], {
    NODE_ENV: "development",
    VITE_LOCAL_CONTROL: "true",
    VITE_CONSOLE_FIXTURES: "false",
  });
  const win = process.platform === "win32";
  const command = win ? "wsl.exe" : "bash";
  const args = win
    ? [
        "--distribution",
        process.env.MAAS_WSL_DISTRO || "Ubuntu-22.04",
        "--exec",
        "env",
        `MAAS_WORKBENCH_PORT=${port}`,
        "bash",
        "scripts/workbench.sh",
      ]
    : ["scripts/workbench.sh"];
  const child = spawn(command, args, {
    cwd: root,
    stdio: ["pipe", "pipe", "pipe"],
    env: { ...process.env, MAAS_WORKBENCH_PORT: String(port) },
  });
  let readyResolve,
    readyReject,
    exitResolve,
    stopped = false,
    ready = false,
    cleaned = false;
  const started = new Promise((resolve, reject) => {
    readyResolve = resolve;
    readyReject = reject;
  });
  const exited = new Promise((resolve) => {
    exitResolve = resolve;
  });
  const reader = createInterface({ input: child.stdout });
  reader.on("line", (line) => {
    let value;
    try {
      value = JSON.parse(line);
    } catch {
      if (!quiet) console.log(line);
      return;
    }
    if (value.event === "ready") {
      ready = true;
      readyResolve(value);
    } else if (value.event === "stopped") cleaned = value.cleaned === true;
    else if (!quiet) console.log(line);
  });
  child.stderr.on("data", (chunk) => {
    if (!quiet) process.stderr.write(chunk);
  });
  child.once("error", (error) => {
    readyReject(error);
    exitResolve({ code: 1, cleaned });
  });
  child.once("close", (code) => {
    if (!ready)
      readyReject(
        Error(
          `Local backend exited ${code}. Install Ubuntu WSL2 and check the startup output.`,
        ),
      );
    exitResolve({ code, cleaned });
  });
  const stop = async () => {
    if (!stopped) {
      stopped = true;
      if (!child.stdin.destroyed) child.stdin.end("stop\n");
    }
    return await exited;
  };
  const interrupt = () => {
    void stop();
  };
  process.on("SIGINT", interrupt);
  process.on("SIGTERM", interrupt);
  exited.finally(() => {
    process.off("SIGINT", interrupt);
    process.off("SIGTERM", interrupt);
  });
  let info; try { info = await started; } catch (error) { error.cleaned = (await exited).cleaned; throw error; }
  return { ...info, stop, exited };
}

if (
  process.argv[1] &&
  path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)
) {
  try {
    const index = process.argv.indexOf("--port");
    const app = await startWorkbench({
      port: index < 0 ? 4179 : Number(process.argv[index + 1]),
    });
    console.log(`\nMaaS 工作台已启动：${app.url}`);
    console.log(
      "本地管理环境；模型推理未接入。Ctrl+C 停止并清理本次临时数据。",
    );
    const result = await app.exited;
    if (result.code) process.exitCode = result.code;
    else console.log("工作台及本次临时数据已清理。");
  } catch (error) {
    console.error(error.message);
    process.exitCode = 1;
  }
}
