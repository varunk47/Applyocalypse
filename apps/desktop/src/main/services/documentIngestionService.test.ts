import { existsSync, mkdtempSync, readFileSync, rmSync, unlinkSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, relative } from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";
import { copySourceIntoCustody } from "./documentIngestionService";

vi.mock("electron", () => ({
  app: {
    getPath: () => tmpdir()
  }
}));

const tempDirs: string[] = [];

const createTempDir = (): string => {
  const dir = mkdtempSync(join(tmpdir(), "applyocalypse-source-custody-"));
  tempDirs.push(dir);
  return dir;
};

afterEach(() => {
  for (const dir of tempDirs.splice(0)) {
    rmSync(dir, { recursive: true, force: true });
  }
});

describe("document source custody", () => {
  it("copies picked source material into Applyocalypse-controlled storage", () => {
    const dir = createTempDir();
    const sourcePath = join(dir, "Ada Lovelace Resume.tex");
    const custodyRoot = join(dir, "source-materials");
    writeFileSync(sourcePath, "\\section{Experience}", "utf8");

    const custodyPath = copySourceIntoCustody({
      localPath: sourcePath,
      profileId: "profile-1",
      fileKind: "RESUME",
      rootDir: custodyRoot
    });

    unlinkSync(sourcePath);

    expect(custodyPath).not.toBe(sourcePath);
    expect(relative(custodyRoot, custodyPath).startsWith("..")).toBe(false);
    expect(existsSync(custodyPath)).toBe(true);
    expect(readFileSync(custodyPath, "utf8")).toBe("\\section{Experience}");
  });
});
