import type { Database } from "better-sqlite3";
import { ThemePreferenceSchema } from "@applyocalypse/shared-schemas";
import type { z } from "zod";

export type ThemePreference = z.infer<typeof ThemePreferenceSchema>;

export class SettingsRepository {
  constructor(private readonly db: Database) {}

  getAll(): Record<string, unknown> {
    const rows = this.db.prepare("SELECT key, value_json FROM app_settings").all() as Array<{ key: string; value_json: string }>;
    return Object.fromEntries(rows.map((row) => [row.key, JSON.parse(row.value_json) as unknown]));
  }

  get<T>(key: string, fallbackValue: T): T {
    const row = this.db.prepare("SELECT value_json FROM app_settings WHERE key = ?").get(key) as { value_json: string } | undefined;
    return row ? (JSON.parse(row.value_json) as T) : fallbackValue;
  }

  set(key: string, value: unknown): void {
    this.db
      .prepare(
        `
        INSERT INTO app_settings (key, value_json, updated_at)
        VALUES (@key, @valueJson, @updatedAt)
        ON CONFLICT(key) DO UPDATE SET
          value_json = excluded.value_json,
          updated_at = excluded.updated_at
      `
      )
      .run({
        key,
        valueJson: JSON.stringify(value),
        updatedAt: new Date().toISOString()
      });
  }

  getThemePreference(): ThemePreference {
    const value = this.get("theme.preference", "system");
    return ThemePreferenceSchema.catch("system").parse(value);
  }

  setThemePreference(preference: ThemePreference): void {
    this.set("theme.preference", ThemePreferenceSchema.parse(preference));
  }
}
