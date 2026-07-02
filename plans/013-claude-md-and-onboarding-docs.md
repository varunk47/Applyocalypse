# Plan 013: Add a repo-root CLAUDE.md and close the onboarding gaps in README

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 224c6f5..HEAD -- README.md`
> and `Test-Path CLAUDE.md` (PowerShell) — if a CLAUDE.md already exists at
> the applyocalypse repo root, reconcile with it instead of overwriting.

## Status

- **Priority**: P2
- **Effort**: M
- **Risk**: LOW (docs only)
- **Depends on**: none (write it against current code; if other plans land first, reflect them)
- **Category**: dx / docs
- **Planned at**: commit `224c6f5`, 2026-06-11

## Why this matters

This repo is developed primarily by coding agents, and there is no repo-root
`CLAUDE.md` — every session re-derives the architecture, the safety
invariants, and the verification commands from scratch (a parent-directory
`C:\Jobs\Codex\CLAUDE.md` exists but contains only generic behavioral
guidance, nothing about this codebase). The README's Development section also
under-documents setup: required tools, the Python env bootstrap, and where
secrets/providers get configured.

## Current state

- No `CLAUDE.md` / `AGENTS.md` in `C:\Jobs\Codex\applyocalypse\` (repo root).
- `README.md` headings: `# Applyocalypse`, `## Development`, `## Verification`,
  `## Current Foundation`, `## Known Production Gaps`.
- No `.env.example` — correct as-is: the app intentionally has no `.env`;
  provider API keys, portal credentials, and the Gmail OAuth client are
  entered in the Settings UI and stored safeStorage-encrypted in SQLite. The
  fix is to SAY that in the README, not to add an env file.
- Facts to encode (verified against the codebase at planning time — re-verify
  anything that plans 001-012 may have changed):
  - Monorepo: pnpm workspaces — `packages/*` (ipc-contracts, shared-schemas,
    shared-types, db, validator, config, ui, document-tools, logging,
    prompt-templates), `apps/desktop` (Electron 42 + SolidJS 1.9 +
    better-sqlite3), `services/automation-python` (Python 3.12 worker,
    PyInstaller-packaged).
  - Toolchain: Node >=22, pnpm >=10 (root package.json engines), Python 3.12,
    on Windows a VS Build Tools toolchain for better-sqlite3 node-gyp builds.
  - Verification: `pnpm verify` (typecheck + vitest + pytest + audits),
    `pnpm verify:packaged` (package + 4 smoke suites), `pnpm test:python`,
    `pnpm dev`.
  - Architecture rules: renderer never touches fs/SQLite/secrets — all
    renderer↔main traffic via Zod contracts in `packages/ipc-contracts`;
    Python worker communicates only via JSON events on stdout ingested by
    `pythonEventIngest.ts`.
  - Safety invariants (these are the section that matters most):
    - No auto-submit without the explicit approval gate.
    - EEO/criminal/previous-employer answers ALWAYS `requires_review=True`.
    - Never log or persist plaintext keys/passwords/OTP codes; secrets are
      safeStorage-encrypted in SQLite settings.
    - No document blobs in SQLite — files on disk, paths + hashes in DB.
    - No em dashes; banned-word list in `packages/validator` (TS) and
      `applyocalypse_automation/validation.py` (Python) stays blocking.
  - Test layout: TS tests co-located `*.test.ts` (vitest, node env); Python
    tests in `services/automation-python/tests` (pytest).
  - Model routing: `LITELLM_MODEL_STRONG` (tailoring) vs `LITELLM_MODEL_FAST`
    (JD analysis), set per-provider in `providerRuntimeEnv.ts`.

## Commands you will need

| Purpose | Command | Expected on success |
|---------|---------|---------------------|
| Sanity | `pnpm verify` | exit 0 (docs must not break anything — this is just the baseline) |

## Scope

**In scope**:
- `CLAUDE.md` (create, repo root `C:\Jobs\Codex\applyocalypse\CLAUDE.md`)
- `README.md` (Development section only)

