import { existsSync, statSync, unlinkSync } from "node:fs";
import { isAbsolute, normalize, relative, resolve } from "node:path";
import type { ApplyocalypseDatabase } from "@applyocalypse/db";

export type GeneratedFileCleanupResult = {
  deleted: number;
  skipped: number;
};

type SafeRootsProvider = string[] | (() => string[]);

const isInsideRoot = (localPath: string, root: string): boolean => {
  const relativePath = relative(root, localPath);
  return relativePath === "" || (!relativePath.startsWith("..") && !isAbsolute(relativePath));
};

const isSafePath = (localPath: string, safeRoots: string[]): boolean => {
  if (!isAbsolute(localPath)) {
    return false;
  }
  const normalizedPath = normalize(resolve(localPath));
  return safeRoots.some((root) => isInsideRoot(normalizedPath, normalize(resolve(root))));
};

export class GeneratedFileCleanupService {
  constructor(
    private readonly db: ApplyocalypseDatabase,
    private readonly safeRoots: SafeRootsProvider
  ) {}

  cleanupExpired(now = new Date().toISOString()): GeneratedFileCleanupResult {
    const rows = this.db
      .prepare(
        `
        SELECT id, local_path
        FROM generated_files
        WHERE deleted_at IS NULL
          AND (
            (retention_policy = 'DELETE_AFTER_RETENTION' AND delete_after IS NOT NULL AND delete_after <= @now)
            OR (retention_policy = 'DELETE_AFTER_UPLOAD' AND upload_status = 'UPLOADED')
          )
        LIMIT 200
      `
      )
      .all({ now }) as Array<{ id: string; local_path: string }>;

    let deleted = 0;
    let skipped = 0;
    for (const row of rows) {
      const localPath = normalize(resolve(row.local_path));
      const safeRoots = typeof this.safeRoots === "function" ? this.safeRoots() : this.safeRoots;
      if (!isSafePath(localPath, safeRoots)) {
        skipped += 1;
        continue;
      }
      if (existsSync(localPath) && statSync(localPath).isFile()) {
        unlinkSync(localPath);
      }
      this.db
        .prepare("UPDATE generated_files SET deleted_at = @now, updated_at = @now WHERE id = @id AND deleted_at IS NULL")
        .run({ id: row.id, now });
      deleted += 1;
    }
    return { deleted, skipped };
  }
}
