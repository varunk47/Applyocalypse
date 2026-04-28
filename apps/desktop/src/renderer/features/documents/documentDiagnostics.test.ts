import { describe, expect, it } from "vitest";
import type { ParsedDocument } from "@applyocalypse/shared-types";
import { buildEditableMasterDiagnostics } from "./documentDiagnostics";

const parsedDocument = (overrides: Partial<ParsedDocument>): ParsedDocument =>
  ({
    id: "parsed-1",
    uploadedFileId: "upload-1",
    parserName: "applyocalypse-local-parser",
    parserVersion: "0.3.0",
    confidence: 0.8,
    canonical: {
      documentKind: "RESUME",
      sourceFormat: "DOCX",
      identity: {},
      sections: [],
      skillGroups: [],
      education: [],
      experience: [],
      projects: [],
      certifications: [],
      rawTextPreview: ""
    },
    styleMap: {},
    anchorMap: {},
    warnings: [],
    createdAt: "2026-01-01T00:00:00.000Z",
    updatedAt: "2026-01-01T00:00:00.000Z",
    ...overrides
  }) as ParsedDocument;

describe("document diagnostics", () => {
  it("marks DOCX masters with placeholders as mutation ready", () => {
    const diagnostics = buildEditableMasterDiagnostics(
      parsedDocument({
        anchorMap: {
          anchors: [{ anchor_id: "docx:p:0" }],
          placeholders: ["{{APPLYO_RESUME_SUMMARY}}"]
        }
      })
    );

    expect(diagnostics.mutationReadiness).toBe("ready");
    expect(diagnostics.placeholderCount).toBe(1);
    expect(diagnostics.structuralAnchorCount).toBe(1);
  });

  it("marks editable documents without placeholders for anchor repair", () => {
    const diagnostics = buildEditableMasterDiagnostics(
      parsedDocument({
        canonical: {
          ...parsedDocument({}).canonical,
          sourceFormat: "TEX"
        },
        anchorMap: { regions: [{ region_id: "tex:item:0" }], placeholders: [] },
        warnings: ["No explicit Applyocalypse placeholders found."]
      })
    );

    expect(diagnostics.mutationReadiness).toBe("needs_anchor_repair");
    expect(diagnostics.summary).toContain("Anchor repair");
  });
});
