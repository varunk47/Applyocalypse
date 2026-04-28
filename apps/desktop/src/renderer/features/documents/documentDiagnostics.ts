import type { ParsedDocument } from "@applyocalypse/shared-types";

export type EditableMasterDiagnostics = {
  sourceFormat: string;
  structuralAnchorCount: number;
  placeholderCount: number;
  placeholderPreview: string[];
  warningCount: number;
  mutationReadiness: "ready" | "needs_anchor_repair" | "review_only";
  summary: string;
};

const arrayFromUnknown = (value: unknown): unknown[] => (Array.isArray(value) ? value : []);

const stringArrayFromUnknown = (value: unknown): string[] =>
  arrayFromUnknown(value).filter((item): item is string => typeof item === "string" && item.trim().length > 0);

export const buildEditableMasterDiagnostics = (document: ParsedDocument): EditableMasterDiagnostics => {
  const sourceFormat = document.canonical.sourceFormat;
  const anchors = arrayFromUnknown(document.anchorMap["anchors"]);
  const regions = arrayFromUnknown(document.anchorMap["regions"]);
  const placeholders = stringArrayFromUnknown(document.anchorMap["placeholders"]);
  const structuralAnchorCount = anchors.length + regions.length;
  const placeholderCount = placeholders.length;
  const isEditableFormat = sourceFormat === "DOCX" || sourceFormat === "TEX";

  const mutationReadiness: EditableMasterDiagnostics["mutationReadiness"] = !isEditableFormat
    ? "review_only"
    : placeholderCount > 0
      ? "ready"
      : "needs_anchor_repair";

  const summary =
    mutationReadiness === "ready"
      ? `${placeholderCount} mutation anchor${placeholderCount === 1 ? "" : "s"} detected`
      : mutationReadiness === "needs_anchor_repair"
        ? "Anchor repair required before automated mutation"
        : "Review-only source";

  return {
    sourceFormat,
    structuralAnchorCount,
    placeholderCount,
    placeholderPreview: placeholders.slice(0, 3),
    warningCount: document.warnings.length,
    mutationReadiness,
    summary
  };
};
