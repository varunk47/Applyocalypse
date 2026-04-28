import { describe, expect, it } from "vitest";
import { buildGeneratedDocumentFilename, sanitizeFilenamePart } from "./index";

describe("document filename policy", () => {
  it("sanitizes filesystem-hostile characters", () => {
    expect(sanitizeFilenamePart('Acme: Platform/Tools*?')).toBe("Acme Platform Tools");
  });

  it("builds deterministic generated document names", () => {
    expect(
      buildGeneratedDocumentFilename({
        firstName: "Ada",
        lastName: "Lovelace",
        company: "Difference Engines",
        role: "Staff Engineer",
        kind: "Resume",
        extension: "docx"
      })
    ).toBe("Ada Lovelace Difference Engines Staff Engineer Resume.docx");
  });
});
