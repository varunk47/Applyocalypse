import { app } from "electron";
import { join } from "node:path";
import { openApplyocalypseDatabase, runMigrations, type ApplyocalypseDatabase } from "@applyocalypse/db";

export const createAppDatabase = (): ApplyocalypseDatabase => {
  const dbPath = join(app.getPath("userData"), "applyocalypse.sqlite");
  const db = openApplyocalypseDatabase(dbPath);
  runMigrations(db);
  return db;
};
