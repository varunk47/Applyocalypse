import { describe, expect, it } from "vitest";

import { buildCoverLetterRequirementSummary } from "./materialRequirementsView";

describe("buildCoverLetterRequirementSummary", () => {
  it("starts pending when no requirement events exist", () => {
    const summary = buildCoverLetterRequirementSummary([]);

    expect(summary.status).toBe("PENDING");
    expect(summary.required).toBe(false);
  });

  it("reports JD-required cover letters", () => {
    const summary = buildCoverLetterRequirementSummary([
      {
        eventType: "COVER_LETTER_REQUIRED",
        severity: "INFO",
        message: "Cover letter appears required by the job description",
        timestamp: "2026-04-27T10:00:00.000Z",
        payload: { required: true, source: "JD_ANALYSIS" }
      }
    ]);

    expect(summary.status).toBe("REQUIRED");
    expect(summary.source).toBe("JD_ANALYSIS");
  });

  it("escalates required form fields with missing artifacts", () => {
    const summary = buildCoverLetterRequirementSummary([
      {
        eventType: "COVER_LETTER_REQUIRED",
        severity: "WARN",
        message: "Application form requires a cover letter",
        timestamp: "2026-04-27T10:00:00.000Z",
        payload: { required: true, source: "APPLICATION_FORM", field_count: 1 }
      },
      {
        eventType: "PAUSED",
        severity: "WARN",
        message: "Browser automation paused because required upload artifacts are missing",
        timestamp: "2026-04-27T10:01:00.000Z",
        payload: { missing_documents: [{ file_kind: "COVER_LETTER", required: true }] }
      }
    ]);

    expect(summary.status).toBe("MISSING_REQUIRED");
    expect(summary.source).toBe("APPLICATION_FORM");
    expect(summary.fieldCount).toBe(1);
    expect(summary.missingRequiredDocuments).toBe(1);
  });
});
