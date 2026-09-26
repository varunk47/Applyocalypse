import { describe, expect, it, vi } from "vitest";
import type { SettingsRepository } from "@applyocalypse/db";

vi.mock("./secureSecretStore", () => ({
  SecureSecretStore: class {
    encryptSecret(value: string): string {
      return "enc:" + value;
    }
    decryptSecret(value: string): string {
      if (value === "CORRUPT") throw new Error("decrypt failed");
      return value.replace(/^enc:/, "");
    }
  }
}));

import { JevKeyService } from "./jevKeyService";

const SETTINGS_KEY = "jev.gatewayKey.encrypted";

function makeRepository(initial: Record<string, string> = {}) {
  const store = new Map(Object.entries(initial));
  return {
    store,
    repository: {
      get: <T>(key: string, fallback: T) => (store.has(key) ? store.get(key) : fallback) as T,
      set: (key: string, value: string) => void store.set(key, value)
    } as unknown as SettingsRepository
  };
}

describe("JevKeyService", () => {
  it("stores the key encrypted and reads it back", () => {
    const { store, repository } = makeRepository();
    const service = new JevKeyService(repository);

    service.save("  gateway-key  ");

    expect(store.get(SETTINGS_KEY)).toBe("enc:gateway-key");
    expect(service.getDecryptedKey()).toBe("gateway-key");
    expect(service.getStatus()).toEqual({ configured: true });
  });

  it.each([
    ["no key saved", {}],
    ["a cleared key", { [SETTINGS_KEY]: "" }],
    ["a key that no longer decrypts", { [SETTINGS_KEY]: "CORRUPT" }]
  ])("reports %s as not configured", (_label, initial) => {
    const service = new JevKeyService(makeRepository(initial).repository);

    expect(service.getDecryptedKey()).toBeNull();
    expect(service.getStatus()).toEqual({ configured: false });
  });

  it("clears the key", () => {
    const { repository } = makeRepository();
    const service = new JevKeyService(repository);
    service.save("gateway-key");

    service.clear();

    expect(service.getStatus()).toEqual({ configured: false });
  });
});
