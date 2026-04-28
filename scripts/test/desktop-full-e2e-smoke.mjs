import { existsSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
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

const userDataDir = mkdtempSync(join(tmpdir(), "applyocalypse-full-e2e-user-data-"));
const fixtureDir = mkdtempSync(join(tmpdir(), "applyocalypse-full-e2e-fixtures-"));
const resumePath = join(fixtureDir, "ada-lovelace-resume.tex");
const detailsPath = join(fixtureDir, "ada-lovelace-projects.md");

writeFileSync(
  resumePath,
  String.raw`\documentclass{article}
\begin{document}
\section{Summary}
Compiler and platform engineer with TypeScript, Python, and SQLite automation experience.
\section{Skills}
TypeScript, Python, SQLite, Electron, browser automation
\section{Experience}
\begin{itemize}
\item Built local-first tooling with human review controls.
\end{itemize}
\end{document}
`,
  "utf8"
);

writeFileSync(
  detailsPath,
  "Project notes: built deterministic document generation, queue recovery, and browser automation review gates.\n",
  "utf8"
);

const runPhase = (phase) =>
  new Promise((resolvePromise, rejectPromise) => {
    const approvedPaths = JSON.stringify([resumePath, detailsPath]);
    const child = spawn(executable, [], {
      cwd: rootDir,
      env: {
        ...process.env,
        APPLYO_FULL_E2E_SMOKE: "1",
        APPLYO_FULL_E2E_SMOKE_PHASE: phase,
        APPLYO_FULL_E2E_RESUME_PATH: resumePath,
        APPLYO_FULL_E2E_DETAILS_PATH: detailsPath,
        APPLYO_TEST_APPROVED_PATHS_JSON: approvedPaths,
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
      rejectPromise(new Error(output || `full-e2e-smoke:${phase}:timeout`));
    }, 45_000);

    const onData = (chunk) => {
      output += chunk.toString("utf8");
    };

    child.stdout.on("data", onData);
    child.stderr.on("data", onData);
    child.on("error", (error) => {
      clearTimeout(timeout);
      rejectPromise(error);
    });
    child.on("exit", (code) => {
      clearTimeout(timeout);
      if (code === 0 && output.includes(`full-e2e-smoke:${phase}:passed`)) {
        resolvePromise(output);
        return;
      }
      rejectPromise(new Error(output || `full-e2e-smoke:${phase}:exit:${code ?? "unknown"}`));
    });
  });

try {
  await runPhase("phase1");
  await runPhase("phase2");
  console.log("full-e2e-smoke:passed");
} catch (error) {
  console.error(error instanceof Error ? error.message : error);
  process.exitCode = 1;
} finally {
  rmSync(userDataDir, { recursive: true, force: true });
  rmSync(fixtureDir, { recursive: true, force: true });
}
