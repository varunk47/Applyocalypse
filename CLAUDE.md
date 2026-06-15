# CLAUDE.md

Repo guidance for coding agents. Read this first every session, before exploring.

## What this is

Applyocalypse is a local-first Electron desktop copilot for **human-controlled**
job applications: it tailors documents, fills portals, and supervises browser
automation while keeping the user in the loop. Stack: Electron 42 + SolidJS 1.9
renderer, better-sqlite3 for durable state, and a packaged Python 3.12 worker
that drives the browser and talks back over structured JSON events.

## Layout (pnpm workspaces)

- `apps/desktop` — Electron main + SolidJS renderer + preload (the app).
- `packages/ipc-contracts` — Zod contracts for every renderer↔main channel.
- `packages/shared-schemas` / `packages/shared-types` — domain schemas & types.
- `packages/db` — better-sqlite3, repositories, `migrations/` (additive only).
- `packages/validator` — TS artifact validator (banned words, em-dash gate).
- `packages/document-tools` — DOCX/TEX mutation + diagnostics.
- `packages/config` / `packages/logging` / `packages/prompt-templates` / `packages/ui` — support libs.
- `services/automation-python` — Python worker (browser automation, answers,
  cover-letter, validation); PyInstaller-packaged. Tests in `tests/` (pytest).
  (The other `services/*` dirs are empty placeholders.)

## Commands (run from repo root)

| Command | Purpose | Notes |
|---------|---------|-------|
| `pnpm dev` | Run the app | Bootstraps Python venv + rebuilds native for Electron |
| `pnpm verify` | **Default gate** | typecheck + test + test:python + python:audit + `pnpm audit --audit-level high` |
| `pnpm test` | TS unit tests (vitest) | Rebuilds better-sqlite3 for **Node** ABI first |
| `pnpm test:python` | Python tests (pytest) | |
| `pnpm typecheck` | `tsc --noEmit` across the workspace | |
| `pnpm db:migrate` | Apply DB migrations | |
| `pnpm desktop:package` | Build + package the app (slow) | |
| `pnpm verify:packaged` | Package + 4 packaged smoke suites (slow) | |

## Architecture rules

- The renderer never touches the filesystem, SQLite, or secrets. **All**
  renderer↔main traffic goes through the Zod contracts in
  `packages/ipc-contracts`; new renderer-supplied file paths must use
  `AbsoluteLocalPathSchema`.
- The Python worker communicates **only** via JSON events on stdout, ingested by
  `apps/desktop/src/main/services/pythonEventIngest.ts` (each event is written in
  a single SQLite transaction — keep new DB writes inside it, I/O side effects out).
- Migrations live in `packages/db/migrations` and are **additive only**.

## Safety invariants (reject any change that weakens these)

1. **No auto-submit** without passing the explicit user approval gate.
2. EEO / criminal-history / previous-employer answers are **always**
   `requires_review=True`.
3. Never log or persist plaintext keys, passwords, or OTP codes. Secrets are
   safeStorage-encrypted in SQLite settings; the worker reads them from a 0600
   temp file, never from child-process env.
4. No document blobs in SQLite — files live on disk, only paths + hashes in DB.
5. No em dashes in generated text. The banned-word lists in
   `packages/validator` (TS) and `services/automation-python/.../validation.py`
   (Python) stay **blocking** and must stay in sync (the CL prompt joins the
   Python list programmatically).

## Conventions

- TypeScript: strict mode, no `console.log` in production code, tests co-located
  as `*.test.ts` (vitest, node env). Validate boundaries with Zod.
- Python: type annotations on signatures, pytest in `tests/`, table-driven
  (parametrized) tests preferred — see `tests/test_answers.py`.

## Gotchas

- **Native ABI split**: better-sqlite3 is rebuilt per runtime —
  `pnpm native:rebuild:node` for vitest, `:electron` for the app. `pnpm test`
  and `pnpm dev` handle this for you. Tests and app need different ABIs, so
  `packages/db` deliberately pins better-sqlite3 at `^11` while `apps/desktop`
  uses `^12`; `scripts/dev/rebuild-native.mjs` relies on both versions existing.
- **Python env**: lives at `services/automation-python/.venv-build`, created by
  `node scripts/dev/ensure-python-env.mjs`. Override the host interpreter with
  `APPLYO_PYTHON`.
- **electron-vite**: keep `"electron"` (and `"better-sqlite3"`) in
  `rollupOptions.external` in `apps/desktop/electron.vite.config.ts`.
- **`pnpm verify` audit step**: `pnpm audit --audit-level high` currently flags a
  transitive **esbuild** advisory via the dev toolchain (`tsx`, `vitest > vite`),
  so the audit step is non-zero pending an esbuild/tsx bump. The functional gates
  (typecheck, test, test:python) are green; don't mistake the audit failure for a
  code regression.

## Configuration

There is no `.env`. LLM provider keys, application credentials, and the Gmail
OAuth client are entered in the app's **Settings** screen and stored encrypted
via Electron safeStorage in SQLite. The Python worker receives only runtime env
vars (e.g. `LITELLM_MODEL_STRONG` for tailoring, `LITELLM_MODEL_FAST` for JD
analysis, set per-provider in `providerRuntimeEnv.ts`).
