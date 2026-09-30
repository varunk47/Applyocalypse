import { SecureSecretStore } from "./secureSecretStore";
import type { SettingsRepository } from "@applyocalypse/db";

const SETTINGS_KEY = "jev.gatewayKey.encrypted";

// The Vercel AI Gateway key that lets the worker ask Jev for each browser step.
// Only whether it is set ever leaves the main process.
export class JevKeyService {
  private readonly secureStore: SecureSecretStore;
  private readonly settingsRepository: SettingsRepository;

  constructor(settingsRepository: SettingsRepository) {
    this.secureStore = new SecureSecretStore();
    this.settingsRepository = settingsRepository;
  }

  getStatus(): { configured: boolean } {
    return { configured: this.getDecryptedKey() !== null };
  }

  save(key: string): void {
    this.settingsRepository.set(SETTINGS_KEY, this.secureStore.encryptSecret(key.trim()));
  }

  clear(): void {
    this.settingsRepository.set(SETTINGS_KEY, "");
  }

  getDecryptedKey(): string | null {
    const encryptedKey = this.settingsRepository.get<string>(SETTINGS_KEY, "");
    if (!encryptedKey) return null;
    try {
      return this.secureStore.decryptSecret(encryptedKey) || null;
    } catch {
      return null;
    }
  }
}
