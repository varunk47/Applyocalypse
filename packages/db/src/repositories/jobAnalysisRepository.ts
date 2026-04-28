import type { Database } from "better-sqlite3";
import { createHash, randomUUID } from "node:crypto";
import { stringifyJsonColumn } from "../json";

const arrayFromPayload = (payload: Record<string, unknown>, key: string): string[] =>
  Array.isArray(payload[key]) ? (payload[key] as unknown[]).map((item) => String(item)) : [];

export class JobAnalysisRepository {
  constructor(private readonly db: Database) {}

  persistFromWorkerEvent(input: {
    applicationRunId: string;
    rawText: string;
    scrapedUrl?: string | null;
    source: "USER_TEXT" | "SCRAPED" | "IMPORTED";
    analysis: Record<string, unknown>;
    extractedAt: string;
  }): { jobDescriptionId: string; keywordSetId: string } {
    const runRow = this.db
      .prepare("SELECT job_target_id FROM application_runs WHERE id = ?")
      .get(input.applicationRunId) as { job_target_id: string } | undefined;
    if (!runRow) {
      throw new Error(`Application run not found: ${input.applicationRunId}`);
    }

    const jobDescriptionId = randomUUID();
    const keywordSetId = randomUUID();
    const sha256 = createHash("sha256").update(input.rawText).digest("hex");
    const now = new Date().toISOString();

    this.db.transaction(() => {
      this.db
        .prepare(
          `
          INSERT INTO job_descriptions (
            id, job_target_id, raw_text, scraped_url, source, sha256, extracted_at, created_at, updated_at
          )
          VALUES (
            @id, @jobTargetId, @rawText, @scrapedUrl, @source, @sha256, @extractedAt, @now, @now
          )
        `
        )
        .run({
          id: jobDescriptionId,
          jobTargetId: runRow.job_target_id,
          rawText: input.rawText,
          scrapedUrl: input.scrapedUrl ?? null,
          source: input.source,
          sha256,
          extractedAt: input.extractedAt,
          now
        });

      this.db
        .prepare(
          `
          INSERT INTO jd_keyword_sets (
            id, job_description_id, must_have_json, preferred_json, hard_requirements_json,
            tools_json, domain_signals_json, location_signals_json, work_authorization_signals_json,
            seniority_cues_json, communication_cues_json, required_materials_json,
            cover_letter_likely_required, risky_claims_to_avoid_json, evidence_matches_json,
            missing_truthful_json, truly_missing_json, created_at, updated_at
          )
          VALUES (
            @id, @jobDescriptionId, @mustHaveJson, @preferredJson, @hardRequirementsJson,
            @toolsJson, @domainSignalsJson, @locationSignalsJson, @workAuthorizationSignalsJson,
            @seniorityCuesJson, @communicationCuesJson, @requiredMaterialsJson,
            @coverLetterLikelyRequired, @riskyClaimsToAvoidJson, '[]',
            '[]', '[]', @now, @now
          )
        `
        )
        .run({
          id: keywordSetId,
          jobDescriptionId,
          mustHaveJson: stringifyJsonColumn(arrayFromPayload(input.analysis, "must_have_keywords")),
          preferredJson: stringifyJsonColumn(arrayFromPayload(input.analysis, "preferred_keywords")),
          hardRequirementsJson: stringifyJsonColumn(arrayFromPayload(input.analysis, "hard_requirements")),
          toolsJson: stringifyJsonColumn(arrayFromPayload(input.analysis, "tools_and_technologies")),
          domainSignalsJson: stringifyJsonColumn(arrayFromPayload(input.analysis, "domain_signals")),
          locationSignalsJson: stringifyJsonColumn(arrayFromPayload(input.analysis, "location_signals")),
          workAuthorizationSignalsJson: stringifyJsonColumn(arrayFromPayload(input.analysis, "work_authorization_signals")),
          seniorityCuesJson: stringifyJsonColumn(arrayFromPayload(input.analysis, "seniority_cues")),
          communicationCuesJson: stringifyJsonColumn(arrayFromPayload(input.analysis, "communication_cues")),
          requiredMaterialsJson: stringifyJsonColumn(arrayFromPayload(input.analysis, "required_materials")),
          coverLetterLikelyRequired: input.analysis["cover_letter_likely_required"] === true ? 1 : 0,
          riskyClaimsToAvoidJson: stringifyJsonColumn(arrayFromPayload(input.analysis, "risky_claims_to_avoid")),
          now
        });
    })();

    return { jobDescriptionId, keywordSetId };
  }
}
