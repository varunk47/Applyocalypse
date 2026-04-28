import { existsSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { spawn } from "node:child_process";

const __dirname = dirname(fileURLToPath(import.meta.url));
const rootDir = resolve(__dirname, "../..");
const serviceDir = join(rootDir, "services", "automation-python");
const venvPython =
  process.platform === "win32"
    ? join(serviceDir, ".venv-build", "Scripts", "python.exe")
    : join(serviceDir, ".venv-build", "bin", "python");
const python = existsSync(venvPython) ? venvPython : process.platform === "win32" ? "python.exe" : "python3";

const forwardedArgs = process.argv.slice(2);
const child = spawn(python, [
  "-m",
  "applyocalypse_automation.llm.provider_matrix",
  ...(forwardedArgs[0] === "--" ? forwardedArgs.slice(1) : forwardedArgs)
], {
  cwd: rootDir,
  env: {
    ...process.env,
    PYTHONPATH: process.env.PYTHONPATH ? `${serviceDir}${process.platform === "win32" ? ";" : ":"}${process.env.PYTHONPATH}` : serviceDir
  },
  shell: false,
  stdio: "inherit",
  windowsHide: true
});

child.on("error", (error) => {
  console.error(error instanceof Error ? error.message : error);
  process.exit(1);
});

child.on("exit", (code) => {
  process.exit(code ?? 1);
});
