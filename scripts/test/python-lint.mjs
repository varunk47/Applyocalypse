import { spawn } from "node:child_process";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const rootDir = resolve(__dirname, "../..");
const serviceDir = join(rootDir, "services", "automation-python");
const venvDir = join(serviceDir, ".venv-build");
const venvPython =
  process.platform === "win32" ? join(venvDir, "Scripts", "python.exe") : join(venvDir, "bin", "python");

const run = async (command, args, options = {}) => {
  await new Promise((resolvePromise, rejectPromise) => {
    const child = spawn(command, args, {
      cwd: options.cwd ?? serviceDir,
      env: {
        ...process.env,
        ...(options.env ?? {})
      },
      shell: false,
      stdio: "inherit",
      windowsHide: true
    });

    child.on("error", rejectPromise);
    child.on("exit", (code) => {
      if (code === 0) {
        resolvePromise();
        return;
      }
      rejectPromise(new Error(`${command} ${args.join(" ")} exited with ${code}`));
    });
  });
};

run(process.execPath, ["scripts/dev/ensure-python-env.mjs"], { cwd: rootDir })
  .then(() => run(venvPython, ["-m", "ruff", "check", "applyocalypse_automation", "evals", "tests"]))
  .catch((error) => {
    console.error(error instanceof Error ? error.message : error);
    process.exit(1);
  });
