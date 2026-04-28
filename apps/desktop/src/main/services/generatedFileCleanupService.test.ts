import { existsSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import {
  JobRepository,
  ProfileRepository,
  RunRepository,
  closeApplyocalypseDatabase,
  openApplyocalypseDatabase,
  runMigrations,
  type ApplyocalypseDatabase
} from "@applyocalypse/db";
import { GeneratedFileCleanupService } from "./generatedFileCleanupService";

const tempDirs: string[] = [];

const createRun = (): { db: ApplyocalypseDatabase; runId: string; dir: string } => {
  const dir = mkdtempSync(join(tmpdir(), "applyocalypse-cleanup-"));
  tempDirs.push(dir);
  const db = openApplyocalypseDatabase(join(dir, "test.sqlite"));
  runMigrations(db, resolve(process.cwd(), "packages/db/migrations"));
  const profile = new ProfileRepository(db).createStarterProfile({ legalName: "Mary Jackson" });
  const { queueItems, jobTargets } = new JobRepository(db).enqueueTargets({
    profileId: profile.id,
    items: [{ sourceKind: "TEXT", sourceValue: "Required: Python" }]
  });
  const run = new RunRepository(db).createApplicationRun({
    queueItemId: queueItems[0]!.id,
    profileId: profile.id,
    jobTargetId: jobTargets[0]!.id
  });
  return { db, runId: run.id, dir };
};

afterEach(() => {
  for (const dir of tempDirs.splice(0)) {
    rmSync(dir, { recursive: true, force: true });
  }
});

describe("generated file cleanup", () => {
  it("deletes expired files only inside configured safe roots", () => {
    const { db, runId, dir } = createRun();
    try {
      const run = new RunRepository(db).getApplicationRun(runId);
      const artifactPath = join(dir, "expired-resume.md");
      writeFileSync(artifactPath, "resume", "utf8");
      new RunRepository(db).addGeneratedFile({
        tailoringRunId: null,
        profileId: run.profileId,
        jobTargetId: run.jobTargetId,
        fileKind: "RESUME",
        format: "MD",
        filename: "expired-resume.md",
        localPath: artifactPath,
        sha256: null,
        sizeBytes: 6,
        uploadStatus: "NOT_UPLOADED",
        uploadedAt: null,
        retentionPolicy: "DELETE_AFTER_RETENTION",
        deleteAfter: "2026-01-01T00:00:00.000Z",
        deletedAt: null
      });

      const result = new GeneratedFileCleanupService(db, [dir]).cleanupExpired("2026-01-02T00:00:00.000Z");
      const row = db.prepare("SELECT deleted_at FROM generated_files WHERE local_path = ?").get(artifactPath) as { deleted_at: string | null };

      expect(result.deleted).toBe(1);
      expect(existsSync(artifactPath)).toBe(false);
      expect(row.deleted_at).not.toBeNull();
    } finally {
      closeApplyocalypseDatabase(db);
    }
  });
});
