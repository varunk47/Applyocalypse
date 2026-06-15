import { beforeEach, describe, expect, it, vi } from "vitest";
import type { SettingsRepository } from "@applyocalypse/db";

vi.mock("electron", () => ({ shell: { openExternal: vi.fn() } }));
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

import { shell } from "electron";
import { GmailOAuthService, parseIdTokenEmail } from "./gmailOAuthService";

const SETTINGS_KEY = "gmail.oauth.encryptedToken";
const GMAIL_TOKEN_URL = "https://oauth2.googleapis.com/token";
const GMAIL_SCOPE = "https://www.googleapis.com/auth/gmail.readonly";

const b64url = (obj: unknown): string => Buffer.from(JSON.stringify(obj)).toString("base64url");

const fakeRepository = (storedValue = ""): SettingsRepository =>
  ({ get: vi.fn().mockReturnValue(storedValue), set: vi.fn() }) as unknown as SettingsRepository;

beforeEach(() => {
  vi.mocked(shell.openExternal).mockReset();
  vi.mocked(shell.openExternal).mockResolvedValue(undefined as never);
});

describe("parseIdTokenEmail", () => {
  it("extracts the email from a JWT-shaped token", () => {
    const token = `header.${b64url({ email: "a@b.com" })}.sig`;
    expect(parseIdTokenEmail(token)).toBe("a@b.com");
  });

  it("returns null when the payload has no email", () => {
    const token = `header.${b64url({ sub: "123" })}.sig`;
    expect(parseIdTokenEmail(token)).toBeNull();
  });

  it("returns null for non-JWT garbage", () => {
    expect(parseIdTokenEmail("not-a-jwt")).toBeNull();
  });
});

describe("GmailOAuthService status", () => {
  it("reports disconnected when no token is stored", () => {
    const service = new GmailOAuthService(fakeRepository(""));
    expect(service.getStatus()).toEqual({ connected: false, email: null });
  });

  it("reports connected with the stored email when a token decrypts", () => {
    const service = new GmailOAuthService(fakeRepository("enc:" + JSON.stringify({ email: "x@y.z" })));
    expect(service.getStatus()).toEqual({ connected: true, email: "x@y.z" });
  });

  it("reports disconnected when the stored token cannot be decrypted", () => {
    const service = new GmailOAuthService(fakeRepository("CORRUPT"));
    expect(service.getStatus()).toEqual({ connected: false, email: null });
  });

  it("clears the stored token on disconnect", () => {
    const repo = fakeRepository("enc:whatever");
    new GmailOAuthService(repo).disconnect();
    expect(repo.set).toHaveBeenCalledWith(SETTINGS_KEY, "");
  });

  it("round-trips the decrypted token json and returns null when corrupt", () => {
    const json = JSON.stringify({ email: "z@z.z", refresh_token: "rt" });
    expect(new GmailOAuthService(fakeRepository("enc:" + json)).getDecryptedTokenJson()).toBe(json);
    expect(new GmailOAuthService(fakeRepository("CORRUPT")).getDecryptedTokenJson()).toBeNull();
  });
});

describe("GmailOAuthService startOAuthFlow", () => {
  const extractState = (): string => {
    const authUrl = vi.mocked(shell.openExternal).mock.calls[0]![0] as string;
    const state = new URL(authUrl).searchParams.get("state");
    expect(state).toBeTruthy();
    return state!;
  };

  it("rejects a state mismatch without calling the token endpoint", async () => {
    const realFetch = globalThis.fetch;
    const fetchStub = vi.fn();
    vi.stubGlobal("fetch", fetchStub);
    try {
      const service = new GmailOAuthService(fakeRepository(""));
      const flowPromise = service.startOAuthFlow("client-id", "client-secret");
      await vi.waitFor(() => expect(shell.openExternal).toHaveBeenCalled());
      extractState();

      await realFetch("http://127.0.0.1:9736/?code=abc&state=WRONG");
      const result = await flowPromise;

      expect(result.ok).toBe(false);
      expect(fetchStub).not.toHaveBeenCalled();
    } finally {
      vi.unstubAllGlobals();
    }
  });

  it("persists an encrypted token on the happy path", async () => {
    const realFetch = globalThis.fetch;
    const fetchStub = vi.fn(async (url: string | URL) => {
      if (String(url).startsWith(GMAIL_TOKEN_URL)) {
        return {
          ok: true,
          json: async () => ({ access_token: "at", refresh_token: "rt", token_type: "Bearer", expires_in: 3600 })
        } as unknown as Response;
      }
      return realFetch(url);
    });
    vi.stubGlobal("fetch", fetchStub);
    try {
      const repo = fakeRepository("");
      const service = new GmailOAuthService(repo);
      const flowPromise = service.startOAuthFlow("client-id", "client-secret");
      await vi.waitFor(() => expect(shell.openExternal).toHaveBeenCalled());
      const state = extractState();

      await realFetch(`http://127.0.0.1:9736/?code=abc&state=${state}`);
      const result = await flowPromise;

      expect(result.ok).toBe(true);
      const [, storedValue] = vi.mocked(repo.set).mock.calls[0]!;
      expect(String(storedValue).startsWith("enc:")).toBe(true);
      const decoded = JSON.parse(String(storedValue).replace(/^enc:/, ""));
      expect(decoded.refresh_token).toBe("rt");
      expect(decoded.scopes).toContain(GMAIL_SCOPE);
    } finally {
      vi.unstubAllGlobals();
    }
  });
});
