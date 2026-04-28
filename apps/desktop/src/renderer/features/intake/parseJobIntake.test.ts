import { describe, expect, it } from "vitest";
import { parseJobIntake } from "./parseJobIntake";

describe("parseJobIntake", () => {
  it("keeps a multi-line job description as one text target", () => {
    const parsed = parseJobIntake("Senior engineer\nRequired: TypeScript\nCover letter required");

    expect(parsed).toEqual([
      {
        sourceKind: "TEXT",
        sourceValue: "Senior engineer\nRequired: TypeScript\nCover letter required"
      }
    ]);
  });

  it("splits a pure URL list into separate URL targets", () => {
    const parsed = parseJobIntake("https://example.com/a\nhttps://example.com/b");

    expect(parsed).toEqual([
      { sourceKind: "URL", sourceValue: "https://example.com/a" },
      { sourceKind: "URL", sourceValue: "https://example.com/b" }
    ]);
  });

  it("preserves mixed URL and description intake without fragmenting text lines", () => {
    const parsed = parseJobIntake("https://example.com/a\nStaff role\nRequired: Python");

    expect(parsed).toEqual([
      { sourceKind: "URL", sourceValue: "https://example.com/a" },
      { sourceKind: "TEXT", sourceValue: "Staff role\nRequired: Python" }
    ]);
  });
});
