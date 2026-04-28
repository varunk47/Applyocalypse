import { existsSync, mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { spawn } from "node:child_process";

const rootDir = resolve(import.meta.dirname, "../..");
const defaultExe =
  process.platform === "win32"
    ? join(rootDir, "apps", "desktop", "release", "win-unpacked", "Applyocalypse.exe")
    : join(rootDir, "apps", "desktop", "release", "Applyocalypse");
const executable = process.env.APPLYO_DESKTOP_EXE || defaultExe;

if (!existsSync(executable)) {
  console.error(`Packaged desktop executable was not found: ${executable}`);
  process.exit(1);
}

const userDataDir = mkdtempSync(join(tmpdir(), "applyocalypse-user-flow-smoke-"));
const child = spawn(executable, [], {
  cwd: rootDir,
  env: {
    ...process.env,
    APPLYO_USER_FLOW_SMOKE: "1",
    APPLYO_DISABLE_SCHEDULER: "1",
    APPLYO_TEST_USER_DATA_DIR: userDataDir
  },
  shell: false,
  windowsHide: true,
  stdio: ["ignore", "pipe", "pipe"]
});

let output = "";
const timeout = setTimeout(() => {
  child.kill();
  console.error(output || "user-flow-smoke:timeout");
  cleanup(1);
}, 35_000);

const onData = (chunk) => {
  output += chunk.toString("utf8");
  if (output.includes("user-flow-smoke:passed")) {
    clearTimeout(timeout);
  }
};

child.stdout.on("data", onData);
child.stderr.on("data", onData);
child.on("error", (error) => {
  clearTimeout(timeout);
  console.error(error instanceof Error ? error.message : error);
  cleanup(1);
});
child.on("exit", (code) => {
  clearTimeout(timeout);
  if (code === 0 && output.includes("user-flow-smoke:passed")) {
    console.log("user-flow-smoke:passed");
    cleanup(0);
    return;
  }
  console.error(output || `user-flow-smoke:exit:${code ?? "unknown"}`);
  cleanup(code ?? 1);
});

function cleanup(code) {
  rmSync(userDataDir, { recursive: true, force: true });
  process.exit(code);
}
