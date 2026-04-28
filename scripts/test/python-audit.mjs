import { existsSync } from "node:fs";
import { mkdir } from "node:fs/promises";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { spawn } from "node:child_process";

const __dirname = dirname(fileURLToPath(import.meta.url));
const rootDir = resolve(__dirname, "../..");
const serviceDir = join(rootDir, "services", "automation-python");
const venvDir = join(serviceDir, ".venv-build");
const isWindows = process.platform === "win32";
const hostPython = process.env.APPLYO_PYTHON ?? (isWindows ? "python" : "python3");
const venvPython = isWindows ? join(venvDir, "Scripts", "python.exe") : join(venvDir, "bin", "python");

const run = async (command, args, options = {}) => {
  await new Promise((resolvePromise, rejectPromise) => {
    const child = spawn(command, args, {
      cwd: options.cwd ?? serviceDir,
      env: process.env,
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

const main = async () => {
  if (!existsSync(venvPython)) {
    await mkdir(venvDir, { recursive: true });
    await run(hostPython, ["-m", "venv", venvDir], { cwd: rootDir });
  }

  await run(venvPython, ["-m", "pip", "install", "--disable-pip-version-check", "--quiet", "-r", join(serviceDir, "requirements.txt")]);
  await run(venvPython, ["-m", "pip", "install", "--disable-pip-version-check", "--quiet", "-r", join(serviceDir, "requirements-audit.txt")]);
  await run(venvPython, ["-m", "pip_audit", "-r", join(serviceDir, "requirements.txt"), "--strict"]);
};

main().catch((error) => {
  console.error(error instanceof Error ? error.message : error);
  process.exit(1);
});
