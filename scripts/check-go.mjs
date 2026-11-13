import { spawn } from "node:child_process";
import { access } from "node:fs/promises";
import path from "node:path";
import { root } from "./dev.mjs";
const cachedGo =
  process.platform === "win32"
    ? path.join(root, ".cache", "go-windows", "bin", "go.exe")
    : path.join(root, ".cache", "go-linux", "go", "bin", "go");
let useCache = false;
try {
  await access(cachedGo);
  useCache = true;
} catch {}
const native = useCache || process.platform !== "win32";
const commands = [
  ["test", "./...", "-count=1"],
  ["vet", "./..."],
  ["build", "./cmd/...", "./deploy/console-server", "./deploy/probe"],
];
for (const args of commands) {
  const command = native ? (useCache ? cachedGo : "go") : "wsl.exe";
  const actual = native
    ? args
    : [
        "--distribution",
        process.env.MAAS_WSL_DISTRO || "Ubuntu-22.04",
        "--exec",
        "bash",
        "scripts/check-go.sh",
        ...args,
      ];
  const env = { ...process.env, GOTOOLCHAIN: "go1.26.0" };
  if (useCache)
    Object.assign(env, {
      GOROOT:
        process.platform === "win32"
          ? path.join(root, ".cache", "go-windows")
          : path.join(root, ".cache", "go-linux", "go"),
      GOMODCACHE: path.join(root, ".cache", "mod"),
      GOCACHE: path.join(root, ".cache", "build"),
      GOTOOLCHAIN: "local",
    });
  const code = await new Promise((resolve, reject) => {
    const child = spawn(command, actual, { cwd: root, stdio: "inherit", env });
    child.once("error", reject);
    child.once("exit", resolve);
  });
  if (code) {
    process.exitCode = code;
    break;
  }
}
