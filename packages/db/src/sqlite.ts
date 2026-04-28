import Database from "better-sqlite3";
import { mkdirSync } from "node:fs";
import { dirname } from "node:path";

export type ApplyocalypseDatabase = Database.Database;

export const openApplyocalypseDatabase = (dbPath: string): ApplyocalypseDatabase => {
  mkdirSync(dirname(dbPath), { recursive: true });
  const db = new Database(dbPath);
  db.pragma("foreign_keys = ON");
  db.pragma("journal_mode = WAL");
  db.pragma("busy_timeout = 5000");
  return db;
};

export const closeApplyocalypseDatabase = (db: ApplyocalypseDatabase): void => {
  db.close();
};
