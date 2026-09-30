import { shell } from "electron";
import { createServer, type IncomingMessage, type ServerResponse } from "node:http";
import { createClient, type SupabaseClient, type SupportedStorage } from "@supabase/supabase-js";
import type { SettingsRepository } from "@applyocalypse/db";
import { SecureSecretStore } from "./secureSecretStore";

// The publishable key is meant to ship inside client apps; row level security,
// not this key, guards data. No service_role key ever belongs in the app.
const SUPABASE_URL = "https://ebfrytsgefqtwhlvrucp.supabase.co";
const SUPABASE_PUBLISHABLE_KEY = "sb_publishable_L4r3tkKjUkZKtAb4RcAUzA_fgUOZ7yZ";
// Must be listed under Authentication > URL Configuration > Redirect URLs.
export const AUTH_CALLBACK_PORT = 9737;
export const AUTH_CALLBACK_URL = `http://127.0.0.1:${AUTH_CALLBACK_PORT}/auth/callback`;
const GOOGLE_TIMEOUT_MS = 180_000;
const SETTINGS_PREFIX = "auth.supabase.";
const SETTINGS_SUFFIX = ".encrypted";

export type AccountState = {
  signedIn: boolean;
  email: string | null;
};

export type AccountResult = AccountState & {
  ok: boolean;
  message: string;
};

/**
 * Supabase keeps its session (and the PKCE verifier during Google sign-in) in
 * this storage. Each value is safeStorage-encrypted in app_settings, so tokens
 * never sit on disk in plaintext and never cross into the renderer.
 */
export const encryptedSettingsStorage = (
  settings: SettingsRepository,
  store: Pick<SecureSecretStore, "encryptSecret" | "decryptSecret">
): SupportedStorage => ({
  getItem: (key) => {
    const encrypted = settings.get<string>(`${SETTINGS_PREFIX}${key}${SETTINGS_SUFFIX}`, "");
    if (!encrypted) return null;
    try {
      return store.decryptSecret(encrypted);
    } catch {
      return null;
    }
  },
  setItem: (key, value) => {
    settings.set(`${SETTINGS_PREFIX}${key}${SETTINGS_SUFFIX}`, store.encryptSecret(value));
  },
  removeItem: (key) => {
    settings.set(`${SETTINGS_PREFIX}${key}${SETTINGS_SUFFIX}`, "");
  }
});

const signedOut = (message: string): AccountResult => ({ ok: false, signedIn: false, email: null, message });

export class AccountAuthService {
  private readonly client: SupabaseClient;

  constructor(settingsRepository: SettingsRepository, client?: SupabaseClient) {
    this.client =
      client ??
      createClient(SUPABASE_URL, SUPABASE_PUBLISHABLE_KEY, {
        auth: {
          flowType: "pkce",
          storage: encryptedSettingsStorage(settingsRepository, new SecureSecretStore()),
          persistSession: true,
          autoRefreshToken: true,
          detectSessionInUrl: false
        }
      });
  }

  async getState(): Promise<AccountState> {
    const { data } = await this.client.auth.getSession();
    const email = data.session?.user.email ?? null;
    return { signedIn: data.session !== null, email };
  }

  async signUp(email: string, password: string): Promise<AccountResult> {
    const { data, error } = await this.client.auth.signUp({ email, password });
    if (error) return signedOut(error.message);
    if (!data.session) {
      return signedOut("Check your inbox and confirm your email, then sign in here.");
    }
    return { ok: true, signedIn: true, email: data.session.user.email ?? email, message: "Account created." };
  }

  async signIn(email: string, password: string): Promise<AccountResult> {
    const { data, error } = await this.client.auth.signInWithPassword({ email, password });
    if (error) return signedOut(error.message);
    return { ok: true, signedIn: true, email: data.user.email ?? email, message: "Signed in." };
  }

  async signInWithGoogle(): Promise<AccountResult> {
    const { data, error } = await this.client.auth.signInWithOAuth({
      provider: "google",
      options: { redirectTo: AUTH_CALLBACK_URL, skipBrowserRedirect: true }
    });
    if (error || !data.url) return signedOut(error?.message ?? "Google sign-in could not start.");

    const code = await waitForAuthCode(data.url);
    if (!code) return signedOut("Google sign-in timed out or was cancelled.");

    const exchanged = await this.client.auth.exchangeCodeForSession(code);
    if (exchanged.error) return signedOut(exchanged.error.message);
    const email = exchanged.data.user.email ?? null;
    return { ok: true, signedIn: true, email, message: "Signed in with Google." };
  }

  async signOut(): Promise<AccountState> {
    // Local scope clears this device even when the network is down.
    await this.client.auth.signOut({ scope: "local" });
    return { signedIn: false, email: null };
  }
}

const CALLBACK_PAGE = (text: string): string =>
  `<!doctype html><html><body style="font-family:system-ui;padding:48px"><h2>${text}</h2><p>You can close this tab and return to Applyocalypse.</p></body></html>`;

/** Opens the browser at the provider and waits for the loopback redirect's code. */
const waitForAuthCode = async (authUrl: string): Promise<string | null> => {
  let finish!: (code: string | null) => void;
  const codePromise = new Promise<string | null>((resolve) => {
    finish = resolve;
  });

  const server = createServer((req: IncomingMessage, res: ServerResponse) => {
    const url = new URL(req.url ?? "/", AUTH_CALLBACK_URL);
    // Stray local requests (favicons, other tabs) must not end the flow.
    if (url.pathname !== "/auth/callback") {
      res.writeHead(404, { "Content-Type": "text/plain" });
      res.end("Not found");
      return;
    }
    const code = url.searchParams.get("code");
    res.writeHead(200, { "Content-Type": "text/html" });
    res.end(CALLBACK_PAGE(code ? "You are signed in." : "Sign-in was not completed."));
    finish(code);
  });

  await new Promise<void>((resolve, reject) => {
    server.once("error", reject);
    server.listen(AUTH_CALLBACK_PORT, "127.0.0.1", () => resolve());
  });

  const timer = setTimeout(() => finish(null), GOOGLE_TIMEOUT_MS);
  try {
    await shell.openExternal(authUrl);
    return await codePromise;
  } finally {
    clearTimeout(timer);
    server.close();
  }
};
