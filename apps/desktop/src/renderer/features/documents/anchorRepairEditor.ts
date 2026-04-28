import type { ParsedDocument } from "@applyocalypse/shared-types";
import { buildEditableMasterDiagnostics } from "./documentDiagnostics";

export type AnchorRepairZone = {
  zoneId: string;
  label: string;
  status: "ready" | "repairable" | "review_only";
  confidence: number;
  placeholder: string | null;
  sourceHint: string;
  priority: number;
};

export type AnchorRepairEditorModel = {
  sourceFormat: string;
  readiness: "ready" | "needs_anchor_repair" | "review_only";
  zones: AnchorRepairZone[];
  actionLabel: string;
  canCreateCandidate: boolean;
};

const PLACEHOLDER_BY_LABEL: Record<string, string> = {
  summary: "{{APPLYO_RESUME_SUMMARY}}",
  skills: "{{APPLYO_SKILLS}}",
  experience: "{{APPLYO_EXPERIENCE}}",
  projects: "{{APPLYO_PROJECTS}}",
  education: "{{APPLYO_EDUCATION}}"
};

const normalizedLabel = (value: string): string => value.trim().toLowerCase();

const arrayFromUnknown = (value: unknown): unknown[] => (Array.isArray(value) ? value : []);

const placeholderSet = (document: ParsedDocument): Set<string> =>
  new Set(arrayFromUnknown(document.anchorMap["placeholders"]).filter((item): item is string => typeof item === "string"));

const zoneForSection = (document: ParsedDocument, sectionLabel: string, index: number): AnchorRepairZone => {
  const label = normalizedLabel(sectionLabel);
  const placeholders = placeholderSet(document);
  const placeholder = PLACEHOLDER_BY_LABEL[label] ?? null;
  const hasPlaceholder = Boolean(placeholder && placeholders.has(placeholder));
  const confidence = Math.max(0.2, Math.min(1, document.confidence - index * 0.04));
  const isKnownEditableRegion = placeholder !== null;

  return {
    zoneId: `${label || "section"}-${index}`,
    label: sectionLabel || `Section ${index + 1}`,
    status: hasPlaceholder ? "ready" : isKnownEditableRegion ? "repairable" : "review_only",
    confidence,
    placeholder,
    sourceHint: hasPlaceholder ? "Explicit Applyocalypse placeholder present" : isKnownEditableRegion ? "Candidate region can receive a placeholder" : "Review manually",
    priority: hasPlaceholder ? 0 : isKnownEditableRegion ? 1 : 2
  };
};

export const buildAnchorRepairEditorModel = (document: ParsedDocument): AnchorRepairEditorModel => {
  const diagnostics = buildEditableMasterDiagnostics(document);
  const sectionLabels = document.canonical.sections.map((section) => section.label).filter((label) => label.trim().length > 0);
  const fallbackLabels = sectionLabels.length > 0 ? sectionLabels : ["Summary", "Skills", "Experience", "Projects"];
  const zones = fallbackLabels
    .map((label, index) => zoneForSection(document, label, index))
    .sort((left, right) => left.priority - right.priority || right.confidence - left.confidence || left.label.localeCompare(right.label));

  return {
    sourceFormat: diagnostics.sourceFormat,
    readiness: diagnostics.mutationReadiness,
    zones,
    actionLabel:
      diagnostics.mutationReadiness === "ready"
        ? "Open verified source"
        : diagnostics.mutationReadiness === "needs_anchor_repair"
          ? "Create anchored candidate"
          : "Open review source",
    canCreateCandidate: diagnostics.mutationReadiness === "needs_anchor_repair"
  };
};
