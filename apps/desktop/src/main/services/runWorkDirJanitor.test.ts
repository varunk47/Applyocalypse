import { existsSync, mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import { sweepStaleRunWorkDirs } from "./runWorkDirJanitor";

const tempDirs: string[] = [];

const createRunsRoot = (): string => {
  const dir = mkdtempSync(join(tmpdir(), "applyocalypse-janitor-"));
  tempDirs.push(dir);
  return dir;
};

afterEach(() => {
  for (const dir of tempDirs.splice(0)) {
    rmSync(dir, { recursive: true, force: true });
  }
});

describe("sweepStaleRunWorkDirs", () => {
  it("deletes run dirs older than retention", () => {
    const runsRoot = createRunsRoot();
    const runDir = join(runsRoot, "old-run");
    mkdirSync(runDir);
    writeFileSync(join(runDir, "file.txt"), "data", "utf8");

    const eightDaysMs = 8 * 24 * 60 * 60 * 1000;
    const removed = sweepStaleRunWorkDirs(runsRoot, { now: Date.now() + eightDaysMs });

    expect(removed).toEqual(["old-run"]);
    expect(existsSync(runDir)).toBe(false);
  });

  it("keeps run dirs newer than retention", () => {
    const runsRoot = createRunsRoot();
    const runDir = join(runsRoot, "new-run");
    mkdirSync(runDir);
    writeFileSync(join(runDir, "file.txt"), "data", "utf8");

    const oneDayMs = 1 * 24 * 60 * 60 * 1000;
    const removed = sweepStaleRunWorkDirs(runsRoot, { now: Date.now() + oneDayMs });

    expect(removed).toEqual([]);
    expect(existsSync(runDir)).toBe(true);
  });

  it("skips active run ids", () => {
    const runsRoot = createRunsRoot();
    const runDir = join(runsRoot, "old-run");
    mkdirSync(runDir);
    writeFileSync(join(runDir, "file.txt"), "data", "utf8");

    const eightDaysMs = 8 * 24 * 60 * 60 * 1000;
    const removed = sweepStaleRunWorkDirs(runsRoot, {
      now: Date.now() + eightDaysMs,
      activeRunIds: new Set(["old-run"])
    });

    expect(removed).toEqual([]);
    expect(existsSync(runDir)).toBe(true);
  });

  it("returns empty when runs root missing", () => {
    const nonexistentPath = join(tmpdir(), "applyocalypse-janitor-does-not-exist-" + Date.now());
    const removed = sweepStaleRunWorkDirs(nonexistentPath);
    expect(removed).toEqual([]);
  });
});
