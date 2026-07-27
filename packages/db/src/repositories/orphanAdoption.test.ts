import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import {
  ParsedDocumentRepository,
  ProfileRepository,
  UploadRepository,
  closeApplyocalypseDatabase,
  openApplyocalypseDatabase,
  runMigrations,
  type ApplyocalypseDatabase
} from "../index";

const tempDirs: string[] = [];
const openDbs: ApplyocalypseDatabase[] = [];

const createDb = (): ApplyocalypseDatabase => {
  const dir = mkdtempSync(join(tmpdir(), "applyocalypse-adoption-"));
  tempDirs.push(dir);
  const db = openApplyocalypseDatabase(join(dir, "test.sqlite"));
  openDbs.push(db);
  runMigrations(db, resolve(process.cwd(), "packages/db/migrations"));
  return db;
};

const writeResume = (): string => {
  const dir = mkdtempSync(join(tmpdir(), "applyocalypse-adoption-file-"));
  tempDirs.push(dir);
  const path = join(dir, "resume.txt");
  writeFileSync(path, "Ada Lovelace\nAnalytical Engine");
  return path;
};

afterEach(() => {
  for (const db of openDbs.splice(0)) {
    closeApplyocalypseDatabase(db);
  }
  for (const dir of tempDirs.splice(0)) {
    rmSync(dir, { recursive: true, force: true });
  }
});

describe("adoptOrphanedFiles", () => {
  it("returns nothing when every upload already has an owner", () => {
    const db = createDb();
    const profiles = new ProfileRepository(db);
    const uploads = new UploadRepository(db);
    const profile = profiles.createStarterProfile({ legalName: "Ada Lovelace" });
    uploads.registerLocalFile({ profileId: profile.id, localPath: writeResume(), fileKind: "RESUME" });

    expect(uploads.adoptOrphanedFiles(profile.id)).toHaveLength(0);
  });

  it("claims an upload registered before any profile existed", () => {
    const db = createDb();
    const profiles = new ProfileRepository(db);
    const uploads = new UploadRepository(db);
    const orphan = uploads.registerLocalFile({ profileId: null, localPath: writeResume(), fileKind: "RESUME" });
    expect(orphan.profileId).toBeNull();

    const profile = profiles.createStarterProfile({ legalName: "Ada Lovelace" });
    const adopted = uploads.adoptOrphanedFiles(profile.id);

    expect(adopted).toHaveLength(1);
    expect(adopted[0]?.id).toBe(orphan.id);
    expect(uploads.getById(orphan.id).profileId).toBe(profile.id);
  });

  it("leaves uploads owned by another profile alone", () => {
    const db = createDb();
    const profiles = new ProfileRepository(db);
    const uploads = new UploadRepository(db);
    const owner = profiles.createStarterProfile({ legalName: "Grace Hopper" });
    const owned = uploads.registerLocalFile({ profileId: owner.id, localPath: writeResume(), fileKind: "RESUME" });
    const orphan = uploads.registerLocalFile({ profileId: null, localPath: writeResume(), fileKind: "RESUME" });

    const claimant = profiles.createStarterProfile({ legalName: "Ada Lovelace" });
    uploads.adoptOrphanedFiles(claimant.id);

    expect(uploads.getById(owned.id).profileId).toBe(owner.id);
    expect(uploads.getById(orphan.id).profileId).toBe(claimant.id);
  });

  /**
   * The reason adoption exists: a parse of an unowned upload merges nothing, so
   * without this the resume-first onboarding would produce an empty profile.
   */
  it("lets a parse taken before the profile existed merge once it is adopted", () => {
    const db = createDb();
    const profiles = new ProfileRepository(db);
    const uploads = new UploadRepository(db);
    const parsedDocuments = new ParsedDocumentRepository(db);
    const orphan = uploads.registerLocalFile({ profileId: null, localPath: writeResume(), fileKind: "RESUME" });

    const beforeAdoption = parsedDocuments.createAndMerge({
      uploadedFileId: orphan.id,
      parserName: "test-parser",
      parserVersion: "1.0.0",
      confidence: 0.95,
      canonical: {
        documentKind: "RESUME",
        sourceFormat: "TXT",
        identity: { legalName: "Ada Lovelace", email: "ada@example.com", phone: null, location: null, links: [] },
        sections: [],
        skillGroups: [],
        education: [],
        experience: [
          {
            company: "Analytical Engine",
            title: "Programmer",
            location: null,
            startDate: null,
            endDate: null,
            bullets: ["Wrote the first algorithm"],
            tools: [],
            confidence: 0.95
          }
        ],
        projects: [],
        certifications: [],
        rawTextPreview: "Ada Lovelace\nAnalytical Engine"
      }
    });
    expect(beforeAdoption.updatedProfile).toBeNull();

    const profile = profiles.createStarterProfile({ legalName: "Ada Lovelace" });
    uploads.adoptOrphanedFiles(profile.id);
    const afterAdoption = parsedDocuments.mergeIntoProfile(beforeAdoption.parsedDocument);

    expect(afterAdoption.updatedProfile).not.toBeNull();
    expect(profiles.getCanonicalProfile(profile.id)?.experience).toHaveLength(1);
  });
});
