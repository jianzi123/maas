// This explicit command preserves the known failing oracle; it does not turn it green.
import { spawn } from "node:child_process";
import { copyFile, mkdir, unlink } from "node:fs/promises";
import { constants } from "node:fs";
import path from "node:path";
import { root } from "./dev.mjs";
const temporary = path.join(root, "console/src/maas17-known-delete.test.ts");
const output = path.join(root, "artifacts/known-boundaries");
await mkdir(output, { recursive: true });
await copyFile(path.join(root, "test/maas17-review/delete-recovery-probe.test.ts.in"), temporary, constants.COPYFILE_EXCL);
try {
  const code = await new Promise((resolve, reject) => {
    const child = spawn(process.execPath, ["node_modules/vitest/vitest.mjs", "run", "src/maas17-known-delete.test.ts", "--pool", "threads", "--maxWorkers", "1", "--configLoader", "runner", "--no-cache", "--reporter", "verbose", "--reporter", "json", "--outputFile.json", path.join(output, "results.json")], { cwd: path.join(root, "console"), stdio: "inherit" });
    child.once("error", reject);
    child.once("close", resolve);
  });
  process.exitCode = code ?? 1;
} finally {
  await unlink(temporary);
}
