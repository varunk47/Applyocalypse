import { describe, expect, it, vi } from "vitest";
import type { SupabaseClient } from "@supabase/supabase-js";
import type { SettingsRepository } from "@applyocalypse/db";

vi.mock("electron", () => ({ shell: { openExternal: vi.fn() }, safeStorage: {} }));

import { AccountAuthService, encryptedSettingsStorage } from "./accountAuthService";
import { rendererSafeSettings } from "../ipc/handlers/settingsHandlers";

const makeRepository = () => {
  const store = new Map<string, unknown>();
  return {
    store,
    repository: {
      get: <T>(key: string, fallback: T) => (store.has(key) ? store.get(key) : fallback) as T,
      set: (key: string, value: unknown) => void store.set(key, value)
    } as unknown as SettingsRepository
  };
};

const fakeStore = {
  encryptSecret: (value: string) => `enc:${value}`,
  decryptSecret: (value: string) => {
    if (value === "CORRUPT") throw new Error("decrypt failed");
    return value.replace(/^enc:/, "");
  }
};

const session = { user: { email: "jane@example.com" } };

const fakeClient = (auth: Record<string, unknown>) => ({ auth }) as unknown as SupabaseClient;

describe("encryptedSettingsStorage", () => {
  it("keeps the session encrypted under an encrypted settings key", () => {
    const { store, repository } = makeRepository();
    const storage = encryptedSettingsStorage(repository, fakeStore);

    void storage.setItem("sb-auth-token", '{"access_token":"secret"}');

    expect([...store.entries()]).toEqual([["auth.supabase.sb-auth-token.encrypted", 'enc:{"access_token":"secret"}']]);
    expect(storage.getItem("sb-auth-token")).toBe('{"access_token":"secret"}');
    void storage.removeItem("sb-auth-token");
    expect(storage.getItem("sb-auth-token")).toBeNull();
  });

  it("treats an unreadable value as signed out", () => {
    const { store, repository } = makeRepository();
    store.set("auth.supabase.sb-auth-token.encrypted", "CORRUPT");

    expect(encryptedSettingsStorage(repository, fakeStore).getItem("sb-auth-token")).toBeNull();
  });

  it("never sends encrypted settings to the renderer", () => {
    expect(
      rendererSafeSettings({
        "auth.supabase.sb-auth-token.encrypted": "enc:x",
        "gmail.oauth.encryptedToken": "enc:y",
        "files.outputDir": "C:\\out"
      })
    ).toEqual({ "files.outputDir": "C:\\out" });
  });
});

describe("AccountAuthService", () => {
  const { repository } = makeRepository();

  it.each([
    [{ session }, { signedIn: true, email: "jane@example.com" }],
    [{ session: null }, { signedIn: false, email: null }]
  ])("reports the stored session", async (data, expected) => {
    const service = new AccountAuthService(repository, fakeClient({ getSession: async () => ({ data }) }));

    await expect(service.getState()).resolves.toEqual(expected);
  });

  it("asks for email confirmation when sign-up returns no session", async () => {
    const service = new AccountAuthService(
      repository,
      fakeClient({ signUp: async () => ({ data: { user: session.user, session: null }, error: null }) })
    );

    const result = await service.signUp("jane@example.com", "long-enough");

    expect(result).toMatchObject({ ok: false, signedIn: false });
    expect(result.message).toMatch(/confirm your email/);
  });

  it("signs in straight away when sign-up returns a session", async () => {
    const service = new AccountAuthService(
      repository,
      fakeClient({ signUp: async () => ({ data: { user: session.user, session }, error: null }) })
    );

    await expect(service.signUp("jane@example.com", "long-enough")).resolves.toMatchObject({
      ok: true,
      signedIn: true,
      email: "jane@example.com"
    });
  });

  it("passes Supabase's sign-in error through", async () => {
    const service = new AccountAuthService(
      repository,
      fakeClient({ signInWithPassword: async () => ({ data: { user: null, session: null }, error: { message: "Invalid login credentials" } }) })
    );

    await expect(service.signIn("jane@example.com", "wrong-password")).resolves.toEqual({
      ok: false,
      signedIn: false,
      email: null,
      message: "Invalid login credentials"
    });
  });

  it("signs out on this device only", async () => {
    const signOut = vi.fn(async () => ({ error: null }));
    const service = new AccountAuthService(repository, fakeClient({ signOut }));

    await expect(service.signOut()).resolves.toEqual({ signedIn: false, email: null });
    expect(signOut).toHaveBeenCalledWith({ scope: "local" });
  });
});
