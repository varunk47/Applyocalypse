export type ParsedJobIntakeItem = {
  sourceKind: "URL" | "TEXT";
  sourceValue: string;
};

const isStandaloneUrl = (value: string): boolean => /^https?:\/\/\S+$/i.test(value.trim());

export const parseJobIntake = (value: string): ParsedJobIntakeItem[] => {
  const trimmed = value.trim();
  if (!trimmed) {
    return [];
  }

  const lines = trimmed
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean);
  const urlLines = lines.filter(isStandaloneUrl);
  const textLines = lines.filter((line) => !isStandaloneUrl(line));

  if (urlLines.length === lines.length) {
    return urlLines.map((sourceValue) => ({ sourceKind: "URL" as const, sourceValue }));
  }

  if (urlLines.length === 0) {
    return [{ sourceKind: "TEXT" as const, sourceValue: trimmed }];
  }

  return [
    ...urlLines.map((sourceValue) => ({ sourceKind: "URL" as const, sourceValue })),
    { sourceKind: "TEXT" as const, sourceValue: textLines.join("\n") }
  ].filter((item) => item.sourceValue.trim().length > 0);
};
