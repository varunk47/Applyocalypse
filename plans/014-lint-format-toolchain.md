# Plan 014: Add a lint/format toolchain (eslint + prettier for TS, ruff for Python) wired into verify

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 224c6f5..HEAD -- package.json apps/desktop/package.json`
> Plans 010/015/016 also touch package.json — additive changes are fine;
> re-read the scripts block before editing.

## Status

- **Priority**: P3
- **Effort**: M
- **Risk**: LOW (report-only first; autofix is a separate, reviewable commit)
- **Depends on**: none
- **Category**: dx
- **Planned at**: commit `224c6f5`, 2026-06-11

## Why this matters

The repo's only "lint" is `tsc --noEmit` (the package `lint` scripts literally
alias typecheck). There is no style/correctness linting for TS (unused vars,
floating promises, accidental `any` growth) and nothing at all for the ~10k
lines of Python, where `runner.py` is high-churn and agent-edited. Agents
match local style well but drift without an enforcement loop; a linter also
catches real bug classes (unawaited promises in main-process code) that
typecheck does not.

## Current state

- Root `package.json` scripts: `"lint": "pnpm -r lint"`; each package's `lint`
  is `tsc -p tsconfig.json --noEmit` (e.g. `apps/desktop/package.json:16`).
- `"verify": "pnpm typecheck && pnpm test && pnpm test:python && pnpm python:audit && pnpm audit --audit-level high"`.
- No eslint/prettier/ruff config anywhere
  (`Get-ChildItem -Recurse -Include .eslintrc*,eslint.config.*,.prettierrc*,ruff.toml,pyproject.toml -Depth 2`
  → empty at planning time; re-verify).
- TS: TypeScript ^5.8, ESM modules, vitest. SolidJS renderer (NOT React — do
  not add react lint plugins; use `eslint-plugin-solid` if available, or skip
  JSX-specific linting).
- Python: 3.12, no pyproject.toml in `services/automation-python` (deps via
  requirements.txt; tests via pytest).
- Python test runner pattern to copy for a ruff runner script:
  `scripts/test/python-tests.mjs` (spawns `.venv-build` python with
  `-m pytest`).

## Commands you will need

| Purpose | Command (repo root) | Expected on success |
|---------|---------------------|---------------------|
| Lint TS | `pnpm lint:js` (new) | exit 0 |
| Lint Python | `pnpm lint:python` (new) | exit 0 |
| Format check | `pnpm format:check` (new) | exit 0 |
| Full verify | `pnpm verify` | exit 0 |

## Scope

**In scope**:
- root `package.json` (devDependencies + scripts)
- `eslint.config.mjs` (create, flat config, repo root)
- `.prettierrc.json` + `.prettierignore` (create)
- `services/automation-python/ruff.toml` (create)
- `services/automation-python/requirements-dev.txt` (create, ruff only) OR add
  ruff to the existing dev bootstrap — match how pytest gets installed
  (inspect `scripts/dev/ensure-python-env.mjs` to see where test deps come
  from, and put ruff in the same place)
- `scripts/test/python-lint.mjs` (create, mirrors python-tests.mjs)
- Mechanical autofix fallout across source files (SEPARATE commit)

**Out of scope** (do NOT touch):
- Rule debates: start from recommended presets only, plus the handful named in
  Step 1. No custom rule inventory.
- Pre-commit hooks / husky — defer.
- CI workflow file (plan 016 owns it; verify already runs in CI).

## Git workflow

- Commit 1: `chore: add eslint, prettier, ruff configs and lint scripts`
- Commit 2: `style: apply automated lint/format fixes` (autofix only, no manual edits)

## Steps

### Step 1: ESLint flat config

Add devDeps at root: `eslint`, `typescript-eslint`, `eslint-plugin-solid`
(check it supports the installed eslint major; drop it if not, and note that).
Create `eslint.config.mjs`:

- `typescript-eslint` recommended (NOT type-checked variant initially — keep
  lint fast; the type-aware rules can come later).
- Targets: `packages/**/src/**/*.ts`, `apps/desktop/src/**/*.{ts,tsx}`,
  `scripts/**/*.mjs`.
- Ignores: `**/dist/**`, `**/out/**`, `**/node_modules/**`, `**/*.test.ts`
  excluded from the no-explicit-any rule only (tests may stub loosely), `plans/`.
- Explicitly enable: `@typescript-eslint/no-floating-promises` requires type
  info — SKIP it in this pass (note as deferred); enable
  `no-unused-vars` (via TS plugin), `eqeqeq`, `no-var`.
- Root script: `"lint:js": "eslint ."`.

**Verify**: `pnpm lint:js` runs and reports; fix config errors until it exits
(violations expected at this point).

### Step 2: Prettier

`.prettierrc.json`: match the OBSERVED dominant style — before writing it, open
3-4 source files and confirm: double quotes, semicolons, 2-space indent,
~120 print width (e.g. `registerIpc.ts`, `domain.ts`). Set `printWidth` to
what the codebase actually uses (inspect; likely 120+ given existing lines).
`.prettierignore`: `dist`, `out`, `release`, `node_modules`, `plans`,
`pnpm-lock.yaml`, `*.md` (leave docs alone for now).
Scripts: `"format:check": "prettier --check ."`, `"format": "prettier --write ."`.

**Verify**: `pnpm format:check` runs (failures expected pre-autofix).

### Step 3: Ruff

`services/automation-python/ruff.toml`:

```toml
target-version = "py312"
line-length = 120

