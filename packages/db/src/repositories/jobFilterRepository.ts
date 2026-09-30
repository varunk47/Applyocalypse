import { randomUUID } from "node:crypto";
import type { Database } from "better-sqlite3";

export const JOB_FILTER_KINDS = ["skip_company", "skip_keyword", "min_salary", "work_arrangement", "place"] as const;
export type JobFilterKind = (typeof JOB_FILTER_KINDS)[number];

export const WORK_ARRANGEMENTS = ["remote", "hybrid", "onsite"] as const;

export interface JobFilter {
  id: string;
  profileId: string;
  kind: JobFilterKind;
  value: string;
  enabled: boolean;
  createdAt: string;
  updatedAt: string;
}

/** The shape the Python worker reads from canonical-profile.json. */
export interface WorkerJobFilter {
  kind: JobFilterKind;
  value: string;
}

type JobFilterRow = {
  id: string;
  profile_id: string;
  kind: JobFilterKind;
  value: string;
  enabled: number;
  created_at: string;
  updated_at: string;
};

const parseRow = (row: JobFilterRow): JobFilter => ({
  id: row.id,
  profileId: row.profile_id,
  kind: row.kind,
  value: row.value,
  enabled: row.enabled === 1,
  createdAt: row.created_at,
  updatedAt: row.updated_at
});

/** Stores salaries as plain digits and arrangements in lower case so the worker compares like with like. */
const normalizeValue = (kind: JobFilterKind, raw: string): string => {
  const value = raw.trim();
  if (!value) {
    throw new Error("A job filter needs a value.");
  }
  if (kind === "min_salary") {
    const digits = value.replace(/[$,\s]/g, "");
    if (!/^\d+$/.test(digits)) {
      throw new Error("A minimum salary must be a number.");
    }
    return digits;
  }
  if (kind === "work_arrangement") {
    const arrangement = value.toLowerCase().replace(/[-\s]/g, "");
    if (!(WORK_ARRANGEMENTS as readonly string[]).includes(arrangement)) {
      throw new Error("A work arrangement must be remote, hybrid or onsite.");
    }
    return arrangement;
  }
  return value;
};

export class JobFilterRepository {
  constructor(private readonly db: Database) {}

  listByProfile(profileId: string): JobFilter[] {
    const rows = this.db
      .prepare("SELECT * FROM job_filters WHERE profile_id = ? ORDER BY created_at ASC, rowid ASC")
      .all(profileId) as JobFilterRow[];
    return rows.map(parseRow);
  }

  workerFilters(profileId: string): WorkerJobFilter[] {
    return this.listByProfile(profileId)
      .filter((filter) => filter.enabled)
      .map(({ kind, value }) => ({ kind, value }));
  }

  upsert(input: {
    id?: string | undefined;
    profileId: string;
    kind: JobFilterKind;
    value: string;
    enabled?: boolean | undefined;
  }): JobFilter {
    const value = normalizeValue(input.kind, input.value);
    const id = input.id ?? randomUUID();
    const now = new Date().toISOString();
    this.db
      .prepare(
        `INSERT INTO job_filters (id, profile_id, kind, value, enabled, created_at, updated_at)
         VALUES (@id, @profileId, @kind, @value, @enabled, @now, @now)
         ON CONFLICT(id) DO UPDATE SET
           kind = excluded.kind,
           value = excluded.value,
           enabled = excluded.enabled,
           updated_at = excluded.updated_at
         WHERE job_filters.profile_id = excluded.profile_id`
      )
      .run({ id, profileId: input.profileId, kind: input.kind, value, enabled: input.enabled === false ? 0 : 1, now });
    const row = this.db.prepare("SELECT * FROM job_filters WHERE id = ? AND profile_id = ?").get(id, input.profileId) as
      | JobFilterRow
      | undefined;
    if (!row) {
      throw new Error("Job filter belongs to another profile.");
    }
    return parseRow(row);
  }

  delete(id: string): boolean {
    return this.db.prepare("DELETE FROM job_filters WHERE id = ?").run(id).changes > 0;
  }
}
