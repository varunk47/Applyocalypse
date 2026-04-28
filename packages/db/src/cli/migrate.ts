import { join } from "node:path";
import { openApplyocalypseDatabase, runMigrations } from "../index";

const dbPath = process.env.APPLYO_DB_PATH ?? join(process.cwd(), ".local", "applyocalypse.sqlite");
const db = openApplyocalypseDatabase(dbPath);
try {
  const result = runMigrations(db);
  console.log(JSON.stringify({ dbPath, ...result }, null, 2));
} finally {
  db.close();
}
