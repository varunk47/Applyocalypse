/**
 * `mergeIntoProfile` already reports exactly what it did with a parsed resume:
 * `applied` lists what reached the profile, `skipped` lists what did not, and
 * every skip carries its reason. Nothing in the renderer read `skipped`, so a
 * resume whose roles parsed at 0.74 lost them on the way in while the card next
 * to it still said PARSED. This turns those strings into something a person can
 * act on: which entries are missing, and why.
 */

/** The reasons `mergeIntoProfile` writes today, plus a catch-all for new ones. */
export type SkipReason = "low_confidence" | "duplicate" | "unknown";

export type SkippedEntry = {
  /** Display name for the section, e.g. `Role`. */
  kind: string;
  label: string;
  reason: SkipReason;
};

export type MergeSummaryInput = {
  sourceName: string;
  applied: string[];
  skipped: string[];
  warnings: string[];
};

export type MergeReport = {
  importedCount: number;
  /** Entries the merge dropped. These are gone unless the user adds them by hand. */
  notImported: SkippedEntry[];
  /** Entries the profile already had. Benign, and worth saying so. */
  alreadyOnFile: SkippedEntry[];
  warnings: string[];
  lostWork: boolean;
  headline: string;
};

const KIND_LABELS: Record<string, string> = {
  experience: "Role",
  education: "Education",
  project: "Project",
  certification: "Certification",
  skill_group: "Skills"
};

const kindLabel = (kind: string): string =>
  KIND_LABELS[kind] ?? (kind ? kind.replace(/_/g, " ") : "Entry");

/**
 * Experience is written `experience:<company>:<title>`, everything else
 * `<kind>:<name>`. Read the company off the front and let the title keep any
 * colon it contains, because "Engineer II: Platform" is a real job title.
 */
const describe = (kind: string, parts: string[]): string => {
  if (kind === "experience" && parts.length > 1) {
    const [company, ...title] = parts;
    const joined = [title.join(":"), company].filter(Boolean).join(" at ");
    return joined || "unnamed entry";
  }
  return parts.join(":") || "unnamed entry";
};

/**
 * Tokens read right to left: the reason is written last, and the label in the
 * middle can hold colons of its own, so splitting left to right would mangle it.
 */
const parseSkipped = (token: string): SkippedEntry => {
  const [kind = "", ...rest] = token.split(":");
  const tail = rest[rest.length - 1];
  const reason: SkipReason = tail === "low_confidence" || tail === "duplicate" ? tail : "unknown";
  if (reason !== "unknown") rest.pop();
  return { kind: kindLabel(kind), label: describe(kind, rest), reason };
};

const plural = (count: number, one: string, many: string): string =>
  `${count} ${count === 1 ? one : many}`;

/** What to tell the user about a single dropped entry. */
export const reasonText = (reason: SkipReason): string => {
  if (reason === "low_confidence") return "the parser was not confident enough to keep it";
  if (reason === "duplicate") return "already on your profile";
  return "skipped";
};

const buildHeadline = (
  sourceName: string,
  importedCount: number,
  notImported: SkippedEntry[],
  alreadyOnFile: SkippedEntry[]
): string => {
  if (notImported.length > 0) {
    return `${plural(notImported.length, "entry", "entries")} from ${sourceName} did not make it onto your profile.`;
  }
  if (importedCount > 0) {
    return `${plural(importedCount, "detail", "details")} from ${sourceName} landed on your profile. Nothing was dropped.`;
  }
  if (alreadyOnFile.length > 0) {
    return `${sourceName} was already on your profile. Nothing new to add.`;
  }
  return `${sourceName} added nothing to your profile. Worth opening it to check what the parser saw.`;
};

export const buildMergeReport = (summary: MergeSummaryInput): MergeReport => {
  const parsed = summary.skipped.map(parseSkipped);
  const alreadyOnFile = parsed.filter((entry) => entry.reason === "duplicate");
  // An unrecognised reason is still an entry that did not land, so it belongs
  // with the losses. Silence is the failure mode being fixed here.
  const notImported = parsed.filter((entry) => entry.reason !== "duplicate");

  return {
    importedCount: summary.applied.length,
    notImported,
    alreadyOnFile,
    warnings: summary.warnings,
    lostWork: notImported.length > 0,
    headline: buildHeadline(summary.sourceName, summary.applied.length, notImported, alreadyOnFile)
  };
};