**Out of scope** (do NOT touch):
- `docs/` content, `plans/`, any source file.
- The parent `C:\Jobs\Codex\CLAUDE.md`.

## Git workflow

- Commit message: `docs: add repo CLAUDE.md and expand development setup in README`

## Steps

### Step 1: Write CLAUDE.md

Create `CLAUDE.md` at the repo root with these sections, in this order, kept
under ~150 lines total (agents load it every session — concision is a
feature). Use the facts from "Current state", but VERIFY each command and path
against the repo before writing it (a wrong doc is worse than none):

1. **What this is** — 2 sentences (local-first desktop copilot for
   human-controlled job applications; Electron + SolidJS + SQLite + Python
   automation worker).
2. **Layout** — one line per workspace package/app/service.
3. **Commands** — table: dev, verify, test, test:python, typecheck,
   desktop:package, verify:packaged, db:migrate. Mark which are slow
   (verify:packaged) and which are the default gate (verify).
4. **Architecture rules** — the IPC-contracts boundary, the stdout-JSON worker
   protocol, where migrations live (`packages/db/migrations`, additive only).
5. **Safety invariants** — the five bullets from Current state, verbatim in
   spirit. State plainly: changes that weaken any of these must be rejected.
6. **Conventions** — TS: strict mode, no console.log in production code,
   co-located vitest tests; Python: type annotations, pytest in tests/,
   table-driven tests preferred (point at `test_answers.py`).
7. **Gotchas** — better-sqlite3 native rebuilds (`pnpm native:rebuild:node`
   for vitest vs `:electron` for the app — tests and app need different ABIs);
   Python venv lives at `services/automation-python/.venv-build` and is
   created by `node scripts/dev/ensure-python-env.mjs`; vite 8 + electron-vite:
   keep `"electron"` in rollupOptions.external (see commit 224c6f5).

**Verify**: every command named in the file exists in root `package.json`
scripts (`grep` each one); every path named exists (`Test-Path`).

### Step 2: Expand README Development section

Extend `## Development` (keep existing content, add what's missing):

- Prerequisites: Node >=22, pnpm >=10 (corepack), Python 3.12 on PATH,
  Windows: Visual Studio Build Tools (C++ workload) for native modules.
- First run: `pnpm install` → `pnpm dev` (auto-bootstraps the Python venv and
  rebuilds native modules).
- Where configuration lives: one short paragraph stating there is no `.env` —
  LLM provider keys, application credentials, and the Gmail OAuth client are
  configured in the app's Settings screen and stored encrypted via Electron
  safeStorage; the only meaningful external env vars are dev overrides
  (`APPLYO_PYTHON` to pick the Python executable — verify this name in
  `scripts/build/build-python-worker.mjs` before writing).
- Pointer: "Agents: read CLAUDE.md first."

**Verify**: `pnpm verify` → exit 0 (nothing functional changed); proofread
that every claim in the diff matches a verifiable fact in the repo.

## Test plan

Not applicable (docs). The verification gates are the command/path existence
checks in Step 1.

## Done criteria

- [ ] `CLAUDE.md` exists at repo root, < ~150 lines, contains the five safety invariants and the verify command table
- [ ] Every command in CLAUDE.md exists in package.json scripts
- [ ] README Development section names prerequisites and states the no-.env settings model
- [ ] `pnpm verify` exits 0
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report back if:

- A `CLAUDE.md` already exists at the applyocalypse root (created since this
  plan) — merge, don't clobber.
- You cannot verify a fact this plan asserts (e.g. `APPLYO_PYTHON` renamed) —
  write what IS true instead, and note the divergence in your report.

## Maintenance notes

- CLAUDE.md should be updated whenever: a new package joins the workspace, a
  verify-pipeline command changes, or a safety invariant is added. Reviewers
  of future PRs should treat invariant edits in CLAUDE.md as red flags.
- Deferred: a dependency-upgrade-cadence note (electron quarterly, vitest on
  majors) can live in CLAUDE.md's Gotchas if the operator wants it.
