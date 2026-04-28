import { describe, expect, it } from "vitest";
import { validateTextArtifact } from "./index";

describe("text artifact validation", () => {
  it("blocks banned wording and em dashes", () => {
    const report = validateTextArtifact("I utilize Python \u2014 daily.", { artifactKind: "cover_letter" });

    expect(report.passed).toBe(false);
    expect(report.blockingIssues.map((issue) => issue.code).sort()).toEqual(["BANNED_WORD", "EM_DASH"]);
  });

  it("warns on long resume bullets without blocking", () => {
    const report = validateTextArtifact(
      "- Built a platform with many many many many many many many many many many many many many many many many many many many many many many many many many many many many many many many many words",
      { artifactKind: "resume" }
    );

    expect(report.passed).toBe(true);
    expect(report.warnings.some((issue) => issue.code === "LONG_BULLET")).toBe(true);
  });

  it("warns on weak resume bullets and repetitive rhythm", () => {
    const report = validateTextArtifact(
      "Experience\nSkills\n- Worked on internal tools\n- Worked on APIs\n- Worked on test suites",
      { artifactKind: "resume" }
    );

    expect(report.passed).toBe(true);
    expect(report.warnings.some((issue) => issue.code === "WEAK_BULLET")).toBe(true);
    expect(report.warnings.some((issue) => issue.code === "REPETITIVE_RHYTHM")).toBe(true);
  });
});
