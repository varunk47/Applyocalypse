import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import {
  ProfileRepository,
  closeApplyocalypseDatabase,
  openApplyocalypseDatabase,
  runMigrations,
  type ApplyocalypseDatabase
} from "@applyocalypse/db";
import { resolveOwningProfileId } from "./profileOwnership";

const tempDirs: string[] = [];
const openDbs: ApplyocalypseDatabase[] = [];

const createDb = (): ApplyocalypseDatabase => {
  const dir = mkdtempSync(join(tmpdir(), "applyocalypse-ownership-"));
  tempDirs.push(dir);
  const db = openApplyocalypseDatabase(join(dir, "test.sqlite"));
  openDbs.push(db);
  runMigrations(db, resolve(process.cwd(), "packages/db/migrations"));
  return db;
};

afterEach(() => {
  for (const db of openDbs.splice(0)) {
    closeApplyocalypseDatabase(db);
  }
  for (const dir of tempDirs.splice(0)) {
    rmSync(dir, { recursive: true, force: true });
  }
});

describe("resolveOwningProfileId", () => {
  it("keeps the requested profile when it exists", () => {
    const profiles = new ProfileRepository(createDb());
    const profile = profiles.createStarterProfile({ legalName: "Ada Lovelace" });

    expect(resolveOwningProfileId(profile.id, profiles)).toBe(profile.id);
  });

  it("falls back to the default profile when the renderer sends null", () => {
    const profiles = new ProfileRepository(createDb());
    const profile = profiles.createStarterProfile({ legalName: "Grace Hopper" });

    expect(resolveOwningProfileId(null, profiles)).toBe(profile.id);
  });

  it("falls back to the default profile when the requested profile no longer exists", () => {
    const profiles = new ProfileRepository(createDb());
    const profile = profiles.createStarterProfile({ legalName: "Katherine Johnson" });

    expect(resolveOwningProfileId("00000000-0000-4000-8000-000000000000", profiles)).toBe(profile.id);
  });

  it("returns null when no profile exists at all", () => {
    const profiles = new ProfileRepository(createDb());

    expect(resolveOwningProfileId(null, profiles)).toBeNull();
  });
});
