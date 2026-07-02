# Plan 019: Split registerIpc.ts into domain handler modules

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 224c6f5..HEAD -- apps/desktop/src/main/ipc/`
> Plans 006 (settings branch) and others add handlers to registerIpc.ts —
> expected; carry their additions into the split. Re-read the file fully
> before starting.

## Status

- **Priority**: P3
- **Effort**: M
- **Risk**: MED (mechanical, but it is the app's entire IPC surface; the packaged smoke tests are the real net)
- **Depends on**: execute AFTER the other registerIpc-touching plans (006, 011) to avoid conflicts
- **Category**: tech-debt
- **Planned at**: commit `224c6f5`, 2026-06-11

## Why this matters

`registerIpc.ts` is ~700 lines registering ~49 handlers inline in one
function: profile, documents, files, providers, jobs, queue, runs, logs,
screenshots, settings, gmail, system — every domain interleaved with shared
closures (`requirePickedPath`, `approvedPickedPaths`, repositories). Finding a
handler means scrolling; adding one means growing the god function; the
800-line file ceiling (repo convention) is breached. The shape of the fix is
mechanical: keep the shared security closures in one place, move each domain's
handlers into its own module that receives a typed context.

## Current state

- `apps/desktop/src/main/ipc/registerIpc.ts` (~700 lines):
  - One exported `registerIpcHandlers(...)` (find its exact signature — it
    receives db, windows, supervisor, scheduler, theme controller, etc.).
  - Shared closures defined at the top of the function: `normalizeUserPath`,
    `requirePickedPath` (+ `approvedPickedPaths` set), `isKnownArtifactPath`
    (baseline ~78-110), `handleContract` (the typed wrapper binding an
    `IpcContracts` entry to `ipcMain.handle` with Zod parse — read it; every
    extracted module needs it).
  - Repositories instantiated once at function scope (~68-76).
  - Handlers grouped roughly by domain already (settings ~185, providers ~210,
    documents ~237, gmail ~686, system at the end).
- Conventions: services/modules in main are plain modules or classes with
  constructor-injected deps; no DI framework. Tests for IPC behavior run at
  the packaged level (`pnpm test:desktop-user-flow`, `test:desktop-e2e`), not
  as vitest units — vitest covers the services the handlers call.
- The file count target: registerIpc.ts becomes a ~60-line composition root;
  each `ipc/handlers/<domain>.ts` stays under ~150 lines.

## Commands you will need

| Purpose | Command (repo root) | Expected on success |
|---------|---------------------|---------------------|
| Typecheck | `pnpm typecheck` | exit 0 |
| Unit suite | `pnpm test` | exit 0 |
| IPC surface diff | `git grep -o "IpcContracts\.[a-zA-Z]*" -- apps/desktop/src/main/ipc | sort | uniq` before vs after | identical lists |
| Packaged net (slow, once at end) | `pnpm verify:packaged` | exit 0 |

## Scope

**In scope**:
- `apps/desktop/src/main/ipc/registerIpc.ts` (becomes the composition root)
- `apps/desktop/src/main/ipc/handlers/*.ts` (create: `context.ts`,
  `profileHandlers.ts`, `documentHandlers.ts`, `fileHandlers.ts`,
  `providerHandlers.ts`, `jobQueueHandlers.ts`, `runHandlers.ts`,
  `settingsHandlers.ts`, `gmailSystemHandlers.ts` — merge/split pragmatically
  by size, target < 150 lines each)

**Out of scope** (do NOT touch):
- `packages/ipc-contracts` — channels and schemas are frozen.
- Any handler's BODY — pure cut-and-paste moves; zero logic edits. If you
  spot a bug while moving, note it in the report; do not fix it here.
- preload, renderer.

## Git workflow

- Branch suggestion: `refactor/ipc-handlers`
- One commit per extracted domain module (reviewable slices).

## Steps

### Step 1: Capture the IPC surface baseline

`git grep -o "IpcContracts\.[a-zA-Z]*" -- apps/desktop/src/main/ipc | sort -u > /tmp/ipc-before.txt`
(PowerShell: redirect to a temp file). Also record the count of
`handleContract(` + `ipcMain.on(` occurrences.

**Verify**: file captured; counts noted in your report.

### Step 2: Extract the shared context

Create `ipc/handlers/context.ts` exporting an interface + factory:

```ts
export interface IpcHandlerContext {
  db: Database;                       // better-sqlite3
  handleContract: <...>(...) => void; // moved from registerIpc.ts, signature unchanged
  requirePickedPath: (localPath: string) => string;
  normalizeUserPath: (localPath: string) => string;
  isKnownArtifactPath: (localPath: string) => boolean;
  approvePickedPath: (localPath: string) => void;   // wraps approvedPickedPaths.add
  // repositories (the ones currently built at function scope):
  profileRepository: ProfileRepository;
  // ... etc, copy the existing list
  // runtime deps passed into registerIpcHandlers today (windows, supervisor, scheduler, themeController, ...)
}

export const createIpcHandlerContext = (deps: <current registerIpcHandlers params>): IpcHandlerContext => { ... }
```

Move the closure DEFINITIONS verbatim; `approvedPickedPaths` stays private to
this module with `approvePickedPath`/`requirePickedPath` as its only doors
(this preserves the security property: nothing else can whitelist a path).

**Verify**: `pnpm typecheck` → exit 0 (registerIpc.ts now imports from context.ts but still registers everything inline).

### Step 3: Extract one domain per commit

For each domain module: `export const registerXxxHandlers = (ctx: IpcHandlerContext): void => { ... }`
— cut the domain's `handleContract`/`ipcMain.on` blocks from registerIpc.ts
verbatim, paste into the module, replace closure references with `ctx.`.
registerIpc.ts calls each `registerXxxHandlers(ctx)` in the ORIGINAL
registration order (order can matter for `ipcMain.on` listeners — preserve it;
note the original order as comments in the composition root).

After EACH extraction: `pnpm typecheck && pnpm test` green before the next.

**Verify** (each): typecheck + unit suite green.

### Step 4: Surface parity check

Re-run the Step 1 grep into `ipc-after.txt`; diff against before — must be
identical. Counts of `handleContract(`/`ipcMain.on(` across the ipc/ dir must
match the baseline.

**Verify**: zero diff; counts match.

### Step 5: Packaged smoke net

`pnpm verify:packaged` — the user-flow and e2e smokes exercise the real IPC
surface end to end (renderer isolation, approval workflow, queue persistence).

**Verify**: exit 0.

## Test plan

No new unit tests (zero logic change). The verification stack is: typecheck →
unit suite → surface-parity grep → packaged smokes. That last one is the
authoritative gate for this refactor.

## Done criteria

- [ ] registerIpc.ts < 100 lines; every handlers/*.ts < 200 lines
- [ ] IPC surface grep identical before/after; handler counts match
- [ ] `pnpm typecheck`, `pnpm test`, `pnpm verify:packaged` all exit 0
- [ ] `approvedPickedPaths` remains module-private with no new export of the raw Set
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report back if:

- `handleContract`'s typing cannot move without rewriting it (complex generic
  inference) — report; a `// eslint-disable`/`any` shim is NOT acceptable here.
- Any handler turns out to capture per-call mutable state from the outer
  function beyond the documented closures (search for other captured `let`/
  `const` collections before starting; list them).
- `pnpm verify:packaged` fails — bisect by reverting the last extraction
  commit; report which domain broke.

## Maintenance notes

- New IPC handlers go into the matching domain module; the composition root
  should only ever grow by one line per domain.
- Reviewer should scrutinize: the registration ORDER comment vs the original
  file, and that no handler body shows a non-whitespace diff
  (`git diff --color-moved=dimmed-zebra` makes pure moves visible).
