import { safeStorage } from "electron";

export class SecureSecretStore {
  encryptSecret(value: string): string {
    if (!safeStorage.isEncryptionAvailable()) {
      throw new Error("OS-backed secure storage is not available on this device");
    }
    return safeStorage.encryptString(value).toString("base64");
  }

  decryptSecret(reference: string): string {
    if (!safeStorage.isEncryptionAvailable()) {
      throw new Error("OS-backed secure storage is not available on this device");
    }
    return safeStorage.decryptString(Buffer.from(reference, "base64"));
  }

  redactedHint(value: string): string {
    if (value.length <= 8) {
      return "[REDACTED]";
    }
    return `${value.slice(0, 3)}...${value.slice(-4)}`;
  }
}
