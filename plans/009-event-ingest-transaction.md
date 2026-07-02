# Plan 009: Make Python event ingestion atomic with a single SQLite transaction per event

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 224c6f5..HEAD -- apps/desktop/src/main/services/pythonEventIngest.ts apps/desktop/src/main/services/pythonEventIngest.test.ts`
> If either file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: LOW (better-sqlite3 transactions are synchronous; the function is already synchronous throughout)
- **Depends on**: none
- **Category**: bug (atomicity) with a perf side benefit
- **Planned at**: commit `224c6f5`, 2026-06-11

## Why this matters

`ingestPythonEventLine` is the single writer that turns each worker event into
SQLite state: a `run_events` row, plus (depending on event type) application
steps, OTP sessions, screenshots, browser artifacts, generated files,
validation reports, run-status updates, and queue-item updates — 6+ separate
`.prepare().run()` calls with **no transaction**. If the process crashes or a
later statement throws mid-event (e.g. an artifact path fails validation), the
database is left with partial state: a `run_events` row whose corresponding
status/queue updates never landed. Wrapping the writes in one
`db.transaction()` makes each event all-or-nothing and, as a bonus, batches
the fsync cost (events arrive ~1-2/sec during runs).

## Current state

- `apps/desktop/src/main/services/pythonEventIngest.ts` (845 lines):
  - Single exported entry point at line 424:
    ```ts
    export const ingestPythonEventLine = ({ db, windows, rawLine, safeArtifactRoots }: PythonEventIngestInput): void => {
      const event = PythonWorkerEventSchema.parse(JSON.parse(rawLine));
      ...
      db.prepare(`INSERT INTO run_events (...)`).run({...});           // line 430
      const materializedStepId = materializeApplicationStep(db, event); // line 454
      persistOtpSessionEvent(db, event);                                // line 455
      if (event.event_type === "SCREENSHOT_CAPTURED") { ...insert... }  // line 457
      if (event.event_type === "BROWSER_ARTIFACT_CAPTURED") { ... }     // line 494
      ...many more conditional writes through ~line 787...
      const safeEvent = SafeRendererRunEventSchema.parse({...});        // line 789
      for (const window of windows()) {                                 // line 800
        window.webContents.send(IpcChannels.logsEvent, safeEvent);      // line 802
      }
    };
    ```
  - Everything between the Zod parse (line 425) and the `safeEvent`
    construction (line 789) is synchronous DB work plus filesystem checks
    (`existsSync`/`statSync`/hashing for artifacts). No `await` anywhere in
    the function (it returns `void`).
  - The renderer broadcast (lines 789-804) must remain OUTSIDE the
    transaction — UI must only learn about state that committed.
- Caller — `pythonWorkerSupervisor.ts:77`: invoked per stdout line; a throw is
  caught upstream and persisted as a supervisor error (verify: see the
  try/catch around the call in the supervisor's stdout handler).
- better-sqlite3 transaction API: `const txn = db.transaction((args) => {...});
  txn(args);` — re-entrant calls and exceptions roll back automatically.
- Tests: `apps/desktop/src/main/services/pythonEventIngest.test.ts` — 20 tests
  feeding `rawLine` JSON through the real function against a real temp SQLite
  database. This is the regression net; it must stay green untouched.

## Commands you will need

| Purpose | Command (repo root) | Expected on success |
|---------|---------------------|---------------------|
| Targeted tests | `pnpm vitest run apps/desktop/src/main/services/pythonEventIngest.test.ts` | 20+ pass |
| Typecheck | `pnpm typecheck` | exit 0 |
| Full TS suite | `pnpm test` | exit 0 |

## Scope

**In scope**:
- `apps/desktop/src/main/services/pythonEventIngest.ts` (the entry function's structure only — no logic changes inside the helpers)
- `apps/desktop/src/main/services/pythonEventIngest.test.ts` (one new test)

**Out of scope** (do NOT touch):
- Any SQL statement text, helper function (`materializeApplicationStep`,
  `persistOtpSessionEvent`, etc.), or schema.
- The supervisor caller.
- The renderer broadcast shape (`SafeRendererRunEventSchema`).

## Git workflow

- Commit message: `fix: wrap per-event ingest writes in a single SQLite transaction`

## Steps

### Step 1: Restructure the entry point

In `pythonEventIngest.ts`, refactor `ingestPythonEventLine` to:

```ts
export const ingestPythonEventLine = ({ db, windows, rawLine, safeArtifactRoots }: PythonEventIngestInput): void => {
  const event = PythonWorkerEventSchema.parse(JSON.parse(rawLine));

  const applyEvent = db.transaction(() => {
    // EVERYTHING that was previously between the parse and the safeEvent
    // construction moves here, unchanged: the run_events insert,
    // materializeApplicationStep, persistOtpSessionEvent, all the
    // event-type-conditional blocks, status/queue updates.
  });
  applyEvent();

  const safeEvent = SafeRendererRunEventSchema.parse({ ... });  // unchanged
  for (const window of windows()) { ... }                        // unchanged
};
```

Mechanical move — cut lines ~426-787 into the transaction body verbatim. Two
checks while moving:

1. Confirm no `await`/Promise appears in the moved block (`grep -n "await" `
   on the file; at planning time there are none inside the function).
   better-sqlite3 transactions must be fully synchronous.
2. The filesystem validations (existsSync/statSync/hash) throwing inside the
   transaction is CORRECT — the rollback is the point: no `run_events` row
   for an event whose artifact failed validation. Note this behavior change:
   today a bad artifact event leaves the `run_events` row behind; after this
   plan it does not. Scan the test file for any test asserting that partial
   state and update its expectation if found (check before assuming).

**Verify**: `pnpm typecheck` → exit 0; `pnpm vitest run apps/desktop/src/main/services/pythonEventIngest.test.ts` → all pass (subject to the partial-state check in point 2).

### Step 2: Add the atomicity regression test

In `pythonEventIngest.test.ts`, add one test following the file's existing
setup pattern (temp SQLite db, migrations, feed a rawLine):

`rolls back the run_events row when a later write in the same event fails` —
feed a `SCREENSHOT_CAPTURED` event whose `local_path` points outside the safe
roots (the existing tests show how safe roots are configured; an out-of-root
path makes `normalizeSafeArtifactPath` throw). Assert:
- the call throws, AND
- `SELECT COUNT(*) FROM run_events WHERE application_run_id = ?` returns the
  same count as before the call (the insert rolled back).

**Verify**: targeted vitest run → all pass including the new test.

## Test plan

Covered in Step 2; the existing 20 tests are the behavioral regression net.
Full suite: `pnpm test` → exit 0.

## Done criteria

- [ ] `pnpm typecheck` exits 0
- [ ] `pnpm test` exits 0 including the new rollback test
- [ ] `grep -n "db.transaction" apps/desktop/src/main/services/pythonEventIngest.ts` → exactly one match inside `ingestPythonEventLine`
- [ ] Renderer broadcast remains outside the transaction (code review)
- [ ] No files outside the in-scope list modified (`git status`)
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report back if:

- The function body has gained an `await` or any async callback between lines
  426-787 (transactions cannot span async work — report, don't restructure).
- Any existing test depends on partial writes surviving a mid-event throw and
  the new rollback semantics would change user-visible behavior beyond the
  screenshot/artifact validation path (list the affected tests and stop).
- `db.transaction` is unavailable on the injected `db` type (it should be the
  better-sqlite3 `Database` — check `PythonEventIngestInput`).

## Maintenance notes

- Future event handlers added to this function must go INSIDE the transaction
  if they write to SQLite, OUTSIDE if they do I/O with side effects beyond the
  DB (e.g. network). Note this in the function's doc comment.
- Reviewer should scrutinize: nothing inside the transaction emits IPC or
  touches `windows()`, and the moved block is byte-identical except for
  indentation.
