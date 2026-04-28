import { EventEmitter } from "node:events";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { PassThrough } from "node:stream";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  JobRepository,
  ProfileRepository,
  QueueRepository,
  RunRepository,
  closeApplyocalypseDatabase,
  openApplyocalypseDatabase,
  runMigrations,
  type ApplyocalypseDatabase
} from "@applyocalypse/db";
import { redactSensitiveSupervisorText } from "./sensitiveRedaction";

type MockChild = EventEmitter & {
  stdout: PassThrough;
  stderr: PassThrough;
  kill: ReturnType<typeof vi.fn>;
};

const tempDirs: string[] = [];

const createMockChild = (): MockChild => {
  const child = new EventEmitter() as MockChild;
  child.stdout = new PassThrough();
  child.stderr = new PassThrough();
  child.kill = vi.fn(() => {
    child.emit("exit", null, "SIGTERM");
    return true;
  });
  return child;
};

const loadSupervisorWithChild = async (child: MockChild) => {
  vi.resetModules();
  vi.doMock("node:child_process", () => ({ spawn: vi.fn(() => child) }));
  vi.doMock("./pythonWorkerPaths", () => ({
    resolvePythonWorkerLaunch: () => ({
      executable: process.execPath,
      baseArgs: ["worker.js"],
      cwd: process.cwd()
    })
  }));
  const module = await import("./pythonWorkerSupervisor");
  return module.PythonWorkerSupervisor;
};

const createDb = (): { db: ApplyocalypseDatabase; dir: string } => {
  const dir = mkdtempSync(join(tmpdir(), "applyocalypse-supervisor-"));
  tempDirs.push(dir);
  const db = openApplyocalypseDatabase(join(dir, "test.sqlite"));
  runMigrations(db, resolve(process.cwd(), "packages/db/migrations"));
  return { db, dir };
};

const createRun = (db: ApplyocalypseDatabase): { runId: string; queueItemId: string } => {
  const profile = new ProfileRepository(db).createStarterProfile({ legalName: "Joan Clarke" });
  const { queueItems, jobTargets } = new JobRepository(db).enqueueTargets({
    profileId: profile.id,
    items: [{ sourceKind: "TEXT", sourceValue: "Role requiring TypeScript" }]
  });
  const run = new RunRepository(db).createApplicationRun({
    queueItemId: queueItems[0]!.id,
    profileId: profile.id,
    jobTargetId: jobTargets[0]!.id,
    workerId: "worker-a"
  });
  db.prepare("UPDATE application_runs SET status = 'RUNNING_AUTOMATION' WHERE id = ?").run(run.id);
  db.prepare("UPDATE queue_items SET status = 'RUNNING_AUTOMATION', claimed_by = 'worker-a' WHERE id = ?").run(queueItems[0]!.id);
  return { runId: run.id, queueItemId: queueItems[0]!.id };
};

afterEach(() => {
  vi.doUnmock("node:child_process");
  vi.doUnmock("./pythonWorkerPaths");
  vi.restoreAllMocks();
  vi.resetModules();
  for (const dir of tempDirs.splice(0)) {
    rmSync(dir, { recursive: true, force: true });
  }
});

describe("python worker supervisor redaction", () => {
  it("redacts provider secrets and common credential assignments before persistence", () => {
    const redacted = redactSensitiveSupervisorText(
      "worker failed with OPENAI_API_KEY=sk-live-secret and token=plain-token and copied sk-live-secret",
      { OPENAI_API_KEY: "sk-live-secret" }
    );

    expect(redacted).not.toContain("sk-live-secret");
    expect(redacted).not.toContain("plain-token");
    expect(redacted).toContain("OPENAI_API_KEY=[REDACTED]");
    expect(redacted).toContain("token=[REDACTED]");
  });

  it("does not redact short non-secret values from diagnostic messages", () => {
    expect(redactSensitiveSupervisorText("exit code 1", { OPENAI_API_KEY: "abc" })).toBe("exit code 1");
  });
});

