import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import { mkdir } from "node:fs/promises";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const rootDir = resolve(__dirname, "../..");
const serviceDir = join(rootDir, "services", "automation-python");
const venvDir = join(serviceDir, ".venv-build");
const hostPython = process.env.APPLYO_PYTHON ?? (process.platform === "win32" ? "python.exe" : "python3");
const venvPython =
  process.platform === "win32"
    ? join(venvDir, "Scripts", "python.exe")
    : join(venvDir, "bin", "python");

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

const ensurePythonEnvironment = async () => {
  if (!existsSync(venvPython)) {
    await mkdir(venvDir, { recursive: true });
    await run(hostPython, ["-m", "venv", venvDir], { cwd: rootDir });
    await run(venvPython, [
      "-m",
      "pip",
      "install",
      "--disable-pip-version-check",
      "--quiet",
      "-r",
      join(serviceDir, "requirements.txt")
    ]);
  }
};

ensurePythonEnvironment()
  .then(() =>
    run(venvPython, ["-m", "pytest", "tests"], {
      env: {
        PYTEST_DISABLE_PLUGIN_AUTOLOAD: "1"
      }
    })
  )
  .catch((error) => {
    console.error(error instanceof Error ? error.message : error);
    process.exit(1);
  });
