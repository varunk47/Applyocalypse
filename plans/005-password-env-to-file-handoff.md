# Plan 005: Pass the application password to the Python worker via a mode-0600 temp file instead of an environment variable

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 224c6f5..HEAD -- apps/desktop/src/main/scheduler/localQueueScheduler.ts services/automation-python/applyocalypse_automation/runner.py`
> Plan 004 touches the supervisor (not these files); plans 002/003 touch
> runner.py around line 2300 (not the lines here, ~370-395). Re-confirm the
> excerpts below against live code; unexplained mismatch is a STOP condition.

## Status

- **Priority**: P2
- **Effort**: M
- **Risk**: MED (touches the credential handoff used by live applies; a regression silently disables password autofill)
- **Depends on**: plans/004-run-workdir-secret-cleanup.md (reuses its exit-handler cleanup and janitor sweep for the new file)
- **Category**: security
- **Planned at**: commit `224c6f5`, 2026-06-11

## Why this matters

The decrypted portal password is passed to the spawned Python worker as the
`APPLYO_APPLICATION_PASSWORD` environment variable. On Windows, any process
running as the same user can read another process's environment block; the
password is exposed for the worker's whole lifetime. The codebase already has
a better pattern three lines below: the Gmail OAuth token is handed off as a
mode-0600 file pointed to by an env var. This plan moves the password to the
same pattern. (The OTP IMAP password `APPLYO_GMAIL_OTP_PASSWORD` is included
too — it is the same class of secret in the same code path.)

## Current state

- `apps/desktop/src/main/scheduler/localQueueScheduler.ts:164-200` (inside
  `startClaimedItem`):
  ```ts
  const credentials = profileRepository.getApplicationCredentialReference(item.profileId);
  if (credentials?.applicationEmail && credentials.encryptedReference) {
    const applicationPassword = secureSecretStore.decryptSecret(credentials.encryptedReference);
    providerEnv = {
      ...(providerEnv ?? {}),
      APPLYO_APPLICATION_EMAIL: credentials.applicationEmail,
      APPLYO_APPLICATION_PASSWORD: applicationPassword
    };
    if (credentials.otpHandlingEnabled) {
      // ... OAuth token path (preferred over IMAP app password)
      const tokenFilePath = join(runWorkDir, "gmail-oauth-token.json");
      writeFileSync(tokenFilePath, oauthTokenJson, { encoding: "utf8", mode: 0o600 });
      providerEnv = { ...providerEnv, APPLYO_GMAIL_OAUTH_TOKEN_PATH: tokenFilePath };
      // ... else IMAP fallback:
      providerEnv = {
        ...providerEnv,
        APPLYO_GMAIL_OTP_ENABLED: "1",
        APPLYO_GMAIL_OTP_EMAIL: credentials.applicationEmail,
        APPLYO_GMAIL_OTP_PASSWORD: otpPassword
        // ...
  ```
  (The file-based OAuth handoff is the pattern to replicate.)
- Python consumption — `services/automation-python/applyocalypse_automation/runner.py`:
  ```python
  # runner.py:375
  if is_password_field(field) and os.getenv("APPLYO_APPLICATION_PASSWORD"):
  # runner.py:393
  password = os.getenv("APPLYO_APPLICATION_PASSWORD")
  ```
  Find ALL consumers before changing anything:
  `grep -rn "APPLYO_APPLICATION_PASSWORD\|APPLYO_GMAIL_OTP_PASSWORD" services/automation-python/applyocalypse_automation --include="*.py"`
  (at planning time: runner.py:375,393 for the application password; the OTP
  password is consumed in `otp/` — locate exactly).
- Redaction: `apps/desktop/src/main/services/sensitiveRedaction.ts` redacts
  providerEnv values from supervisor stderr logging — moving secrets out of
  providerEnv must NOT remove them from redaction. Read that file and keep the
  password value flowing into the redaction list even though it is no longer
  in the child env (pass it explicitly if the API allows, or leave the
  redaction input construction unchanged — it is built from values the
  scheduler already has).
- Plan 004 (prerequisite) already deletes `gmail-oauth-token.json` on worker
  exit and sweeps stale run dirs. This plan extends both to the new secrets file.

## Commands you will need

| Purpose | Command (repo root) | Expected on success |
|---------|---------------------|---------------------|
| Typecheck | `pnpm typecheck` | exit 0 |
| TS tests | `pnpm test` | all pass |
| Python tests | `pnpm test:python` | all pass |

## Scope

**In scope**:
- `apps/desktop/src/main/scheduler/localQueueScheduler.ts`
- `apps/desktop/src/main/services/pythonWorkerSupervisor.ts` (extend plan 004's exit cleanup to the new file)
- `services/automation-python/applyocalypse_automation/runner.py` (env reads → file-aware helper)
- Any other Python module consuming `APPLYO_GMAIL_OTP_PASSWORD` (located via the grep above)
- New Python helper + its test file; scheduler test if one exists for this path

**Out of scope** (do NOT touch):
- `secureSecretStore` / safeStorage encryption.
- `APPLYO_APPLICATION_EMAIL` and other non-secret env vars — they stay in env.
- The packaged-app smoke tests (`scripts/test/desktop-*.mjs`) — if they assert
  on env vars, STOP instead (see STOP conditions).

## Git workflow

- Commit message: `fix(security): hand off application/OTP passwords via 0600 file, not child env`

## Steps

### Step 1: Python-side file-aware secret accessor (backward compatible)

Create `services/automation-python/applyocalypse_automation/secret_env.py`:

```python
"""Read worker secrets from an env-pointed file, falling back to plain env vars."""
from __future__ import annotations

import json
import os
from functools import lru_cache


@lru_cache(maxsize=1)
def _secrets_from_file() -> dict[str, str]:
    path = os.getenv("APPLYO_SECRETS_FILE", "")
    if not path:
        return {}
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        return {str(k): str(v) for k, v in data.items()} if isinstance(data, dict) else {}
    except OSError, ValueError:
        return {}


def get_secret(name: str) -> str | None:
    value = _secrets_from_file().get(name)
    if value:
        return value
    return os.getenv(name) or None
```

NOTE the except clause above must be written as `except (OSError, ValueError):`
— fix the tuple syntax when writing the file.

Replace every `os.getenv("APPLYO_APPLICATION_PASSWORD")` and
`os.getenv("APPLYO_GMAIL_OTP_PASSWORD")` consumer found by the grep with
`get_secret("...")`. Keep boolean flags like `APPLYO_GMAIL_OTP_ENABLED` on
plain `os.getenv`.

**Verify**: `pnpm test:python` → green (fallback path keeps current behavior).

### Step 2: Scheduler writes the secrets file

In `localQueueScheduler.ts`, where `APPLYO_APPLICATION_PASSWORD` (and, in the
IMAP fallback, `APPLYO_GMAIL_OTP_PASSWORD`) are added to `providerEnv`:
instead collect them into a local `secretPayload: Record<string, string>`.
After the credentials block, if `secretPayload` is non-empty:

```ts
const secretsFilePath = join(runWorkDir, "worker-secrets.json");
writeFileSync(secretsFilePath, JSON.stringify(secretPayload), { encoding: "utf8", mode: 0o600 });
providerEnv = { ...(providerEnv ?? {}), APPLYO_SECRETS_FILE: secretsFilePath };
```

Mirror the existing OAuth-token write style (excerpt in Current state). The
password values must no longer appear in `providerEnv`. Confirm redaction
still covers them (see Current state note); if `redactSensitiveSupervisorText`
derives its needles from providerEnv values, extend its inputs so the password
is still redacted from stderr persistence.

**Verify**: `pnpm typecheck` → exit 0; `pnpm test` → green.

### Step 3: Cleanup on exit + sweep

In `pythonWorkerSupervisor.ts`, extend plan 004's exit-handler deletion to also
remove `worker-secrets.json`:

```ts
rmSync(join(input.workDir, "worker-secrets.json"), { force: true });
```

(Plan 004's janitor sweep already covers stale dirs wholesale — no change there.)

**Verify**: `pnpm typecheck` → exit 0.

### Step 4: Tests

1. Python — create `services/automation-python/tests/test_secret_env.py`:
   - file present and key present → file value wins over env;
   - `APPLYO_SECRETS_FILE` unset → env fallback returned;
   - file path set but file missing/corrupt JSON → env fallback, no raise;
   - cache note: call `_secrets_from_file.cache_clear()` in a fixture between
     tests (lru_cache persists across tests otherwise).
   Use `monkeypatch.setenv` / `tmp_path` (pattern: any existing test using
   `monkeypatch`, e.g. `tests/test_portal_replay_fixtures.py`).
2. TS — if `localQueueScheduler.test.ts` covers `startClaimedItem`'s env
   construction, add/extend a case asserting `APPLYO_APPLICATION_PASSWORD` is
   ABSENT from the supervisor-start env and `APPLYO_SECRETS_FILE` points to an
   existing file containing the password key. If the existing test does not
   reach this path (it may not construct credentials), skip the TS test and
   note it in the commit message rather than building new scaffolding.

**Verify**: `pnpm test:python` → green incl. new tests; `pnpm test` → green.

## Test plan

Covered in Step 4. End-to-end behavior (worker actually reading the file
during a live apply) is only verifiable via a live run — out of scope; the
unit seams (file write on one side, `get_secret` on the other) are the
verification surface.

## Done criteria

- [ ] `grep -rn "APPLYO_APPLICATION_PASSWORD" apps/desktop/src/main/scheduler/localQueueScheduler.ts` → no match adding it to providerEnv (the string may remain as a secretPayload key)
- [ ] `grep -rn "os.getenv(\"APPLYO_APPLICATION_PASSWORD\")" services/automation-python/applyocalypse_automation` → no matches (all consumers use `get_secret`)
- [ ] `pnpm typecheck`, `pnpm test`, `pnpm test:python` all exit 0
- [ ] worker-secrets.json removed on worker exit (code-reviewed in supervisor exit handler)
- [ ] No files outside the in-scope list modified (`git status`)
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report back if:

- Plan 004 is not DONE (this plan extends its cleanup hook).
- The grep in Current state reveals consumers of the password env vars outside
  `services/automation-python/applyocalypse_automation/` (e.g. smoke-test
  scripts asserting on env) — report the list instead of changing them.
- `redactSensitiveSupervisorText`'s redaction inputs cannot be preserved
  without the password in providerEnv (i.e., redaction would regress) — the
  invariant "never log passwords" outranks this refactor.
- The worker spawn path sets `env` from something other than providerEnv.

## Maintenance notes

- Future secrets (new providers) should go into `worker-secrets.json` via the
  same `secretPayload`, not new env vars.
- Reviewer should scrutinize: redaction coverage (stderr persistence must
  still mask the password) and that the IMAP fallback branch still works when
  only the OTP password moves to the file.
- Deferred: the LLM provider API key in providerEnv (set by
  `buildProviderRuntimeEnv`) could move to the same file later; left out to
  keep this diff reviewable, and litellm reads env vars natively.
