# Plan 015: Lock Python dependencies with pip-tools for reproducible worker builds

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 224c6f5..HEAD -- services/automation-python/requirements.txt scripts/dev/ensure-python-env.mjs scripts/build/build-python-worker.mjs`
> Plan 003 adds `pypdf>=5.0` to requirements.txt — expected; include it in the
> lock. Other structural changes to the env scripts are a STOP condition.

## Status

- **Priority**: P3
- **Effort**: M
- **Risk**: MED (changes what exact versions every dev/CI/packaged build installs; a bad pin shows up as worker breakage)
- **Depends on**: plans/003-pypdf-dep-and-one-page-enforcement.md (so the lock includes pypdf)
- **Category**: dependencies
- **Planned at**: commit `224c6f5`, 2026-06-11

## Why this matters

`requirements.txt` is all unbounded `>=` specifiers (litellm>=1.74.0,
nodriver>=0.44, seleniumbase>=4.33.3, ...). There is no Python lock file, so
every `ensure-python-env` run and every PyInstaller build resolves
latest-at-that-moment. nodriver and seleniumbase are fast-moving
browser-stealth projects where minor releases routinely change behavior — the
worker that passed CI yesterday and the one packaged today can differ. JS has
a lockfile; Python should too.

## Current state

- `services/automation-python/requirements.txt` — loose `>=` specs (~10 deps;
  read the file for the exact list at execution time).
- Three installers consume it:
  - `scripts/dev/ensure-python-env.mjs` — dev venv `.venv-build` (read the
    file to find the exact `pip install -r` invocation).
  - `scripts/build/build-python-worker.mjs:58` —
    `await run(venvPython, ["-m", "pip", "install", "-r", join(serviceDir, "requirements.txt")]);`
  - `.github/workflows/ci.yml` — indirectly via `pnpm verify` → ensure-python-env.
- No pyproject.toml in `services/automation-python`.
- Convention to follow: keep intent (`requirements.in`, loose) separate from
  resolution (`requirements.txt`, fully pinned by pip-compile) so the existing
  `-r requirements.txt` consumers do not need to change paths.

## Commands you will need

| Purpose | Command (repo root) | Expected on success |
|---------|---------------------|---------------------|
| Compile lock | `services\automation-python\.venv-build\Scripts\python.exe -m piptools compile requirements.in -o requirements.txt --strip-extras` (cwd `services/automation-python`) | requirements.txt regenerated, exit 0 |
| Rebuild venv | `Remove-Item -Recurse -Force services/automation-python/.venv-build; node scripts/dev/ensure-python-env.mjs` | exit 0 |
| Python tests | `pnpm test:python` | 243+ passed |
| Python audit | `pnpm python:audit` | no known vulnerabilities |

## Scope

**In scope**:
- `services/automation-python/requirements.in` (create — current loose specs move here)
- `services/automation-python/requirements.txt` (becomes the compiled lock, with the pip-compile header comment)
- `services/automation-python/README.md` or a comment block: one paragraph on how to upgrade (only if a README exists there; otherwise put the how-to in the requirements.in header comment)
- `pip-tools` added wherever dev tools are provisioned (same location decision as plan 014's ruff — inspect `ensure-python-env.mjs`)

**Out of scope** (do NOT touch):
- The installer scripts' `-r requirements.txt` invocations — the lock keeps
  the same filename precisely so these do not change.
- PyInstaller spec/hiddenimports.
- Upgrading any dependency beyond what today's resolution produces — this plan
  pins the status quo; upgrades are deliberate follow-ups.

## Git workflow

- Commit message: `chore(python): introduce requirements.in + pip-compile lock`

## Steps

### Step 1: Create requirements.in

Copy the current `requirements.txt` content verbatim to `requirements.in`,
with a header comment:

```
# Source of intent. Edit THIS file, then regenerate the lock:
#   python -m piptools compile requirements.in -o requirements.txt --strip-extras
```

**Verify**: file exists; content matches old requirements.txt line-for-line.

### Step 2: Compile the lock

Install pip-tools into the build venv
(`.venv-build\Scripts\python.exe -m pip install pip-tools`), then run the
compile command from the table. The output `requirements.txt` will be fully
pinned (`package==x.y.z` with `# via ...` provenance comments).

**Verify**: `Select-String "==" services/automation-python/requirements.txt | Measure-Object` → dozens of pinned lines; the pip-compile header names requirements.in.

### Step 3: Clean rebuild against the lock

Delete `.venv-build` and re-bootstrap (`node scripts/dev/ensure-python-env.mjs`).
This proves a from-scratch install resolves the lock without conflicts.

**Verify**: `pnpm test:python` → all pass; `pnpm python:audit` → clean.

### Step 4: Provision pip-tools for future maintainers

Add pip-tools installation alongside however pytest/dev tools are provisioned
(found in Step scope inspection of `ensure-python-env.mjs`). If dev tools are
simply part of requirements, add `pip-tools` to `requirements.in` under a
`# dev tooling` comment and recompile.

**Verify**: rebuild venv once more → `python -m piptools --version` works inside it.

## Test plan

The lock is validated by the clean rebuild + full pytest pass + pip audit in
Step 3. Additionally run `pnpm python:build` if the operator wants packaged
proof (slow; optional — note in the report whether you ran it).

## Done criteria

- [ ] `requirements.in` exists with the loose specs and regeneration how-to
- [ ] `requirements.txt` is fully pinned with the pip-compile header
- [ ] Fresh `.venv-build` rebuild succeeds; `pnpm test:python` exits 0
- [ ] `pnpm python:audit` reports no known vulnerabilities
- [ ] No installer script needed modification (filename unchanged)
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report back if:

- pip-compile cannot resolve the current `>=` set (conflicting transitive
  pins) — report the conflict output; do not hand-pick versions.
- The freshly locked env fails any pytest that passed before locking — a
  transitive dep moved underneath; report which package differs (`pip freeze`
  diff against a pre-lock venv).
- `pnpm python:audit` flags a vulnerability in the pinned set that the loose
  set avoided — bump that pin in requirements.in and recompile; if it cascades,
  stop and report.

## Maintenance notes

- Upgrades are now explicit: edit `requirements.in` (or run
  `piptools compile --upgrade-package nodriver`), recompile, run
  `pnpm test:python` + a live smoke. Recommend a monthly cadence for
  nodriver/seleniumbase given how fast portal-stealth churns.
- CI uses the same lock automatically (same requirements.txt path).
- Reviewer should scrutinize: the lock's litellm/nodriver/seleniumbase pins
  match what the currently working venv has (`pip freeze` comparison), so this
  plan changes nothing behaviorally on day one.
