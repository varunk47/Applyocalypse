import type { RunEvent, SafeRendererRunEvent } from "@applyocalypse/shared-types";

export type MaterialsEvent = Pick<RunEvent | SafeRendererRunEvent, "eventType" | "severity" | "message" | "payload" | "timestamp">;

export type CoverLetterRequirementSummary = {
  status: "PENDING" | "OPTIONAL" | "REQUIRED" | "MISSING_REQUIRED";
  source: "UNKNOWN" | "JD_ANALYSIS" | "APPLICATION_FORM" | "MULTIPLE";
  required: boolean;
  fieldCount: number;
  missingRequiredDocuments: number;
  latestMessage: string;
  updatedAt: string | null;
};

const asRecord = (value: unknown): Record<string, unknown> =>
  value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : {};

const asArray = (value: unknown): unknown[] => (Array.isArray(value) ? value : []);

const sortedEvents = (events: readonly MaterialsEvent[]): MaterialsEvent[] =>
  [...events].sort((first, second) => first.timestamp.localeCompare(second.timestamp));

const normalizeSource = (source: unknown): "UNKNOWN" | "JD_ANALYSIS" | "APPLICATION_FORM" => {
  const normalized = typeof source === "string" ? source.toUpperCase() : "";
  if (normalized === "JD_ANALYSIS" || normalized === "APPLICATION_FORM") {
    return normalized;
  }
  return "UNKNOWN";
};

const combinedSource = (events: readonly MaterialsEvent[]): CoverLetterRequirementSummary["source"] => {
  const sources = new Set(events.map((event) => normalizeSource(asRecord(event.payload)["source"])).filter((source) => source !== "UNKNOWN"));
  if (sources.size > 1) {
    return "MULTIPLE";
  }
  return sources.values().next().value ?? "UNKNOWN";
};

const missingCoverLetterDocuments = (events: readonly MaterialsEvent[]): number =>
  events.reduce((count, event) => {
    const payload = asRecord(event.payload);
    const missingDocuments = asArray(payload["missing_documents"]);
    if (missingDocuments.length > 0) {
      return (
        count +
        missingDocuments.filter((item) => {
          const document = asRecord(item);
          return String(document["file_kind"] ?? "").toUpperCase() === "COVER_LETTER";
        }).length
      );
    }
    return String(payload["file_kind"] ?? "").toUpperCase() === "COVER_LETTER" && payload["required"] === true ? count + 1 : count;
  }, 0);

export const buildCoverLetterRequirementSummary = (events: readonly MaterialsEvent[]): CoverLetterRequirementSummary => {
  const ordered = sortedEvents(events);
  const coverLetterEvents = ordered.filter((event) => event.eventType === "COVER_LETTER_REQUIRED");
  const latestRequirement = coverLetterEvents.at(-1);
  const latestPayload = asRecord(latestRequirement?.payload);
  const missingRequiredDocuments = missingCoverLetterDocuments(ordered);
  const required = latestPayload["required"] === true || missingRequiredDocuments > 0;
  const fieldCount = typeof latestPayload["field_count"] === "number" ? latestPayload["field_count"] : 0;

  return {
    status: missingRequiredDocuments > 0 ? "MISSING_REQUIRED" : required ? "REQUIRED" : latestRequirement ? "OPTIONAL" : "PENDING",
    source: combinedSource(coverLetterEvents),
    required,
    fieldCount,
    missingRequiredDocuments,
    latestMessage: latestRequirement?.message ?? "No cover-letter requirement has been detected yet.",
    updatedAt: latestRequirement?.timestamp ?? null
  };
};
