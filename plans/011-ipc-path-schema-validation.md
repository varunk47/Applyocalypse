# Plan 011: Validate file paths at the IPC contract boundary (defense-in-depth for localPath inputs)

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 224c6f5..HEAD -- packages/ipc-contracts/src/index.ts packages/ipc-contracts/src/index.test.ts`
> If either changed since this plan was written, compare "Current state"
> excerpts against live code; on a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P3
- **Effort**: S
- **Risk**: LOW (tightens validation; can only reject inputs that were already rejected later in the handler)
- **Depends on**: none
- **Category**: security (defense-in-depth)
- **Planned at**: commit `224c6f5`, 2026-06-11

## Why this matters

Renderer-supplied file paths are validated at runtime by `requirePickedPath`
in the IPC handler layer (absolute, no null bytes, AND must have come through
the app's file picker). That gate is solid. But the Zod contracts that define
the IPC boundary accept any non-empty string for `localPath`, so the
contract — the layer that exists precisely to make renderer↔main traffic
trustworthy by construction — does not express the path rules at all. Adding
the checks to the shared schema fails malicious or buggy inputs at parse time,
keeps the rules in one place, and protects any future handler that forgets to
call `requirePickedPath`.

## Current state

- `packages/ipc-contracts/src/index.ts` — three `localPath` request fields:
  - line 138 (documents ingest request): `localPath: z.string().min(1)`
  - line 234 (filesRegisterUpload request): `localPath: z.string().min(1),`
  - line 239: `filesOpenLocalPath: contract(IpcChannels.filesOpenLocalPath, z.object({ localPath: z.string().min(1) }).strict(), ...)`
  - line 323 is a RESPONSE field (file-picker result) — main-process produced;
    leave it as is.
- The runtime gate being mirrored —
  `apps/desktop/src/main/ipc/registerIpc.ts:~78-94`:
  ```ts
  if (localPath.includes("\0")) { throw new Error("Path contains invalid characters"); }
  if (!isAbsolute(localPath)) { throw new Error("Path must be absolute"); }
  ```
- The contracts package is imported by BOTH main and preload; it currently
  imports only `zod` — keep it dependency-free (do not import `node:path` —
  preload bundling should stay platform-neutral; implement absoluteness as a
  regex instead).
- Tests: `packages/ipc-contracts/src/index.test.ts` — 10 tests parsing valid
  and invalid payloads against contracts; follow its style.

## Commands you will need

| Purpose | Command (repo root) | Expected on success |
|---------|---------------------|---------------------|
| Targeted tests | `pnpm vitest run packages/ipc-contracts/src/index.test.ts` | all pass |
| Typecheck | `pnpm typecheck` | exit 0 |
| Full TS suite | `pnpm test` | exit 0 (handlers still parse picker-produced paths) |

## Scope

**In scope**:
- `packages/ipc-contracts/src/index.ts`
- `packages/ipc-contracts/src/index.test.ts`

**Out of scope** (do NOT touch):
- `registerIpc.ts` — `requirePickedPath` stays; the schema is additional, not a replacement.
- Response schemas (line 323 picker result).
- Any path that the MAIN process generates and parses through response schemas.

## Git workflow

- Commit message: `feat(ipc-contracts): validate localPath shape at the contract boundary`

## Steps

### Step 1: Shared path schema

Near the top of `packages/ipc-contracts/src/index.ts` (after the zod import,
before the contracts), add:

```ts
const WINDOWS_ABSOLUTE = /^[A-Za-z]:[\\/]/;
const POSIX_ABSOLUTE = /^\//;
const UNC_ABSOLUTE = /^\\\\/;

export const AbsoluteLocalPathSchema = z
  .string()
  .min(1)
  .refine((p) => !p.includes("\0"), { message: "Path contains invalid characters" })
  .refine((p) => WINDOWS_ABSOLUTE.test(p) || POSIX_ABSOLUTE.test(p) || UNC_ABSOLUTE.test(p), {
    message: "Path must be absolute"
  });
```

Replace the three REQUEST `localPath: z.string().min(1)` occurrences (lines
138, 234, 239) with `localPath: AbsoluteLocalPathSchema`.

**Verify**: `pnpm typecheck` → exit 0.

### Step 2: Tests

In `packages/ipc-contracts/src/index.test.ts`, following the existing
parse/safeParse test style, add for `filesOpenLocalPath` (representative of
all three):

1. accepts `C:\\Users\\someone\\file.docx` (Windows absolute)
2. accepts `/home/user/file.docx` (POSIX absolute)
3. rejects `..\\..\\secrets.txt` (relative)
4. rejects `docs/resume.docx` (relative)
5. rejects a string containing `\0`

**Verify**: `pnpm vitest run packages/ipc-contracts/src/index.test.ts` → all
pass including 5 new.

### Step 3: Full-suite confirmation

The desktop tests exercise handlers that parse real picked paths through these
contracts — they confirm no legitimate path shape got rejected.

**Verify**: `pnpm test` → exit 0.

## Test plan

Covered in Step 2; Step 3 is the integration regression net.

## Done criteria

- [ ] `grep -c "AbsoluteLocalPathSchema" packages/ipc-contracts/src/index.ts` → 4 (1 definition + 3 uses)
- [ ] `pnpm vitest run packages/ipc-contracts/src/index.test.ts` → all pass
- [ ] `pnpm test` and `pnpm typecheck` exit 0
- [ ] No files outside the in-scope list modified (`git status`)
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report back if:

- More than three request-side `localPath` fields exist now (drift) — apply
  the same replacement to all request-side occurrences and list them in your
  report, but STOP first if any of them is documented as accepting relative
  paths.
- Any existing test legitimately feeds a relative path through a request
  contract (it would mean a real flow depends on relative paths — report it).

## Maintenance notes

- New IPC contracts carrying renderer-supplied paths must use
  `AbsoluteLocalPathSchema` — note this in the contracts file near the schema.
- This is defense-in-depth: `requirePickedPath`'s picker-allowlist check
  remains the primary authorization gate and must not be weakened on the
  strength of this schema.
