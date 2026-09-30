import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import {
  JobFilterRepository,
  ProfileAddressRepository,
  ProfileRepository,
  closeApplyocalypseDatabase,
  openApplyocalypseDatabase,
  runMigrations,
  type ApplyocalypseDatabase
} from "../index";

const tempDirs: string[] = [];

const withDb = (run: (db: ApplyocalypseDatabase, profileId: string, otherProfileId: string) => void): void => {
  const dir = mkdtempSync(join(tmpdir(), "applyocalypse-db-"));
  tempDirs.push(dir);
  const db = openApplyocalypseDatabase(join(dir, "test.sqlite"));
  try {
    runMigrations(db, resolve(process.cwd(), "packages/db/migrations"));
    const profiles = new ProfileRepository(db);
    run(db, profiles.createStarterProfile({ legalName: "Grace Hopper" }).id, profiles.createStarterProfile({ legalName: "Alan Turing" }).id);
  } finally {
    closeApplyocalypseDatabase(db);
  }
};

afterEach(() => {
  for (const dir of tempDirs.splice(0)) {
    rmSync(dir, { recursive: true, force: true });
  }
});

describe("JobFilterRepository", () => {
  it("stores filters per profile and hands the worker only the enabled ones", () => {
    withDb((db, profileId) => {
      const filters = new JobFilterRepository(db);
      filters.upsert({ profileId, kind: "skip_company", value: "  Initech " });
      const salary = filters.upsert({ profileId, kind: "min_salary", value: "120000" });
      filters.upsert({ id: salary.id, profileId, kind: "min_salary", value: "130000", enabled: false });

      expect(filters.listByProfile(profileId).map((f) => [f.kind, f.value, f.enabled])).toEqual([
        ["skip_company", "Initech", true],
        ["min_salary", "130000", false]
      ]);
      expect(filters.workerFilters(profileId)).toEqual([{ kind: "skip_company", value: "Initech" }]);
    });
  });

  it("refuses a blank value, an unknown arrangement and a salary that is not a number", () => {
    withDb((db, profileId) => {
      const filters = new JobFilterRepository(db);
      expect(() => filters.upsert({ profileId, kind: "skip_keyword", value: " " })).toThrow();
      expect(() => filters.upsert({ profileId, kind: "work_arrangement", value: "sometimes" })).toThrow();
      expect(() => filters.upsert({ profileId, kind: "min_salary", value: "lots" })).toThrow();
      expect(filters.upsert({ profileId, kind: "work_arrangement", value: "Remote" }).value).toBe("remote");
      expect(filters.upsert({ profileId, kind: "min_salary", value: "$95,000" }).value).toBe("95000");
    });
  });

  it("will not let one profile overwrite another profile's filter", () => {
    withDb((db, profileId, otherProfileId) => {
      const filters = new JobFilterRepository(db);
      const mine = filters.upsert({ profileId, kind: "place", value: "Atlanta" });
      expect(() => filters.upsert({ id: mine.id, profileId: otherProfileId, kind: "place", value: "Boston" })).toThrow();
      expect(filters.listByProfile(profileId)[0]?.value).toBe("Atlanta");
      expect(filters.delete(mine.id)).toBe(true);
      expect(filters.listByProfile(profileId)).toEqual([]);
    });
  });
});

describe("ProfileAddressRepository", () => {
  it("stores several addresses and gives the worker the profile's address shape", () => {
    withDb((db, profileId) => {
      const addresses = new ProfileAddressRepository(db);
      addresses.upsert({ profileId, label: "Home", addressLine1: "10 Peachtree St", city: "Atlanta", state: "GA", postalCode: "30303", country: "United States" });
      addresses.upsert({ profileId, label: "Family", city: "Boston", state: "MA" });

      expect(addresses.listByProfile(profileId).map((a) => a.city)).toEqual(["Atlanta", "Boston"]);
      expect(addresses.workerAddresses(profileId)[0]).toEqual({
        label: "Home",
        addressLine1: "10 Peachtree St",
        addressLine2: "",
        city: "Atlanta",
        state: "GA",
        postalCode: "30303",
        country: "United States"
      });
    });
  });

  it("needs a city and stays inside its profile", () => {
    withDb((db, profileId, otherProfileId) => {
      const addresses = new ProfileAddressRepository(db);
      expect(() => addresses.upsert({ profileId, city: "  " })).toThrow();
      const home = addresses.upsert({ profileId, city: "Atlanta" });
      expect(() => addresses.upsert({ id: home.id, profileId: otherProfileId, city: "Boston" })).toThrow();
      expect(addresses.delete(home.id)).toBe(true);
    });
  });
});
