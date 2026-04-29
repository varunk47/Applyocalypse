import type { Database } from "better-sqlite3";
import { existsSync, readdirSync, readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

export type MigrationResult = {
  applied: string[];
  skipped: string[];
};

const currentDir = dirname(fileURLToPath(import.meta.url));

type ElectronProcess = NodeJS.Process & {
  resourcesPath?: string;
};

const isMigrationDir = (path: string): boolean => {
  try {
    return existsSync(path) && readdirSync(path).some((file) => file.endsWith(".sql"));
  } catch {
    return false;
  }
};

const collectUpwardMigrationDirs = (startDir: string): string[] => {
  const dirs: string[] = [];
  let cursor = resolve(startDir);

  while (true) {
    dirs.push(join(cursor, "packages", "db", "migrations"));
    dirs.push(join(cursor, "migrations"));

    const parent = dirname(cursor);
    if (parent === cursor) {
      break;
    }
    cursor = parent;
  }

  return dirs;
};

const candidateMigrationDirs = (): string[] => {
  const resourcesPath = (process as ElectronProcess).resourcesPath;
  const explicitDirs = [
    resolve(currentDir, "../migrations"),
    resolve(currentDir, "../../migrations"),
    resolve(process.cwd(), "packages/db/migrations"),
    resourcesPath ? resolve(resourcesPath, "migrations") : undefined
  ].filter((path): path is string => Boolean(path));

  return Array.from(
    new Set([
      ...explicitDirs,
      ...collectUpwardMigrationDirs(currentDir),
      ...collectUpwardMigrationDirs(process.cwd())
    ])
  );
};

export const resolveMigrationDir = (): string => {
  const checkedDirs = candidateMigrationDirs();
  const migrationDir = checkedDirs.find((path) => isMigrationDir(path));
  if (!migrationDir) {
    throw new Error(`No migration directory found. Checked: ${checkedDirs.join(", ")}`);
  }
  return migrationDir;
};

export const runMigrations = (db: Database, migrationDir = resolveMigrationDir()): MigrationResult => {
  db.exec(`
    CREATE TABLE IF NOT EXISTS schema_migrations (
      id TEXT PRIMARY KEY,
      applied_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
    );
  `);

  const files = readdirSync(migrationDir)
    .filter((file) => file.endsWith(".sql"))
    .sort((a, b) => a.localeCompare(b));

  const alreadyApplied = new Set(
    db.prepare("SELECT id FROM schema_migrations ORDER BY id").all().map((row) => String((row as { id: string }).id))
  );

  const applied: string[] = [];
  const skipped: string[] = [];

  const migrate = db.transaction((file: string) => {
    const sql = readFileSync(join(migrationDir, file), "utf8");
    db.exec(sql);
    db.prepare("INSERT INTO schema_migrations (id) VALUES (?)").run(file);
  });

  const migrateWithoutTransaction = (file: string) => {
    const sql = readFileSync(join(migrationDir, file), "utf8");
    db.exec(sql);
    db.prepare("INSERT INTO schema_migrations (id) VALUES (?)").run(file);
  };

  for (const file of files) {
    if (alreadyApplied.has(file)) {
      skipped.push(file);
      continue;
    }

    const sql = readFileSync(join(migrationDir, file), "utf8");
    if (sql.includes("-- applyocalypse:no-transaction")) {
      migrateWithoutTransaction(file);
    } else {
      migrate(file);
    }
    applied.push(file);
  }

  return { applied, skipped };
};
