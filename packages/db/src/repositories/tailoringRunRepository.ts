import type { Database } from "better-sqlite3";
import { randomUUID } from "node:crypto";
import { stringifyJsonColumn } from "../json";

export class TailoringRunRepository {
  constructor(private readonly db: Database) {}

  createFromPlan(input: {
    applicationRunId: string;
    resumePlan: Record<string, unknown>;
    coverLetterPlan?: Record<string, unknown>;
    validationSummary?: Record<string, unknown>;
    status?: "PREPARING" | "ANALYZING" | "TAILORING_RESUME" | "GENERATING_COVER_LETTER" | "READY_FOR_REVIEW" | "COMPLETED" | "FAILED" | "CANCELLED";
  }): string {
    const runRow = this.db.prepare("SELECT profile_id, job_target_id FROM application_runs WHERE id = ?").get(input.applicationRunId) as
      | { profile_id: string; job_target_id: string }
      | undefined;
    if (!runRow) {
      throw new Error(`Application run not found: ${input.applicationRunId}`);
    }

    const id = randomUUID();
    const now = new Date().toISOString();

    this.db.transaction(() => {
      this.db
        .prepare(
          `
          INSERT INTO tailoring_runs (
            id, profile_id, job_target_id, status, one_page_plan_json,
            resume_plan_json, cover_letter_plan_json, validation_summary_json,
            created_at, updated_at
          )
          VALUES (
            @id, @profileId, @jobTargetId, @status, @onePagePlanJson,
            @resumePlanJson, @coverLetterPlanJson, @validationSummaryJson,
            @now, @now
          )
        `
        )
        .run({
          id,
          profileId: runRow.profile_id,
          jobTargetId: runRow.job_target_id,
          status: input.status ?? "READY_FOR_REVIEW",
          onePagePlanJson: stringifyJsonColumn(input.resumePlan["one_page_plan"] ?? {}),
          resumePlanJson: stringifyJsonColumn(input.resumePlan),
          coverLetterPlanJson: stringifyJsonColumn(input.coverLetterPlan ?? {}),
          validationSummaryJson: stringifyJsonColumn(input.validationSummary ?? {}),
          now
        });

      this.db
        .prepare("UPDATE application_runs SET tailoring_run_id = @tailoringRunId, updated_at = @now WHERE id = @applicationRunId")
        .run({ tailoringRunId: id, applicationRunId: input.applicationRunId, now });
    })();

    return id;
  }
}
