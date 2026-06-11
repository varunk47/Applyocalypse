import { existsSync, mkdtempSync, readFileSync, rmSync, unlinkSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, relative, resolve } from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  ProfileRepository,
  UploadRepository,
  ParsedDocumentRepository,
  closeApplyocalypseDatabase,
  openApplyocalypseDatabase,
  runMigrations,
  type ApplyocalypseDatabase
} from "@applyocalypse/db";
import { copySourceIntoCustody, getLatestCoverLetterText } from "./documentIngestionService";

vi.mock("electron", () => ({
  app: {
    getPath: () => tmpdir()
  }
}));

const tempDirs: string[] = [];
const openDbs: ApplyocalypseDatabase[] = [];

const createDb = (): ApplyocalypseDatabase => {
  const dir = mkdtempSync(join(tmpdir(), "applyocalypse-ingestion-"));
  tempDirs.push(dir);
  const db = openApplyocalypseDatabase(join(dir, "test.sqlite"));
  openDbs.push(db);
  runMigrations(db, resolve(process.cwd(), "packages/db/migrations"));
  return db;
};

const createTempDir = (): string => {
  const dir = mkdtempSync(join(tmpdir(), "applyocalypse-source-custody-"));
  tempDirs.push(dir);
  return dir;
};

afterEach(() => {
  for (const db of openDbs.splice(0)) {
    closeApplyocalypseDatabase(db);
  }
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

describe("getLatestCoverLetterText", () => {
  const insertCoverLetterDoc = (db: ApplyocalypseDatabase, profileId: string, text: string): void => {
    const dir = createTempDir();
    const filePath = join(dir, "cover-letter.txt");
    writeFileSync(filePath, text, "utf8");
    const upload = new UploadRepository(db).registerLocalFile({
      profileId,
      localPath: filePath,
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
        rawTextPreview: text,
        identity: { legalName: null, email: null, phone: null, location: null, links: [] },
        sections: [],
        skillGroups: [],
        education: [],
        experience: [],
        projects: [],
        certifications: []
      }
    });
  };

  it("returns null when the profile has no COVER_LETTER uploads", () => {
    const db = createDb();
    const profile = new ProfileRepository(db).createStarterProfile({ legalName: "Test User" });
    expect(getLatestCoverLetterText(db, profile.id)).toBeNull();
  });

  it("returns rawTextPreview from the latest COVER_LETTER parsed document", () => {
    const db = createDb();
    const profile = new ProfileRepository(db).createStarterProfile({ legalName: "Grace Hopper" });
    const sampleText = "Dear Hiring Manager,\n\nI am excited to apply for the Software Engineer position.";
    insertCoverLetterDoc(db, profile.id, sampleText);
    expect(getLatestCoverLetterText(db, profile.id)).toBe(sampleText);
  });

  it("returns the most recently created COVER_LETTER when multiple exist", () => {
    const db = createDb();
    const profile = new ProfileRepository(db).createStarterProfile({ legalName: "Ada Lovelace" });
    insertCoverLetterDoc(db, profile.id, "older cover letter text");
    insertCoverLetterDoc(db, profile.id, "newer cover letter text");
    expect(getLatestCoverLetterText(db, profile.id)).toBe("newer cover letter text");
  });

  it("returns null when rawTextPreview is empty", () => {
    const db = createDb();
    const profile = new ProfileRepository(db).createStarterProfile({ legalName: "Test User 2" });
    insertCoverLetterDoc(db, profile.id, "");
    expect(getLatestCoverLetterText(db, profile.id)).toBeNull();
  });

  it("does not return RESUME documents for the profile", () => {
    const db = createDb();
    const profile = new ProfileRepository(db).createStarterProfile({ legalName: "Marie Curie" });
    const dir = createTempDir();
    const filePath = join(dir, "resume.txt");
    writeFileSync(filePath, "resume content", "utf8");
    const upload = new UploadRepository(db).registerLocalFile({
      profileId: profile.id,
      localPath: filePath,
      fileKind: "RESUME"
    });
    new ParsedDocumentRepository(db).create({
      uploadedFileId: upload.id,
      parserName: "test-parser",
      parserVersion: "0.0.1",
      confidence: 0.9,
      canonical: {
        documentKind: "RESUME",
        sourceFormat: "TXT",
        rawTextPreview: "resume preview",
        identity: { legalName: null, email: null, phone: null, location: null, links: [] },
        sections: [],
        skillGroups: [],
        education: [],
        experience: [],
        projects: [],
        certifications: []
      }
    });
    expect(getLatestCoverLetterText(db, profile.id)).toBeNull();
  });
});
