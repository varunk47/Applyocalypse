import { BrowserWindow, nativeTheme } from "electron";
import type { SettingsRepository } from "@applyocalypse/db";
import { ThemePreferenceSchema, ThemeStateSchema } from "@applyocalypse/shared-schemas";
import type { ThemePreference, ThemeState } from "@applyocalypse/shared-types";
import { IpcChannels } from "@applyocalypse/ipc-contracts";

export class ThemeController {
  private preference: ThemePreference;

  constructor(
    private readonly settings: SettingsRepository,
    private readonly windows: () => BrowserWindow[]
  ) {
    this.preference = this.settings.getThemePreference();
    nativeTheme.themeSource = this.preference;
    nativeTheme.on("updated", () => {
      if (this.preference === "system") {
        this.broadcast();
      }
    });
  }

  getState(): ThemeState {
    return ThemeStateSchema.parse({
      preference: this.preference,
      activeTheme: nativeTheme.shouldUseDarkColors ? "dark" : "light",
      updatedAt: new Date().toISOString()
    });
  }

  setPreference(preference: ThemePreference): ThemeState {
    this.preference = ThemePreferenceSchema.parse(preference);
    this.settings.setThemePreference(this.preference);
    nativeTheme.themeSource = this.preference;
    const state = this.getState();
    this.broadcast(state);
    return state;
  }

  broadcast(state = this.getState()): void {
    for (const window of this.windows()) {
      if (!window.isDestroyed()) {
        window.webContents.send(IpcChannels.themeUpdated, state);
      }
    }
  }
}
