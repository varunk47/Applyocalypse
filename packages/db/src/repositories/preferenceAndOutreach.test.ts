import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import {
  OutreachRepository,
  PreferenceRuleRepository,
  ProfileRepository,
  closeApplyocalypseDatabase,
  openApplyocalypseDatabase,
  runMigrations,
  type ApplyocalypseDatabase
} from "../index";

const tempDirs: string[] = [];

const withDb = (run: (db: ApplyocalypseDatabase, profileId: string) => void): void => {
  const dir = mkdtempSync(join(tmpdir(), "applyocalypse-db-"));
  tempDirs.push(dir);
  const db = openApplyocalypseDatabase(join(dir, "test.sqlite"));
  try {
    runMigrations(db, resolve(process.cwd(), "packages/db/migrations"));
    run(db, new ProfileRepository(db).createStarterProfile({ legalName: "Grace Hopper" }).id);
  } finally {
    closeApplyocalypseDatabase(db);
  }
};

afterEach(() => {
  for (const dir of tempDirs.splice(0)) {
    rmSync(dir, { recursive: true, force: true });
  }
});

describe("PreferenceRuleRepository", () => {
  it("saves, edits and deletes a profile's rules", () => {
    withDb((db, profileId) => {
      const rules = new PreferenceRuleRepository(db);
      const rule = rules.upsert({ profileId, question: "address line 1", answer: "10 Peachtree St", conditions: { location: "GA" } });
      rules.upsert({ profileId, question: "address line 1", answer: "1 Default St" });

      const edited = rules.upsert({ ...rule, answer: "12 Peachtree St", enabled: false });

      expect(edited.id).toBe(rule.id);
      expect(rules.listByProfile(profileId).map((item) => [item.answer, item.conditions, item.enabled])).toEqual([
        ["12 Peachtree St", { location: "GA" }, false],
        ["1 Default St", {}, true]
      ]);
      expect(rules.delete(rule.id)).toBe(true);
      expect(rules.listByProfile(profileId)).toHaveLength(1);
    });
  });

  it("hands the worker only enabled rules, in the shape it reads", () => {
    withDb((db, profileId) => {
      const rules = new PreferenceRuleRepository(db);
      rules.upsert({ profileId, question: "salary", answer: "150000", enabled: false });
      rules.upsert({ profileId, question: "address line 1", answer: "10 Peachtree St", conditions: { location: "GA" } });

      expect(rules.workerRules(profileId)).toEqual([
        { question: "address line 1", answer: "10 Peachtree St", conditions: { location: "GA" } }
      ]);
    });
  });

  it("refuses a rule with a blank question or answer", () => {
    withDb((db, profileId) => {
      const rules = new PreferenceRuleRepository(db);
      expect(() => rules.upsert({ profileId, question: "  ", answer: "x" })).toThrow();
      expect(() => rules.upsert({ profileId, question: "salary", answer: "" })).toThrow();
    });
  });
});

describe("OutreachRepository", () => {
  const draftFor = (outreach: OutreachRepository, profileId: string, body = "Hello") => {
    const contact = outreach.createContact({ profileId, name: "Ada Lovelace", email: "ada@example.com", company: "Acme" });
    return outreach.createDraft({ contactId: contact.id, channel: "EMAIL", subject: "Hi", body });
  };

  it("only records a send for a message the user approved", () => {
    withDb((db, profileId) => {
      const outreach = new OutreachRepository(db);
      const draft = draftFor(outreach, profileId);

      expect(outreach.recordSend(draft.id)).toEqual({ ok: false, reason: "NOT_APPROVED" });

      outreach.approve(draft.id);
      const result = outreach.recordSend(draft.id);

      expect(result.ok).toBe(true);
      expect(outreach.getMessage(draft.id)?.status).toBe("SENT");
      expect(outreach.recordSend(draft.id)).toEqual({ ok: false, reason: "NOT_APPROVED" });
    });
  });

  it("stops sends once the daily cap is reached, counting a rolling 24 hours", () => {
    withDb((db, profileId) => {
      const outreach = new OutreachRepository(db);
      const start = new Date("2026-09-24T09:00:00.000Z");
      const [first, second, third] = [0, 1, 2].map((index) => outreach.approve(draftFor(outreach, profileId, `Hello ${index}`).id).id) as [
        string,
        string,
        string
      ];

      expect(outreach.recordSend(first, { dailyCap: 2, now: start }).ok).toBe(true);
      expect(outreach.recordSend(second, { dailyCap: 2, now: new Date("2026-09-24T20:00:00.000Z") }).ok).toBe(true);
      expect(outreach.recordSend(third, { dailyCap: 2, now: new Date("2026-09-25T08:59:00.000Z") })).toEqual({
        ok: false,
        reason: "DAILY_CAP_REACHED"
      });
      expect(outreach.sentInLast24Hours(new Date("2026-09-25T09:00:01.000Z"))).toBe(1);
      expect(outreach.recordSend(third, { dailyCap: 2, now: new Date("2026-09-25T09:00:01.000Z") }).ok).toBe(true);
    });
  });

  it("editing an approved message sends it back to draft", () => {
    withDb((db, profileId) => {
      const outreach = new OutreachRepository(db);
      const message = outreach.approve(draftFor(outreach, profileId).id);

      const edited = outreach.updateDraft(message.id, { body: "Hello again" });

      expect(edited.status).toBe("DRAFT");
      expect(edited.approvedAt).toBeNull();
    });
  });

  it("records a failed send without counting it against the cap", () => {
    withDb((db, profileId) => {
      const outreach = new OutreachRepository(db);
      const message = outreach.approve(draftFor(outreach, profileId).id);

      outreach.recordFailure(message.id, "Gmail send scope not granted");

      expect(outreach.getMessage(message.id)).toMatchObject({ status: "FAILED", failureReason: "Gmail send scope not granted" });
      expect(outreach.sentInLast24Hours()).toBe(0);
    });
  });
});
