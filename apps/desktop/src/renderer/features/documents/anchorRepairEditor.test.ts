import { describe, expect, it } from "vitest";
import type { ParsedDocument } from "@applyocalypse/shared-types";
import { buildAnchorRepairEditorModel } from "./anchorRepairEditor";

const parsedDocument = (overrides: Partial<ParsedDocument>): ParsedDocument =>
  ({
    id: "parsed-1",
    uploadedFileId: "upload-1",
    parserName: "applyocalypse-local-parser",
    parserVersion: "0.3.0",
    confidence: 0.86,
    canonical: {
      documentKind: "RESUME",
      sourceFormat: "DOCX",
      identity: {},
      sections: [
        { label: "Summary", text: "Platform engineer", confidence: 0.9 },
        { label: "Skills", text: "TypeScript, Python", confidence: 0.88 },
        { label: "Patents", text: "Patent detail", confidence: 0.6 }
      ],
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

describe("anchor repair editor model", () => {
  it("prioritizes ready zones and repairable canonical sections", () => {
    const model = buildAnchorRepairEditorModel(
      parsedDocument({
        anchorMap: {
          placeholders: ["{{APPLYO_RESUME_SUMMARY}}"]
        }
      })
    );

    expect(model.readiness).toBe("ready");
    expect(model.zones[0]).toMatchObject({
      label: "Summary",
      status: "ready",
      placeholder: "{{APPLYO_RESUME_SUMMARY}}"
    });
    expect(model.zones.some((zone) => zone.label === "Skills" && zone.status === "repairable")).toBe(true);
  });

  it("marks editable documents without placeholders as candidate repair targets", () => {
    const model = buildAnchorRepairEditorModel(parsedDocument({ anchorMap: { placeholders: [] } }));

    expect(model.readiness).toBe("needs_anchor_repair");
    expect(model.canCreateCandidate).toBe(true);
    expect(model.actionLabel).toBe("Create anchored candidate");
    expect(model.zones.filter((zone) => zone.status === "repairable").length).toBeGreaterThanOrEqual(2);
  });
});
