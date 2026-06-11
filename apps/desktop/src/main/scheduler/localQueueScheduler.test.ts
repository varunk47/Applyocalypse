import { existsSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  JobRepository,
  ParsedDocumentRepository,
  ProfileRepository,
  QueueRepository,
  RunRepository,
  SettingsRepository,
  UploadRepository,
  closeApplyocalypseDatabase,
  openApplyocalypseDatabase,
  runMigrations,
  type ApplyocalypseDatabase
} from "@applyocalypse/db";
import type { PythonWorkerSupervisor } from "../services/pythonWorkerSupervisor";
import type { StartWorkerInput } from "../services/pythonWorkerSupervisor";
import { LocalQueueScheduler } from "./localQueueScheduler";

const electronPaths = vi.hoisted(() => ({
  userData: "",
  downloads: "",
  temp: ""
}));

vi.mock("electron", () => ({
  app: {
    getPath: (name: "userData" | "downloads" | "temp") => electronPaths[name] || electronPaths.userData
  }
}));

const tempDirs: string[] = [];

const createDb = (): { db: ApplyocalypseDatabase; dir: string } => {
  const dir = mkdtempSync(join(tmpdir(), "applyocalypse-scheduler-"));
  tempDirs.push(dir);
  electronPaths.userData = join(dir, "userData");
  electronPaths.downloads = join(dir, "Downloads");
  electronPaths.temp = join(dir, "Temp");
  const db = openApplyocalypseDatabase(join(dir, "test.sqlite"));
  runMigrations(db, resolve(process.cwd(), "packages/db/migrations"));
  return { db, dir };
};

afterEach(() => {
  vi.restoreAllMocks();
  for (const dir of tempDirs.splice(0)) {
    rmSync(dir, { recursive: true, force: true });
  }
});

