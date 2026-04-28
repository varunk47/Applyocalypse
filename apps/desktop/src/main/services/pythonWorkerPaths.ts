import { app } from "electron";
import { existsSync } from "node:fs";
import { join, resolve } from "node:path";

export type PythonWorkerLaunch = {
  executable: string;
  baseArgs: string[];
  cwd: string;
};

export const resolvePythonWorkerCwd = (): string => {
  if (process.env.APPLYO_WORKER_CWD) {
    return process.env.APPLYO_WORKER_CWD;
  }

  if (app.isPackaged) {
    return join(process.resourcesPath, "automation-python");
  }

  return resolve(app.getAppPath(), "../..", "services", "automation-python");
};

export const resolveBundledPythonWorkerExecutable = (): string => {
  const executableName = process.platform === "win32" ? "applyocalypse-worker.exe" : "applyocalypse-worker";
  return join(process.resourcesPath, "automation-python", executableName);
};

export const resolvePythonWorkerLaunch = (): PythonWorkerLaunch => {
  const cwd = resolvePythonWorkerCwd();

  if (process.env.APPLYO_WORKER_EXE) {
    return {
      executable: process.env.APPLYO_WORKER_EXE,
      baseArgs: [],
      cwd
    };
  }

  if (app.isPackaged) {
    const executable = resolveBundledPythonWorkerExecutable();
    if (!existsSync(executable)) {
      throw new Error(`Bundled Applyocalypse worker was not found at ${executable}`);
    }
    return {
      executable,
      baseArgs: [],
      cwd
    };
  }

  return {
    executable: process.env.APPLYO_PYTHON ?? "python",
    baseArgs: ["-m", "applyocalypse_automation.runner"],
    cwd
  };
};