[lint]
select = ["E", "F", "W", "I", "UP", "B"]
ignore = ["E501"]  # long lines exist in prompts; revisit later
```

Install ruff the same way pytest is provisioned (Step scope note). Create
`scripts/test/python-lint.mjs` modeled on `scripts/test/python-tests.mjs`,
running `python -m ruff check applyocalypse_automation tests`. Root script
`"lint:python": "node scripts/test/python-lint.mjs"`.

**Verify**: `pnpm lint:python` runs and reports.

### Step 4: Autofix and triage (separate commit)

1. `pnpm format` (prettier write).
2. `pnpm lint:js -- --fix` and `python -m ruff check --fix ...`.
3. Re-run `pnpm verify` — the FULL suite must stay green after autofixes.
4. Remaining violations: fix trivial ones by hand ONLY if under ~20 total;
   otherwise add targeted `ignore` entries / rule downgrades to get to zero
   and list them in the commit message as follow-up debt. The gate must end
   green — a lint step that fails on day one will be deleted, not fixed.

**Verify**: `pnpm lint:js && pnpm lint:python && pnpm format:check` → all exit 0; `pnpm verify` → exit 0.

### Step 5: Wire into verify

Change root verify to:
`"verify": "pnpm typecheck && pnpm lint:js && pnpm lint:python && pnpm test && pnpm test:python && pnpm python:audit && pnpm audit --audit-level high"`
(format:check intentionally NOT in verify — prettier drift is autofixable noise;
keep it as an on-demand command).

**Verify**: `pnpm verify` → exit 0.

## Test plan

No new tests; the gate is `pnpm verify` green INCLUDING the new lint steps,
and the existing 142 TS + 243 Python tests passing after autofix.

## Done criteria

- [ ] `pnpm lint:js`, `pnpm lint:python`, `pnpm format:check` all exist and exit 0
- [ ] `pnpm verify` includes both lint steps and exits 0
- [ ] Autofix changes are isolated in their own commit with no manual logic edits
- [ ] `pnpm test` and `pnpm test:python` still green post-autofix
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report back if:

- Autofix changes test behavior (any test that passed before fails after) —
  revert the offending file and report which rule did it.
- `eslint-plugin-solid` is incompatible with the chosen eslint version — drop
  it, lint .tsx with the TS preset only, and note it.
- The autofix diff exceeds ~3000 changed lines — pause and ask the operator
  whether to land it (review cost is real).

## Maintenance notes

- Deferred explicitly: type-aware eslint rules (`no-floating-promises`) —
  high value for main-process code, needs `parserOptions.project` and slows
  lint; revisit once the baseline is stable. Also deferred: pre-commit hooks,
  `ruff format` (prettier-style Python formatting), E501 re-enable.
- Reviewer should scrutinize commit 2 for anything that is not a pure
  mechanical fix.