describe("local queue scheduler", () => {
  it("marks a claimed run failed instead of throwing when worker start fails", () => {
    const { db } = createDb();
    try {
      const profile = new ProfileRepository(db).createStarterProfile({ legalName: "Hedy Lamarr" });
      const { queueItems } = new JobRepository(db).enqueueTargets({
        profileId: profile.id,
        items: [{ sourceKind: "TEXT", sourceValue: "Required: Python" }]
      });
      const supervisor = {
        start: vi.fn(() => {
          throw new Error("worker spawn failed");
        })
      } as unknown as PythonWorkerSupervisor;

      const scheduler = new LocalQueueScheduler(db, new QueueRepository(db), supervisor, {
        maxConcurrentApplications: 1,
        pollIntervalMs: 1000
      });

      expect(() => scheduler.tick()).not.toThrow();

      const run = new RunRepository(db).listApplicationRuns()[0]!;
      const queueItem = new QueueRepository(db).getById(queueItems[0]!.id);
      const event = new RunRepository(db).listRunEvents(run.id)[0]!;
      const audit = db.prepare("SELECT action, metadata_json FROM audit_logs WHERE entity_id = ?").get(run.id) as {
        action: string;
        metadata_json: string;
      };

      expect(supervisor.start).toHaveBeenCalledTimes(1);
      expect(run.status).toBe("FAILED");
      expect(run.failureCode).toBe("SCHEDULER_PREPARE_FAILED");
      expect(run.failureMessage).toBe("worker spawn failed");
      expect(queueItem.status).toBe("FAILED");
      expect(queueItem.claimedBy).toBeNull();
      expect(event.eventType).toBe("FAILED");
      expect(event.payload.error).toBe("worker spawn failed");
      expect(audit.action).toBe("scheduler.run_prepare_failed");
      expect(audit.metadata_json).toContain(queueItems[0]!.id);
    } finally {
      closeApplyocalypseDatabase(db);
    }
  });

  it("writes cover-letter-sample.txt and passes --cover-letter-sample-file when a COVER_LETTER doc exists", () => {
    const { db } = createDb();
    try {
      const profile = new ProfileRepository(db).createStarterProfile({ legalName: "Margaret Hamilton" });
      const { queueItems } = new JobRepository(db).enqueueTargets({
        profileId: profile.id,
        items: [{ sourceKind: "TEXT", sourceValue: "Requires Python and ML experience" }]
      });

      const tmpDir = mkdtempSync(join(tmpdir(), "cl-sample-"));
      tempDirs.push(tmpDir);
      const clFilePath = join(tmpDir, "cover-letter.txt");
      const sampleCl = "Dear Hiring Manager,\n\nI am excited to apply.";
      writeFileSync(clFilePath, sampleCl, "utf8");

      const upload = new UploadRepository(db).registerLocalFile({
        profileId: profile.id,
        localPath: clFilePath,
        fileKind: "COVER_LETTER"
      });
      new ParsedDocumentRepository(db).create({
        uploadedFileId: upload.id,
        parserName: "test-parser",
        parserVersion: "0.0.1",
        confidence: 0.9,
        canonical: {
          documentKind: "COVER_LETTER",
          sourceFormat: "TXT",
          rawTextPreview: sampleCl,
          identity: { legalName: null, email: null, phone: null, location: null, links: [] },
          sections: [],
          skillGroups: [],
          education: [],
          experience: [],
          projects: [],
          certifications: []
        }
      });

      let capturedInput: StartWorkerInput | undefined;
      const supervisor = {
        start: vi.fn((input: StartWorkerInput) => {
          capturedInput = input;
        })
      } as unknown as PythonWorkerSupervisor;

      const scheduler = new LocalQueueScheduler(db, new QueueRepository(db), supervisor, {
        maxConcurrentApplications: 1,
        pollIntervalMs: 1000
      });
      scheduler.tick();

      expect(supervisor.start).toHaveBeenCalledTimes(1);
      expect(capturedInput?.coverLetterSampleFile).toBeDefined();
      expect(existsSync(capturedInput!.coverLetterSampleFile!)).toBe(true);
      expect(readFileSync(capturedInput!.coverLetterSampleFile!, "utf8")).toBe(sampleCl);
      expect(capturedInput?.runId).toBe(
        db.prepare("SELECT id FROM application_runs WHERE queue_item_id = ?").get(queueItems[0]!.id) as { id: string } | undefined
          ? (db.prepare("SELECT id FROM application_runs WHERE queue_item_id = ?").get(queueItems[0]!.id) as { id: string }).id
          : capturedInput?.runId
      );
    } finally {
      closeApplyocalypseDatabase(db);
    }
  });

  it("omits coverLetterSampleFile when no COVER_LETTER doc exists for the profile", () => {
    const { db } = createDb();
    try {
      const profile = new ProfileRepository(db).createStarterProfile({ legalName: "Katherine Johnson" });
      new JobRepository(db).enqueueTargets({
        profileId: profile.id,
        items: [{ sourceKind: "TEXT", sourceValue: "Requires math skills" }]
      });

      let capturedInput: StartWorkerInput | undefined;
      const supervisor = {
        start: vi.fn((input: StartWorkerInput) => {
          capturedInput = input;
        })
      } as unknown as PythonWorkerSupervisor;

      const scheduler = new LocalQueueScheduler(db, new QueueRepository(db), supervisor, {
        maxConcurrentApplications: 1,
        pollIntervalMs: 1000
      });
      scheduler.tick();

      expect(supervisor.start).toHaveBeenCalledTimes(1);
      expect(capturedInput?.coverLetterSampleFile).toBeUndefined();
    } finally {
      closeApplyocalypseDatabase(db);
    }
  });

  it("uses the persisted concurrency setting when claiming local queue work", () => {
    const { db } = createDb();
    try {
      const profile = new ProfileRepository(db).createStarterProfile({ legalName: "Annie Easley" });
      const { queueItems } = new JobRepository(db).enqueueTargets({
        profileId: profile.id,
        items: [
          { sourceKind: "TEXT", sourceValue: "Required: Python" },
          { sourceKind: "TEXT", sourceValue: "Required: TypeScript" }
        ]
      });
      new SettingsRepository(db).set("automation.maxConcurrentApplications", 1);
      const futureLease = new Date(Date.now() + 600_000).toISOString();
      db.prepare(
        `
        UPDATE queue_items
        SET status = 'RUNNING_AUTOMATION',
            claimed_by = 'worker-a',
            heartbeat_at = @futureLease,
            lease_expires_at = @futureLease
        WHERE id = @queueItemId
      `
      ).run({ futureLease, queueItemId: queueItems[0]!.id });
      const supervisor = {
        start: vi.fn()
      } as unknown as PythonWorkerSupervisor;

      const scheduler = new LocalQueueScheduler(db, new QueueRepository(db), supervisor, {
        maxConcurrentApplications: 2,
        pollIntervalMs: 1000
      });

      scheduler.tick();

      expect(supervisor.start).not.toHaveBeenCalled();
      expect(new QueueRepository(db).getById(queueItems[1]!.id).status).toBe("PENDING");
    } finally {
      closeApplyocalypseDatabase(db);
    }
  });
});
