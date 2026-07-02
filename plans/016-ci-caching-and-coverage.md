# Plan 016: Cache dependencies in CI and surface test coverage

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 224c6f5..HEAD -- .github/workflows/ci.yml vitest.config.ts package.json`
> Plans 014/015 may have altered verify and the Python env — reread ci.yml
> fully before editing.

## Status

- **Priority**: P3
- **Effort**: S
- **Risk**: LOW (CI-only; worst case is a cache miss, which equals today's behavior)
- **Depends on**: none (coverage step interacts with plan 014's verify changes — apply on whatever verify looks like at execution time)
- **Category**: dx
- **Planned at**: commit `224c6f5`, 2026-06-11

## Why this matters

CI (windows-latest) reinstalls every dependency and rebuilds better-sqlite3
from source on every run — several minutes of pure overhead per push. And
`vitest.config.ts` declares 80% coverage thresholds that nothing ever
enforces: CI never runs `--coverage`, so the thresholds are dead config and
coverage can regress silently.

## Current state

- `.github/workflows/ci.yml` (full content read at planning time): checkout →
  setup-node@v4 (`node-version: "22"`, NO cache option) → pnpm/action-setup@v4
  (10.33.0) → setup-python@v5 ("3.12", NO cache option) →
  `pnpm install --frozen-lockfile` → `pnpm native:rebuild` → `pnpm verify` →
  `pnpm release:preflight`.
- `vitest.config.ts:22-31` — coverage block exists:
  ```ts
  coverage: {
    provider: "v8",
    reporter: ["text", "json-summary"],
    thresholds: { branches: 80, functions: 80, lines: 80, statements: 80 }
  }
  ```
  but `@vitest/coverage-v8` is NOT in devDependencies (verify with
  `grep coverage-v8 package.json`) and no script passes `--coverage`.
- Real coverage today is unknown — the 80% thresholds were aspirational. A
  hard gate that fails CI on day one will get deleted; this plan reports
  coverage and enforces only a floor it actually meets.

## Commands you will need

| Purpose | Command (repo root) | Expected on success |
|---------|---------------------|---------------------|
| Coverage locally | `pnpm test:coverage` (new) | tests pass, coverage table prints, exit 0 |
| YAML sanity | push to a branch / `gh workflow view` | CI green |

## Scope

**In scope**:
- `.github/workflows/ci.yml`
- root `package.json` (devDep `@vitest/coverage-v8`, script `test:coverage`)
- `vitest.config.ts` (threshold numbers only, if they must drop to reality)

**Out of scope** (do NOT touch):
- The verify pipeline composition (plan 014 owns it).
- Codecov/external services — text + summary in the job log only.
- Python coverage (pytest-cov) — deferred; note it.

## Git workflow

- Commit message: `ci: cache pnpm/pip stores, report vitest coverage`

## Steps

### Step 1: pnpm store cache

`setup-node@v4` has first-class pnpm caching — add to the existing step:

```yaml
      - name: Setup Node
        uses: actions/setup-node@v4
        with:
          node-version: "22"
          cache: "pnpm"
```

ORDERING REQUIREMENT: `actions/setup-node` with `cache: pnpm` requires pnpm to
already be on PATH — move the `pnpm/action-setup@v4` step ABOVE setup-node.

**Verify**: workflow YAML parses (`gh workflow view` after push, or a YAML
linter locally); CI run shows "Cache restored" on the second run.

### Step 2: pip cache

```yaml
      - name: Setup Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.12"
          cache: "pip"
          cache-dependency-path: services/automation-python/requirements.txt
```

(If plan 015 landed, requirements.txt is the lock — ideal cache key.)

**Verify**: second CI run shows pip cache restored.

### Step 3: better-sqlite3 build cache (optional, attempt once)

The expensive step is node-gyp compiling better-sqlite3. Add an
`actions/cache@v4` step keyed on
`${{ runner.os }}-bsqlite-${{ hashFiles('pnpm-lock.yaml') }}` caching
`node_modules/.pnpm/better-sqlite3*/node_modules/better-sqlite3/build`. If the
restored build does not survive `pnpm install --frozen-lockfile` (pnpm may
recreate the dir), `pnpm native:rebuild` repairs it anyway — the cache is
best-effort. If this step proves flaky on the first CI run, delete it and note
that in the report; steps 1-2 are the dependable wins.

**Verify**: CI green with the step present (or removed with a note).

### Step 4: Coverage reporting

1. Add devDep `@vitest/coverage-v8` (match the vitest major: ^3.2.6).
2. Root script: `"test:coverage": "pnpm native:rebuild:node && vitest run --coverage"`.
3. Run it locally. Read the ACTUAL totals. Then set the thresholds in
   `vitest.config.ts` to 5 points BELOW actual (floor, not target) so the gate
   is green from day one but catches regressions. If actuals are wildly below
   80 (plausible — renderer screens are untested), keep the new honest numbers
   and note the gap in the report.
4. Add a CI step after Verify:
   ```yaml
      - name: Coverage
        run: pnpm test:coverage
   ```

**Verify**: `pnpm test:coverage` locally → exit 0 with table; CI run green
with the coverage summary visible in the log.

## Test plan

No new tests. Gates: two consecutive CI runs (first primes caches, second
proves restore + green), local `pnpm test:coverage` exit 0.

## Done criteria

- [ ] ci.yml: pnpm-action before setup-node; node cache=pnpm; python cache=pip
- [ ] Second CI run restores both caches (check the run logs)
- [ ] `pnpm test:coverage` exists and exits 0 locally and in CI
- [ ] vitest thresholds reflect measured reality (no aspirational dead config)
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report back if:

- You cannot trigger/observe CI runs (no push rights) — land the YAML changes
  and report that runtime verification is pending.
- `@vitest/coverage-v8@^3` conflicts with the installed vitest — report the
  resolution rather than forcing.
- Measured coverage is so low the thresholds become meaningless (<30%) — set
  no thresholds (report-only) and say so.

## Maintenance notes

- When the vitest major bumps, `@vitest/coverage-v8` must bump in lockstep.
- Ratchet the thresholds upward as plans 012 and future test plans land —
  re-measure and raise the floor each time.
- Deferred: Python coverage via pytest-cov; PR comment integration.
