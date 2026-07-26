export type ParsedJobIntakeItem = {
  sourceKind: "URL" | "TEXT";
  sourceValue: string;
};

/** Pull a leading URL off a line, tolerating trailing text like "(Remote)" pasted
 * after the link. Lines that merely mention a URL mid-sentence stay TEXT. */
const extractLeadingUrl = (line: string): { url: string | null; rest: string } => {
  const match = line.match(/^https?:\/\/\S+/i);
  if (!match) {
    return { url: null, rest: line };
  }
  const url = match[0].replace(/[),.;\]]+$/, "");
  const rest = line.slice(match[0].length).trim();
  return { url, rest };
};

export const parseJobIntake = (value: string): ParsedJobIntakeItem[] => {
  const trimmed = value.trim();
  if (!trimmed) {
    return [];
  }

  const lines = trimmed
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean);

  const urls: string[] = [];
  const textLines: string[] = [];
  for (const line of lines) {
    const { url, rest } = extractLeadingUrl(line);
    if (url) {
      urls.push(url);
      if (rest) {
        textLines.push(rest);
      }
    } else {
      textLines.push(line);
    }
  }

  if (urls.length === 0) {
    return [{ sourceKind: "TEXT" as const, sourceValue: trimmed }];
  }

  return [
    ...urls.map((sourceValue) => ({ sourceKind: "URL" as const, sourceValue })),
    { sourceKind: "TEXT" as const, sourceValue: textLines.join("\n") }
  ].filter((item) => item.sourceValue.trim().length > 0);
};
