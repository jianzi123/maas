import { spawn } from "node:child_process";
import { root } from "./dev.mjs";
const command = process.env.PYTHON || (process.platform === "win32" ? "python" : "python3");
const child = spawn(command, ["-m", "unittest", "discover", "-s", "scripts/tests", "-p", "test_*.py", "-v"], { cwd: root, stdio: "inherit" });
child.once("error", (error) => { console.error(error.message); process.exitCode = 1; });
child.once("close", (code) => { process.exitCode = code ?? 1; });
