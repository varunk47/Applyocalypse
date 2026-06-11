import { shell } from "electron";
import { createServer, type IncomingMessage, type ServerResponse } from "node:http";
import { randomBytes } from "node:crypto";
import { SecureSecretStore } from "./secureSecretStore";
import type { SettingsRepository } from "@applyocalypse/db";

const GMAIL_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth";
const GMAIL_TOKEN_URL = "https://oauth2.googleapis.com/token";
const GMAIL_SCOPE = "https://www.googleapis.com/auth/gmail.readonly";
const SETTINGS_KEY = "gmail.oauth.encryptedToken";
const LOOPBACK_PORT = 9736;

export type GmailOAuthStatus = {
  connected: boolean;
  email: string | null;
};

export type GmailOAuthStartResult = {
  ok: boolean;
  message: string;
  email: string | null;
};

type TokenResponse = {
  access_token: string;
  refresh_token?: string;
  token_type: string;
  expires_in: number;
  id_token?: string;
};

function parseIdTokenEmail(idToken: string): string | null {
  try {
    const parts = idToken.split(".");
    if (parts.length < 2) return null;
    const payload = JSON.parse(Buffer.from(parts[1]!, "base64url").toString("utf-8")) as {
      email?: string;
    };
    return payload.email ?? null;
  } catch {
    return null;
  }
}

export class GmailOAuthService {
  private readonly secureStore: SecureSecretStore;
  private readonly settingsRepository: SettingsRepository;

  constructor(settingsRepository: SettingsRepository) {
    this.secureStore = new SecureSecretStore();
    this.settingsRepository = settingsRepository;
  }

  getStatus(): GmailOAuthStatus {
    const encryptedToken = this.settingsRepository.get<string>(SETTINGS_KEY, "");
    if (!encryptedToken) {
      return { connected: false, email: null };
    }
    try {
      const tokenJson = this.secureStore.decryptSecret(encryptedToken);
      const token = JSON.parse(tokenJson) as { email?: string };
      return { connected: true, email: token.email ?? null };
    } catch {
      return { connected: false, email: null };
    }
  }

  disconnect(): void {
    this.settingsRepository.set(SETTINGS_KEY, "");
  }

  getDecryptedTokenJson(): string | null {
    const encryptedToken = this.settingsRepository.get<string>(SETTINGS_KEY, "");
    if (!encryptedToken) return null;
    try {
      return this.secureStore.decryptSecret(encryptedToken);
    } catch {
      return null;
    }
  }

  async startOAuthFlow(clientId: string, clientSecret: string): Promise<GmailOAuthStartResult> {
    const state = randomBytes(16).toString("hex");
    const redirectUri = `http://localhost:${LOOPBACK_PORT}`;

    const authParams = new URLSearchParams({
      client_id: clientId,
      redirect_uri: redirectUri,
      response_type: "code",
      scope: `${GMAIL_SCOPE} openid email`,
      access_type: "offline",
      prompt: "consent",
      state,
    });

    const authUrl = `${GMAIL_AUTH_URL}?${authParams.toString()}`;

    let resolveCallback!: (code: string | null) => void;
    const codePromise = new Promise<string | null>((resolve) => {
      resolveCallback = resolve;
    });

    const server = createServer((req: IncomingMessage, res: ServerResponse) => {
      const url = new URL(req.url ?? "/", `http://localhost:${LOOPBACK_PORT}`);
      const code = url.searchParams.get("code");
      const returnedState = url.searchParams.get("state");

      res.writeHead(200, { "Content-Type": "text/html" });
      res.end(
        "<html><body><h2>Gmail connected. You can close this tab.</h2></body></html>"
      );
      server.close();

      if (returnedState === state && code) {
        resolveCallback(code);
      } else {
        resolveCallback(null);
      }
    });

    await new Promise<void>((resolve, reject) => {
      server.listen(LOOPBACK_PORT, "127.0.0.1", () => resolve());
      server.on("error", reject);
    });

    await shell.openExternal(authUrl);

    const timeoutMs = 120_000;
    const code = await Promise.race([
      codePromise,
      new Promise<null>((resolve) => setTimeout(() => resolve(null), timeoutMs)),
    ]);

    if (!code) {
      server.close();
      return { ok: false, message: "OAuth flow timed out or was cancelled", email: null };
    }

    try {
      const body = new URLSearchParams({
        code,
        client_id: clientId,
        client_secret: clientSecret,
        redirect_uri: redirectUri,
        grant_type: "authorization_code",
      });

      const tokenRes = await fetch(GMAIL_TOKEN_URL, {
        method: "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        body: body.toString(),
      });

      if (!tokenRes.ok) {
        return {
          ok: false,
          message: `Token exchange failed: ${tokenRes.status} ${tokenRes.statusText}`,
          email: null,
        };
      }

      const tokenData = (await tokenRes.json()) as TokenResponse;
      const email = tokenData.id_token ? parseIdTokenEmail(tokenData.id_token) : null;

      const tokenJson = JSON.stringify({
        token: tokenData.access_token,
        refresh_token: tokenData.refresh_token ?? "",
        token_uri: GMAIL_TOKEN_URL,
        client_id: clientId,
        client_secret: clientSecret,
        scopes: [GMAIL_SCOPE],
        email,
      });

      const encrypted = this.secureStore.encryptSecret(tokenJson);
      this.settingsRepository.set(SETTINGS_KEY, encrypted);

      return { ok: true, message: "Gmail OAuth connected", email };
    } catch (err) {
      const message = err instanceof Error ? err.message : "OAuth token exchange failed";
      return { ok: false, message, email: null };
    }
  }
}
