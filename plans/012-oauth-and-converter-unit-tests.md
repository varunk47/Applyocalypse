# Plan 012: Unit-test the Gmail OAuth service and converter diagnostics (currently zero coverage)

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 224c6f5..HEAD -- apps/desktop/src/main/services/gmailOAuthService.ts apps/desktop/src/main/services/converterDiagnostics.ts`
> Both are source-of-truth for the excerpts below. Small refactors are
> tolerable (re-locate symbols); semantic changes to the OAuth flow are a STOP
> condition.

## Status

- **Priority**: P2
- **Effort**: M
- **Risk**: LOW (tests only; minimal export-surface changes to the source files)
- **Depends on**: none
- **Category**: tests
- **Planned at**: commit `224c6f5`, 2026-06-11

## Why this matters

Two recently added main-process services have no tests at all:

- `gmailOAuthService.ts` — the OAuth loopback flow guarding the user's Gmail
  account: state validation, timeout, token persistence via safeStorage. A
  regression here silently breaks OTP retrieval or, worse, persists tokens
  wrongly.
- `converterDiagnostics.ts` — platform-specific binary discovery driving the
  Settings "Document converters" panel; wrong results misinform users about
  why PDF export fails.

Both are mostly pure logic around two seams (`spawnSync`/`existsSync`, and the
HTTP loopback + fetch) that are cheap to stub.

## Current state

- `apps/desktop/src/main/services/gmailOAuthService.ts` (185 lines):
  - module-private `parseIdTokenEmail(idToken)` (lines 32-43) — base64url JWT
    payload decode, returns `email ?? null`, `null` on garbage. **Not exported.**
  - `GmailOAuthService` class: constructor takes a `SettingsRepository`,
    internally constructs `SecureSecretStore` (line 50).
  - `getStatus()` (54-66): decrypts `gmail.oauth.encryptedToken` setting →
    `{connected, email}`; corrupt token → `{connected: false}`.
  - `disconnect()` (68-70): sets the key to `""`.
  - `getDecryptedTokenJson()` (72-80): null on missing/corrupt.
  - `startOAuthFlow(clientId, clientSecret)` (82-183): random `state`, spins an
    HTTP server on `127.0.0.1:9736`, opens the browser via `shell.openExternal`,
    races a 120s timeout, validates `returnedState === state`, exchanges the
    code via `fetch(GMAIL_TOKEN_URL, ...)`, encrypts + persists the token JSON.
- `apps/desktop/src/main/services/converterDiagnostics.ts` (100 lines, full
  source read at planning time):
  - module-private helpers `findOnPath`, `findLibreOffice`, `findWord`,
    `findTectonic`, `readVersion`; single export `checkConverters()`.
  - Seams: `spawnSync` (node:child_process), `existsSync` (node:fs),
    `process.platform`, `process.env.PROGRAMFILES`.
- Test conventions in this repo: vitest, node environment, tests co-located
  (`*.test.ts` next to the source). `vi.mock` is available. Electron imports
  (`shell`, `safeStorage`) cannot load in plain node — they must be mocked
  with `vi.mock("electron", ...)`. Exemplar for service tests with real temp
  SQLite: `documentIngestionService.test.ts`; exemplar for pure-logic tests:
  `providerRuntimeEnv.test.ts`.
- `SecureSecretStore` (`./secureSecretStore`) wraps Electron `safeStorage` —
  mock the module in OAuth tests.

## Commands you will need

| Purpose | Command (repo root) | Expected on success |
|---------|---------------------|---------------------|
| Targeted | `pnpm vitest run apps/desktop/src/main/services/gmailOAuthService.test.ts apps/desktop/src/main/services/converterDiagnostics.test.ts` | all pass |
| Typecheck | `pnpm typecheck` | exit 0 |
| Full | `pnpm test` | exit 0 |

## Scope

**In scope**:
- `apps/desktop/src/main/services/gmailOAuthService.test.ts` (create)
- `apps/desktop/src/main/services/converterDiagnostics.test.ts` (create)
- `gmailOAuthService.ts` — ONLY to export `parseIdTokenEmail` for testing
  (change `function parseIdTokenEmail` to `export function parseIdTokenEmail`)
- `converterDiagnostics.ts` — no changes expected; if seams prove unmockable
  via `vi.mock` on node builtins, a minimal injectable-deps refactor of the
  helper signatures is allowed (keep `checkConverters()`'s public signature)

**Out of scope** (do NOT touch):
- OAuth flow logic, port, scopes, token shape.
- `secureSecretStore.ts`.
- The Settings UI.

## Git workflow

- Commit message: `test: cover gmail oauth service and converter diagnostics`

## Steps

### Step 1: converterDiagnostics tests

Create `converterDiagnostics.test.ts`. Mock the node builtins at module level:

```ts
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("node:child_process", () => ({ spawnSync: vi.fn() }));
vi.mock("node:fs", () => ({ existsSync: vi.fn() }));

import { spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import { checkConverters } from "./converterDiagnostics";
```

Cases (drive `vi.mocked(spawnSync)` / `vi.mocked(existsSync)` per case;
`beforeEach` resets mocks):

1. all binaries missing → every converter `{available: false, version: null, path: null}` and `installUrl` non-empty.
2. LibreOffice found at the ProgramFiles path (existsSync true for the
   `soffice.exe` candidate) with `spawnSync` returning
   `{status: 0, stdout: "LibreOffice 24.8.0.3 ...multiline"}` for `--version` →
   `available: true`, `version: "LibreOffice 24.8.0.3 ..."` first line only,
   `path` ends with `soffice.exe`.
3. binary on PATH only: existsSync false everywhere, `where`/`which` spawnSync
   returns `{status: 0, stdout: "C:\\tools\\tectonic.exe\r\n"}` → tectonic
   available with trimmed path.
4. `readVersion` resilience: spawnSync for `--version` returns
   `{status: 1, stdout: "", stderr: ""}` → `version: null` but
   `available: true` (presence ≠ version).
5. Word never probes `--version` (its `version` is hardcoded null) — assert
   spawnSync was not called with a WINWORD path.

Platform note: the win32 branches run only when `process.platform === "win32"`.
Tests run on Windows in this repo's CI/dev, but make them platform-independent
where cheap: stub `process.platform` via
`vi.spyOn(process, "platform", "get").mockReturnValue("win32")` if needed
(check whether vitest allows this; otherwise gate the win32-specific
assertions with `it.runIf(process.platform === "win32")`, which the repo's
Windows-first workflow satisfies).

**Verify**: `pnpm vitest run apps/desktop/src/main/services/converterDiagnostics.test.ts` → all pass.

### Step 2: parseIdTokenEmail export + tests

Export `parseIdTokenEmail` from `gmailOAuthService.ts`. In
`gmailOAuthService.test.ts` (with `vi.mock("electron", () => ({ shell: { openExternal: vi.fn() } }))`
and `vi.mock("./secureSecretStore", ...)` returning a stub class with
`encryptSecret: (s) => "enc:" + s`, `decryptSecret: (s) => s.replace(/^enc:/, "")`):

1. valid JWT-ish token: `header.${base64url({"email":"a@b.com"})}.sig` → `"a@b.com"`.
2. payload without email → null.
3. not-a-JWT garbage → null.

### Step 3: GmailOAuthService state/status tests

Same test file. Build a minimal fake `SettingsRepository`
(`{ get: vi.fn(), set: vi.fn() }` cast as needed — check the repository's
method signatures in `packages/db/src/repositories/settingsRepository.ts` and
match them):

1. `getStatus` with empty setting → `{connected: false, email: null}`.
2. `getStatus` with `"enc:" + JSON.stringify({email: "x@y.z"})` →
   `{connected: true, email: "x@y.z"}`.
3. `getStatus` with decrypt throwing (make the stub throw) → `{connected: false}`.
4. `disconnect` → `set(SETTINGS_KEY, "")` called (assert via the fake's mock).
5. `getDecryptedTokenJson` round-trip and corrupt-token null.

### Step 4: startOAuthFlow loopback tests

Highest-value, slightly more setup. The flow's seams: the loopback HTTP server
(real — it binds 127.0.0.1:9736 in-process, a test can hit it with fetch),
`shell.openExternal` (mocked), global `fetch` to Google (stub with
`vi.stubGlobal("fetch", vi.fn())`).

1. `state mismatch is rejected`: start the flow (do not await), wait until
   `shell.openExternal` was called (poll the mock), extract the real `state`
   from the URL it was called with, then
   `await fetch("http://127.0.0.1:9736/?code=abc&state=WRONG")`. The flow
   should resolve `{ok: false}` WITHOUT calling the token endpoint (assert the
   stubbed global fetch was never called with `GMAIL_TOKEN_URL`).
2. `happy path persists encrypted token`: same orchestration with the CORRECT
   state; stub global fetch to return
   `{ok: true, json: async () => ({access_token: "at", refresh_token: "rt", token_type: "Bearer", expires_in: 3600})}`.
   Assert result `{ok: true}` and the fake settings repo received a `set` with
   a value starting `"enc:"` whose decrypted JSON contains
   `refresh_token: "rt"` and the scopes array.
3. Timeout test is OMITTED on purpose (120s constant is not injectable; do not
   refactor for it — note as deferred).

Sequencing caution: each test must let the server close (the service closes it
on first request) before the next starts, or port 9736 collides — run these
serially in one `describe` and `await` the flow promise fully in each test.

**Verify**: `pnpm vitest run apps/desktop/src/main/services/gmailOAuthService.test.ts` → all pass.

## Test plan

This plan IS the test plan: ~5 converter cases + ~8-10 OAuth cases. Full
suite: `pnpm test` → exit 0.

## Done criteria

- [ ] Both new test files exist and pass; `pnpm test` exits 0
- [ ] `startOAuthFlow` state-mismatch and happy-path are covered (grep the test file for `state=WRONG`)
- [ ] No production-logic changes beyond the `parseIdTokenEmail` export keyword
- [ ] `pnpm typecheck` exits 0
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report back if:

- `vi.mock` of `node:child_process`/`node:fs` does not intercept the service's
  calls (ESM hoisting issue) AND the injectable-deps fallback would change
  `checkConverters`'s public signature.
- Binding 127.0.0.1:9736 in tests fails (port already in use in the test
  environment) — report; do not change the service's port handling.
- `SecureSecretStore` is constructed in a way `vi.mock("./secureSecretStore")`
  cannot stub (e.g. re-export indirection) — report the actual import chain.

## Maintenance notes

- When plan 004/005 add cleanup behavior around the OAuth token file, these
  tests are the seam to extend.
- Deferred: making the 120s OAuth timeout injectable for a timeout test;
  origin validation on the loopback callback (audit reviewed and rejected as
  unnecessary — state validation suffices).
- Reviewer should scrutinize: tests must never hit the real Google endpoints
  (global fetch stubbed in every startOAuthFlow test).
