import { readdirSync, rmSync, statSync } from "node:fs";
import { join } from "node:path";

const DEFAULT_RETENTION_DAYS = 7;

export const sweepStaleRunWorkDirs = (
  runsRoot: string,
  options: { retentionDays?: number; activeRunIds?: ReadonlySet<string>; now?: number } = {}
): string[] => {
  const retentionMs = (options.retentionDays ?? DEFAULT_RETENTION_DAYS) * 24 * 60 * 60 * 1000;
  const now = options.now ?? Date.now();
  const removed: string[] = [];
  let entries: string[];
  try {
    entries = readdirSync(runsRoot);
  } catch {
    return removed; // runs/ does not exist yet
  }
  for (const entry of entries) {
    if (options.activeRunIds?.has(entry)) continue;
    const dirPath = join(runsRoot, entry);
    try {
      const stats = statSync(dirPath);
      if (!stats.isDirectory()) continue;
      if (now - stats.mtimeMs > retentionMs) {
        rmSync(dirPath, { recursive: true, force: true });
        removed.push(entry);
      }
    } catch {
      // skip entries we cannot stat/remove
    }
  }
  return removed;
};
