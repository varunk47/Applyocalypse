# Plan 004: Delete the plaintext Gmail OAuth token file when a run's worker exits, and sweep stale run work directories on startup

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 224c6f5..HEAD -- apps/desktop/src/main/services/pythonWorkerSupervisor.ts apps/desktop/src/main/scheduler/localQueueScheduler.ts apps/desktop/src/main/index.ts`
> If any in-scope file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: LOW (cleanup logic only; worst failure mode is a file not deleted, which is today's behavior)
- **Depends on**: none
- **Category**: security
- **Planned at**: commit `224c6f5`, 2026-06-11

## Why this matters

When OTP handling is enabled, the scheduler decrypts the safeStorage-encrypted
Gmail OAuth token and writes it as **plaintext JSON** to the run's work
directory so the Python worker can read it. That JSON contains the Gmail
**refresh token, client_id, and client_secret**. Nothing ever deletes it: the
`GeneratedFileCleanupService` only deletes files registered in the database,
and run work dirs are never registered. Every OTP-enabled run leaves a
long-lived Gmail credential on disk in `userData/runs/<runId>/`, silently
defeating the encryption-at-rest design. The work dirs also accumulate the
full canonical profile and job data forever, with no retention policy.

This plan: (1) deletes the token file the moment the worker process exits,
(2) sweeps run work dirs older than a retention window at app startup.

## Current state

- `apps/desktop/src/main/scheduler/localQueueScheduler.ts:115-116` — work dir
  creation:
  ```ts
  const runWorkDir = join(app.getPath("userData"), "runs", runId);
  mkdirSync(runWorkDir, { recursive: true });
  ```
- `localQueueScheduler.ts:173-184` — the token file write (inside
  `startClaimedItem`, when `credentials.otpHandlingEnabled`):
  ```ts
  const oauthTokenJson = gmailOAuthService.getDecryptedTokenJson();
  if (oauthTokenJson) {
    const tokenFilePath = join(runWorkDir, "gmail-oauth-token.json");
    writeFileSync(tokenFilePath, oauthTokenJson, { encoding: "utf8", mode: 0o600 });
    providerEnv = { ...providerEnv, APPLYO_GMAIL_OAUTH_TOKEN_PATH: tokenFilePath };
  }
  ```
- The scheduler hands off to the supervisor with the work dir
  (`localQueueScheduler.ts:243`: `workDir: runWorkDir` inside the
  `supervisor.start({...})` input).
- `apps/desktop/src/main/services/pythonWorkerSupervisor.ts`:
  - `StartWorkerInput` type has `workDir: string` (line 21).
  - `start(input: StartWorkerInput): void` (line 41) spawns the child and
    registers the exit handler (lines 87-94):
    ```ts
    child.on("exit", (code: number | null, signal: NodeJS.Signals | null) => {
      const activeWorker = this.active.get(input.runId);
      clearInterval(activeWorker?.heartbeat ?? heartbeat);
      this.active.delete(input.runId);
      if (!activeWorker?.stopping) {
        this.pauseRunAfterUnexpectedWorkerExit(input.runId, code, signal);
      }
    });
    ```
- `apps/desktop/src/main/index.ts:59` — startup wiring exemplar (the cleanup
  service is constructed here; follow the same pattern for the new sweep):
  ```ts
  const cleanupService = new GeneratedFileCleanupService(database, getSafeArtifactRoots);
  ```
- Test exemplar: `apps/desktop/src/main/services/generatedFileCleanupService.test.ts`
  — builds a temp dir structure and asserts deletion respects safe roots.
  Tests run with vitest, node environment.
- Repo conventions: services are classes in
  `apps/desktop/src/main/services/`, constructor-injected dependencies,
  no console.log (errors persisted via repositories or rethrown).

## Commands you will need

| Purpose | Command (repo root) | Expected on success |
|---------|---------------------|---------------------|
| Typecheck | `pnpm typecheck` | exit 0 |
| Targeted tests | `pnpm vitest run apps/desktop/src/main/services/runWorkDirJanitor.test.ts` | all pass |
| Full TS suite | `pnpm test` | 142+ passed, exit 0 |

## Scope

**In scope**:
- `apps/desktop/src/main/services/pythonWorkerSupervisor.ts` (exit handler only)
- `apps/desktop/src/main/services/runWorkDirJanitor.ts` (create)
- `apps/desktop/src/main/services/runWorkDirJanitor.test.ts` (create)
- `apps/desktop/src/main/index.ts` (startup wiring, a few lines)

**Out of scope** (do NOT touch):
- `localQueueScheduler.ts` — the token write stays as is (the worker needs the file).
- `generatedFileCleanupService.ts` — DB-registered artifact cleanup is a different concern.
- `gmailOAuthService.ts` — encrypted storage is correct; do not change token contents (the Python google-auth refresh flow requires client_id/client_secret/token_uri in the JSON).
- The Python worker.

## Git workflow

- Commit message: `fix(security): delete plaintext oauth token on worker exit; sweep stale run work dirs`

## Steps

### Step 1: Delete the token file on worker exit

In `pythonWorkerSupervisor.ts`, inside the existing `child.on("exit", ...)`
handler (excerpt above), add — before the `pauseRunAfterUnexpectedWorkerExit`
branch — a best-effort deletion:

```ts
try {
  rmSync(join(input.workDir, "gmail-oauth-token.json"), { force: true });
} catch {
  // best-effort: never let cleanup failure mask the exit handling
}
```

Add `rmSync` and `join` to the existing `node:fs` / `node:path` imports at the
top of the file (check what is already imported and extend, do not duplicate).
`force: true` makes the call a no-op when the file does not exist (runs
without OTP), so no existence check is needed.

**Verify**: `pnpm typecheck` → exit 0. `pnpm vitest run apps/desktop/src/main/services/pythonWorkerSupervisor.test.ts` → existing 5 tests still pass.

### Step 2: Create the startup janitor

Create `apps/desktop/src/main/services/runWorkDirJanitor.ts`:

```ts
import { readdirSync, rmSync, statSync } from "node:fs";
import { join } from "node:path";

