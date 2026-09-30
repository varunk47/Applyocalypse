import { randomUUID } from "node:crypto";
import type { Database } from "better-sqlite3";
import { parseJsonColumn, stringifyJsonColumn } from "../json";

/** Job facts a rule can be limited to; the worker matches each as whole words. */
export type PreferenceRuleConditions = { [key in "location" | "company" | "portal"]?: string | undefined };

export interface PreferenceRule {
  id: string;
  profileId: string;
  question: string;
  answer: string;
  conditions: PreferenceRuleConditions;
  enabled: boolean;
  createdAt: string;
  updatedAt: string;
}

/** The shape the Python worker reads from canonical-profile.json. */
export interface WorkerPreferenceRule {
  question: string;
  answer: string;
  conditions: PreferenceRuleConditions;
}

type PreferenceRuleRow = {
  id: string;
  profile_id: string;
  question: string;
  answer: string;
  conditions_json: string;
  enabled: number;
  created_at: string;
  updated_at: string;
};

const parseRow = (row: PreferenceRuleRow): PreferenceRule => ({
  id: row.id,
  profileId: row.profile_id,
  question: row.question,
  answer: row.answer,
  conditions: parseJsonColumn<PreferenceRuleConditions>(row.conditions_json, {}),
  enabled: row.enabled === 1,
  createdAt: row.created_at,
  updatedAt: row.updated_at
});

export class PreferenceRuleRepository {
  constructor(private readonly db: Database) {}

  listByProfile(profileId: string): PreferenceRule[] {
    const rows = this.db
      .prepare("SELECT * FROM preference_rules WHERE profile_id = ? ORDER BY created_at ASC, rowid ASC")
      .all(profileId) as PreferenceRuleRow[];
    return rows.map(parseRow);
  }

  workerRules(profileId: string): WorkerPreferenceRule[] {
    return this.listByProfile(profileId)
      .filter((rule) => rule.enabled)
      .map(({ question, answer, conditions }) => ({ question, answer, conditions }));
  }

  upsert(input: {
    id?: string | undefined;
    profileId: string;
    question: string;
    answer: string;
    conditions?: PreferenceRuleConditions | undefined;
    enabled?: boolean | undefined;
  }): PreferenceRule {
    const question = input.question.trim();
    const answer = input.answer.trim();
    if (!question || !answer) {
      throw new Error("A preference rule needs both a question and an answer.");
    }
    const id = input.id ?? randomUUID();
    const now = new Date().toISOString();
    this.db
      .prepare(
        `INSERT INTO preference_rules (id, profile_id, question, answer, conditions_json, enabled, created_at, updated_at)
         VALUES (@id, @profileId, @question, @answer, @conditionsJson, @enabled, @now, @now)
         ON CONFLICT(id) DO UPDATE SET
           question = excluded.question,
           answer = excluded.answer,
           conditions_json = excluded.conditions_json,
           enabled = excluded.enabled,
           updated_at = excluded.updated_at
         WHERE preference_rules.profile_id = excluded.profile_id`
      )
      .run({
        id,
        profileId: input.profileId,
        question,
        answer,
        conditionsJson: stringifyJsonColumn(input.conditions ?? {}),
        enabled: input.enabled === false ? 0 : 1,
        now
      });
    const row = this.db.prepare("SELECT * FROM preference_rules WHERE id = ? AND profile_id = ?").get(id, input.profileId) as
      | PreferenceRuleRow
      | undefined;
    if (!row) {
      throw new Error("Preference rule belongs to another profile.");
    }
    return parseRow(row);
  }

  delete(id: string): boolean {
    return this.db.prepare("DELETE FROM preference_rules WHERE id = ?").run(id).changes > 0;
  }
}
