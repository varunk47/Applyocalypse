import { existsSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { randomUUID } from "node:crypto";
import { fileURLToPath } from "node:url";
import { spawn } from "node:child_process";

const __dirname = dirname(fileURLToPath(import.meta.url));
const rootDir = resolve(__dirname, "../..");
const workerName = process.platform === "win32" ? "applyocalypse-worker.exe" : "applyocalypse-worker";
const defaultWorker = join(rootDir, "apps", "desktop", "release", "win-unpacked", "resources", "automation-python", workerName);
const executable = process.env.APPLYO_WORKER_EXE || defaultWorker;

if (!existsSync(executable)) {
  console.error(`Packaged worker executable was not found: ${executable}`);
  process.exit(1);
}

const tempDir = mkdtempSync(join(tmpdir(), "applyocalypse-worker-smoke-"));
const workDir = join(tempDir, "work");
const outputDir = join(tempDir, "out");
const jobTextPath = join(tempDir, "job.txt");
const profilePath = join(tempDir, "profile.json");
const runId = randomUUID();

writeFileSync(
  jobTextPath,
  "Required: Python, TypeScript, SQLite. Build local desktop tools with clear user review controls.",
  "utf8"
);
writeFileSync(
  profilePath,
  JSON.stringify(
    {
      profile: {
        legalName: "Mary Jackson",
        displayName: "Mary Jackson",
        email: "mary@example.com",
        phone: "555-0100",
        location: "Hampton, VA"
      },
      skillGroups: [{ label: "Engineering", skills: ["Python", "TypeScript", "SQLite"] }],
      experience: [
        {
          title: "Software Engineer",
          company: "Local Systems Lab",
          bullets: ["Built Python and TypeScript tools for local operator workflows."]
        }
      ],
      projects: []
    },
    null,
    2
  ),
  "utf8"
);

const child = spawn(
  executable,
  [
    "--run-id",
    runId,
    "--job-text-file",
    jobTextPath,
    "--profile-json-file",
    profilePath,
    "--work-dir",
    workDir,
    "--output-dir",
    outputDir
  ],
  {
    cwd: rootDir,
    env: process.env,
    shell: false,
    windowsHide: true,
    stdio: ["ignore", "pipe", "pipe"]
  }
);

let stdout = "";
let stderr = "";
const timeout = setTimeout(() => {
  child.kill();
  finish(1, "worker-smoke:timeout");
}, 45_000);

child.stdout.on("data", (chunk) => {
  stdout += chunk.toString("utf8");
});
child.stderr.on("data", (chunk) => {
  stderr += chunk.toString("utf8");
});
child.on("error", (error) => {
  clearTimeout(timeout);
  finish(1, error instanceof Error ? error.message : String(error));
});
child.on("exit", (code) => {
  clearTimeout(timeout);
  if (code !== 0) {
    finish(code ?? 1, stderr || stdout || `worker-smoke:exit:${code ?? "unknown"}`);
    return;
  }

  const events = stdout
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => JSON.parse(line));
  const eventTypes = new Set(events.map((event) => event.event_type));
  const requiredEvents = ["RUN_STARTED", "JD_ANALYSIS_COMPLETED", "RESUME_RENDERED", "PAUSED"];
  const missing = requiredEvents.filter((eventType) => !eventTypes.has(eventType));
  if (missing.length > 0) {
    finish(1, `worker-smoke:missing-events:${missing.join(",")}`);
    return;
  }
  console.log("worker-smoke:ok");
  finish(0);
});

function finish(code, message) {
  if (message) {
    console.error(message);
    if (stderr) {
      console.error(stderr);
    }
  }
  rmSync(tempDir, { recursive: true, force: true });
  process.exit(code);
}