const DEFAULT_RETENTION_DAYS = 7;

export const sweepStaleRunWorkDirs = (
  runsRoot: string,
  options: { retentionDays?: number; activeRunIds?: ReadonlySet<string>; now?: number } = {}
): string[] => {
  const retentionMs = (options.retentionDays ?? DEFAULT_RETENTION_DAYS) * 24 * 60 * 60 * 1000;
  const now = options.now ?? Date.now();
  const removed: string[] = [];
  let entries: string[];
  try {
    entries = readdirSync(runsRoot);
  } catch {
    return removed; // runs/ does not exist yet
  }
  for (const entry of entries) {
    if (options.activeRunIds?.has(entry)) continue;
    const dirPath = join(runsRoot, entry);
    try {
      const stats = statSync(dirPath);
      if (!stats.isDirectory()) continue;
      if (now - stats.mtimeMs > retentionMs) {
        rmSync(dirPath, { recursive: true, force: true });
        removed.push(entry);
      }
    } catch {
      // skip entries we cannot stat/remove
    }
  }
  return removed;
};
```

This is a pure function (no class needed — it has no state), matching the
style of small helpers elsewhere; keep it under 60 lines.

**Verify**: `pnpm typecheck` → exit 0.

### Step 3: Wire the sweep at startup

In `apps/desktop/src/main/index.ts`, after the database and scheduler are
constructed (near the `GeneratedFileCleanupService` construction at line ~59),
add:

```ts
sweepStaleRunWorkDirs(join(app.getPath("userData"), "runs"));
```

with the import added at the top. Do not pass `activeRunIds` here — at app
startup no workers are running yet. Wrap in try/catch only if the surrounding
startup code follows that pattern (check the neighboring lines and match).

**Verify**: `pnpm typecheck` → exit 0.

### Step 4: Tests

Create `apps/desktop/src/main/services/runWorkDirJanitor.test.ts`, modeled
structurally on `generatedFileCleanupService.test.ts` (temp dirs via
`mkdtempSync(join(tmpdir(), ...))`, cleanup in `afterEach`):

1. `deletes run dirs older than retention` — create `runs/old-run/file.txt`,
   set `now` option to `Date.now() + 8 days` (avoids needing utimes), assert
   the dir is gone and the return value lists `old-run`.
2. `keeps run dirs newer than retention` — same setup, `now` = +1 day →
   dir still exists.
3. `skips active run ids` — old dir but `activeRunIds: new Set(["old-run"])` →
   dir still exists.
4. `returns empty when runs root missing` — nonexistent path → `[]`, no throw.

**Verify**: `pnpm vitest run apps/desktop/src/main/services/runWorkDirJanitor.test.ts` → 4 passed.

## Test plan

Covered in Step 4. The Step 1 exit-handler deletion is covered indirectly: the
existing supervisor lifecycle test spawns real short-lived processes — confirm
it still passes; if it is cheap to extend (a `workDir` temp dir with a dummy
`gmail-oauth-token.json` asserted gone after exit), add that one assertion to
the existing test rather than building new spawn scaffolding.

Full verification: `pnpm test` → exit 0 with 4+ new tests.

## Done criteria

- [ ] `pnpm typecheck` exits 0
- [ ] `pnpm test` exits 0; the 4 janitor tests pass
- [ ] `grep -n "gmail-oauth-token.json" apps/desktop/src/main/services/pythonWorkerSupervisor.ts` → one match inside the exit handler
- [ ] `grep -n "sweepStaleRunWorkDirs" apps/desktop/src/main/index.ts` → one call
- [ ] No files outside the in-scope list modified (`git status`)
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report back if:

- The supervisor exit handler no longer matches the excerpt (drift).
- `StartWorkerInput` no longer carries `workDir`.
- The Python worker reads the token file at a time other than during the run
  (search `APPLYO_GMAIL_OAUTH_TOKEN_PATH` in `services/automation-python/` —
  it must only be read by the in-run OTP extractor `otp/gmail_mcp.py:284`; if
  any post-exit reader exists, deletion-on-exit would break it).
- Startup wiring in `index.ts` has been restructured so there is no obvious
  post-database-init insertion point.

## Maintenance notes

- If a "retention days" user setting is added later, thread it through the
  `retentionDays` option — the function signature already supports it.
- If runs ever resume across app restarts with the same work dir, the startup
  sweep's mtime window (7 days) is the safety margin; revisit if long-paused
  runs become a feature.
- Reviewer should scrutinize: deletion must be best-effort (never throw out of
  the exit handler) and the sweep must never follow the path outside
  `userData/runs` (it joins fixed segments; no user input involved).
- Deferred: encrypting `canonical-profile.json` in the work dir at rest
  (adds key-management complexity to the worker; revisit if threat model
  changes).