describe("python worker supervisor lifecycle", () => {
  it("pauses active runs and clears queue claims when a worker exits unexpectedly", async () => {
    const { db, dir } = createDb();
    try {
      const { runId, queueItemId } = createRun(db);
      const child = createMockChild();
      const send = vi.fn();
      const PythonWorkerSupervisor = await loadSupervisorWithChild(child);
      const supervisor = new PythonWorkerSupervisor(
        db,
        () =>
          [
            {
              isDestroyed: () => false,
              webContents: { send }
            }
          ] as never,
        () => [dir]
      );

      supervisor.start({ runId, workDir: dir });
      child.emit("exit", 1, null);

      const run = new RunRepository(db).getApplicationRun(runId);
      const queueItem = new QueueRepository(db).getById(queueItemId);
      const event = db.prepare("SELECT event_type, severity, message, payload_json FROM run_events WHERE application_run_id = ?").get(runId) as {
        event_type: string;
        severity: string;
        message: string;
        payload_json: string;
      };
      const runRow = db.prepare("SELECT worker_id, lease_expires_at, heartbeat_at FROM application_runs WHERE id = ?").get(runId) as {
        worker_id: string | null;
        lease_expires_at: string | null;
        heartbeat_at: string | null;
      };

      expect(run.status).toBe("PAUSED");
      expect(run.failureCode).toBe("WORKER_EXITED_UNEXPECTEDLY");
      expect(runRow.worker_id).toBeNull();
      expect(runRow.lease_expires_at).toBeNull();
      expect(runRow.heartbeat_at).toBeNull();
      expect(queueItem.status).toBe("PAUSED");
      expect(queueItem.claimedBy).toBeNull();
      expect(queueItem.leaseExpiresAt).toBeNull();
      expect(queueItem.heartbeatAt).toBeNull();
      expect(event.event_type).toBe("PAUSED");
      expect(event.severity).toBe("ERROR");
      expect(event.message).toContain("exited unexpectedly");
      expect(event.payload_json).toContain("WORKER_EXITED_UNEXPECTEDLY");
      expect(send).toHaveBeenCalledWith("logs:event", expect.objectContaining({ eventType: "PAUSED", runId, severity: "ERROR" }));
    } finally {
      closeApplyocalypseDatabase(db);
    }
  });

  it("does not overwrite terminal runs when a worker exits after completion", async () => {
    const { db, dir } = createDb();
    try {
      const { runId, queueItemId } = createRun(db);
      db.prepare("UPDATE application_runs SET status = 'COMPLETED', failure_code = NULL, failure_message = NULL WHERE id = ?").run(runId);
      db.prepare("UPDATE queue_items SET status = 'COMPLETED' WHERE id = ?").run(queueItemId);
      const child = createMockChild();
      const PythonWorkerSupervisor = await loadSupervisorWithChild(child);
      const supervisor = new PythonWorkerSupervisor(db, () => [], () => [dir]);

      supervisor.start({ runId, workDir: dir });
      child.emit("exit", 0, null);

      const run = new RunRepository(db).getApplicationRun(runId);
      const events = new RunRepository(db).listRunEvents(runId);
      expect(run.status).toBe("COMPLETED");
      expect(run.failureCode).toBeNull();
      expect(events).toHaveLength(0);
    } finally {
      closeApplyocalypseDatabase(db);
    }
  });

  it("treats supervisor stop as intentional and leaves status changes to the control path", async () => {
    const { db, dir } = createDb();
    try {
      const { runId } = createRun(db);
      const child = createMockChild();
      const PythonWorkerSupervisor = await loadSupervisorWithChild(child);
      const supervisor = new PythonWorkerSupervisor(db, () => [], () => [dir]);

      supervisor.start({ runId, workDir: dir });
      expect(supervisor.stop(runId)).toBe(true);

      const run = new RunRepository(db).getApplicationRun(runId);
      expect(child.kill).toHaveBeenCalledTimes(1);
      expect(run.status).toBe("RUNNING_AUTOMATION");
      expect(new RunRepository(db).listRunEvents(runId)).toHaveLength(0);
    } finally {
      closeApplyocalypseDatabase(db);
    }
  });
});
