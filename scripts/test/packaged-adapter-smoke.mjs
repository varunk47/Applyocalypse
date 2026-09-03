// Does the shipped binary still contain the browser drivers it will need?
//
// Every adapter imports its driver inside launch() and degrades a missing one to a soft
// "<name> is not installed" step result, so a driver that fell out of the PyInstaller
// bundle produces no build error and no failing test. It surfaces as a run that quietly
// falls back, or fails outright, in front of a user partway through an application.
//
// The rest of the packaged suite never reaches that code: packaged-worker-smoke.mjs stops
// at PAUSED, which is document review, before any browser is asked for. This asks the
// binary directly instead, with no browser started and no network touched.

import { existsSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { spawn } from "node:child_process";
import { smokeBudgetMs, timeoutMessage } from "./smoke-budget.mjs";

const __dirname = dirname(fileURLToPath(import.meta.url));
const rootDir = resolve(__dirname, "../..");
const workerName = process.platform === "win32" ? "applyocalypse-worker.exe" : "applyocalypse-worker";
const defaultWorker = join(rootDir, "apps", "desktop", "release", "win-unpacked", "resources", "automation-python", workerName);
const executable = process.env.APPLYO_WORKER_EXE || defaultWorker;

if (!existsSync(executable)) {
  console.error(`Packaged worker executable was not found: ${executable}`);
  process.exit(1);
}

const child = spawn(executable, ["self-check"], {
  cwd: rootDir,
  env: process.env,
  shell: false,
  windowsHide: true,
  stdio: ["ignore", "pipe", "pipe"]
});

let stdout = "";
let stderr = "";
const budgetMs = smokeBudgetMs();
const timeout = setTimeout(() => {
  child.kill();
  fail(timeoutMessage("adapter-smoke", budgetMs, `${stdout}${stderr}`));
}, budgetMs);

child.stdout.on("data", (chunk) => {
  stdout += chunk.toString("utf8");
});
child.stderr.on("data", (chunk) => {
  stderr += chunk.toString("utf8");
});
child.on("error", (error) => {
  clearTimeout(timeout);
  fail(error instanceof Error ? error.message : String(error));
});
child.on("exit", (code) => {
  clearTimeout(timeout);

  const line = stdout
    .split(/\r?\n/)
    .map((entry) => entry.trim())
    .filter((entry) => entry.startsWith("{"))
    .at(-1);
  if (!line) {
    // An exit with no JSON means the subcommand is missing from this build, which is a
    // different failure from a driver being missing and deserves to read differently.
    fail(`adapter-smoke:no-report:exit:${code ?? "unknown"}\n${stderr || stdout}`);
    return;
  }

  let report;
  try {
    report = JSON.parse(line);
  } catch (error) {
    fail(`adapter-smoke:unparsable-report:${error instanceof Error ? error.message : String(error)}\n${line}`);
    return;
  }

  const drivers = Array.isArray(report.drivers) ? report.drivers : [];
  const required = drivers.filter((driver) => driver.required);
  if (required.length === 0) {
    fail(`adapter-smoke:no-required-drivers-reported\n${line}`);
    return;
  }

  const missing = required.filter((driver) => !driver.available);
  if (missing.length > 0) {
    const detail = missing.map((driver) => `${driver.adapter} (${driver.module}): ${driver.error}`).join("\n  ");
    fail(`adapter-smoke:missing-drivers\n  ${detail}`);
    return;
  }

  if (code !== 0) {
    fail(`adapter-smoke:exit:${code ?? "unknown"} despite every required driver importing\n${stderr || line}`);
    return;
  }

  const names = required.map((driver) => driver.adapter).join(", ");
  console.log(`adapter-smoke:ok (${names})`);
  process.exit(0);
});

/** @param {string} message */
function fail(message) {
  console.error(message);
  if (stderr) {
    console.error(stderr);
  }
  process.exit(1);
}
