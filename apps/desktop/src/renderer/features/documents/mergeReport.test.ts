import { describe, expect, it } from "vitest";
import { buildMergeReport, reasonText, type MergeSummaryInput } from "./mergeReport";

const summary = (overrides: Partial<MergeSummaryInput> = {}): MergeSummaryInput => ({
  sourceName: "grace-hopper-resume.docx",
  applied: [],
  skipped: [],
  warnings: [],
  ...overrides
});

describe("merge report", () => {
  it("names the roles the merge dropped for low confidence", () => {
    const report = buildMergeReport(
      summary({
        applied: ["profile.email", "education:MIT"],
        skipped: ["experience:Acme:Senior Engineer:low_confidence"]
      })
    );

    expect(report.lostWork).toBe(true);
    expect(report.importedCount).toBe(2);
    expect(report.notImported).toEqual([
      { kind: "Role", label: "Senior Engineer at Acme", reason: "low_confidence" }
    ]);
    expect(report.headline).toBe(
      "1 entry from grace-hopper-resume.docx did not make it onto your profile."
    );
  });

  it("keeps a job title that contains a colon intact", () => {
    const report = buildMergeReport(
      summary({ skipped: ["experience:Acme:Engineer II: Platform:low_confidence"] })
    );

    expect(report.notImported[0]?.label).toBe("Engineer II: Platform at Acme");
  });

  it("files duplicates apart from losses, because nothing was lost", () => {
    const report = buildMergeReport(
      summary({
        applied: ["profile.phone"],
        skipped: ["education:MIT:duplicate", "skill_group:Languages:duplicate"]
      })
    );

    expect(report.lostWork).toBe(false);
    expect(report.notImported).toEqual([]);
    expect(report.alreadyOnFile.map((entry) => entry.label)).toEqual(["MIT", "Languages"]);
    expect(report.headline).toBe(
      "1 detail from grace-hopper-resume.docx landed on your profile. Nothing was dropped."
    );
  });

  it("labels every section the merge can skip", () => {
    const report = buildMergeReport(
      summary({
        skipped: [
          "education:MIT:low_confidence",
          "project:Cobol Compiler:low_confidence",
          "certification:PMP:low_confidence",
          "skill_group:Languages:low_confidence"
        ]
      })
    );

    expect(report.notImported.map((entry) => `${entry.kind}/${entry.label}`)).toEqual([
      "Education/MIT",
      "Project/Cobol Compiler",
      "Certification/PMP",
      "Skills/Languages"
    ]);
  });

  it("treats a reason it does not recognise as a loss rather than swallowing it", () => {
    const report = buildMergeReport(summary({ skipped: ["experience:Acme:Engineer:some_new_reason"] }));

    expect(report.lostWork).toBe(true);
    expect(report.notImported[0]?.reason).toBe("unknown");
    // The unfamiliar trailing token stays in the label instead of being dropped,
    // so the entry is still recognisable to whoever has to go looking for it.
    expect(report.notImported[0]?.label).toContain("Acme");
  });

  it("survives a token with no label to show", () => {
    const report = buildMergeReport(summary({ skipped: ["experience:low_confidence"] }));

    expect(report.notImported[0]).toEqual({
      kind: "Role",
      label: "unnamed entry",
      reason: "low_confidence"
    });
  });

  it("says so when the parse added nothing at all", () => {
    const report = buildMergeReport(summary());

    expect(report.lostWork).toBe(false);
    expect(report.headline).toBe(
      "grace-hopper-resume.docx added nothing to your profile. Worth opening it to check what the parser saw."
    );
  });

  it("says so when the profile already held everything the resume offered", () => {
    const report = buildMergeReport(summary({ skipped: ["experience:Acme:Engineer:duplicate"] }));

    expect(report.headline).toBe("grace-hopper-resume.docx was already on your profile. Nothing new to add.");
  });

  it("passes parser warnings through untouched", () => {
    const warnings = ["No explicit Applyocalypse placeholders found."];
    expect(buildMergeReport(summary({ warnings })).warnings).toEqual(warnings);
  });

  it("explains each skip reason in plain words", () => {
    expect(reasonText("low_confidence")).toBe("the parser was not confident enough to keep it");
    expect(reasonText("duplicate")).toBe("already on your profile");
    expect(reasonText("unknown")).toBe("skipped");
  });
});
