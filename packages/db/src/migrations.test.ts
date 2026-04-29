import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import { closeApplyocalypseDatabase, openApplyocalypseDatabase, resolveMigrationDir, runMigrations } from "./index";

const tempDirs: string[] = [];

afterEach(() => {
  for (const dir of tempDirs.splice(0)) {
    rmSync(dir, { recursive: true, force: true });
  }
});

describe("migrations", () => {
  it("resolve and run when Electron dev starts from apps/desktop", () => {
    const originalCwd = process.cwd();
    const tempDir = mkdtempSync(join(tmpdir(), "applyocalypse-migrations-"));
    tempDirs.push(tempDir);

    try {
      process.chdir(resolve(originalCwd, "apps/desktop"));
      expect(resolveMigrationDir().replaceAll("\\", "/")).toMatch(/packages\/db\/migrations$/);

      const db = openApplyocalypseDatabase(join(tempDir, "dev.sqlite"));
      try {
        const result = runMigrations(db);
        expect(result.applied).toContain("0001_initial.sql");
      } finally {
        closeApplyocalypseDatabase(db);
      }
    } finally {
      process.chdir(originalCwd);
    }
  });
});
