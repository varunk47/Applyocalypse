# Plan 020: Decompose runner.py — extract the document-generation and answer-resolution stages into modules

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 224c6f5..HEAD -- services/automation-python/applyocalypse_automation/`
> This plan REQUIRES plans 002, 003, and 018 to be DONE (018 already extracted
> export_flow). Line anchors below are baseline-relative; re-locate by symbol.

## Status

- **Priority**: P3
- **Effort**: L
- **Risk**: HIGH for a careless move, MED with the staged approach below — this file orchestrates live applies
- **Depends on**: plans/018-document-export-flow-dedup.md (and transitively 002, 003)
- **Category**: tech-debt
- **Planned at**: commit `224c6f5`, 2026-06-11

## Why this matters

`runner.py` is ~2700 lines (post-018: ~2400) holding 50+ top-level functions
across at least five concerns: CLI/arg handling, answer
proposal/field-resolution, OTP application, portal step execution and approval
gates, and the document-generation pipeline. Every recent phase added 100-200
inline lines. The repo's own convention caps files at 800 lines. Each
extraction below moves a cohesive, already-loosely-coupled cluster behind an
import, with the existing test suite as a lock at every step. This plan
deliberately does NOT touch the portal/approval-gate orchestration core — the
riskiest part stays put until the extracted layers around it are stable.

## Current state

(Re-derive exact line spans at execution time; clusters verified at planning:)

- `services/automation-python/applyocalypse_automation/runner.py`:
  - **Answer/field cluster** (~baseline 340-400 + helpers they call):
    `is_password_field`, `is_otp_field`, `normalize_field_label` (check where
    it lives), `proposed_answer_for_browser_field`,
    `resolve_secret_reviewed_value`, `APPLICATION_PASSWORD_SENTINEL`,
    `OTP_FIELD_HINTS`. Imports `answers.py` already.
  - **Document-generation stage** (~baseline 2070-2640): the big block that
    reads work-dir inputs (`canonical-profile.json`, `job-description.txt`,
    `job-target.json`), runs JD analysis + tailoring plan, builds the markdown
    review artifact, finds the editable master, and drives the (post-018)
    export_flow calls; plus `_lazy_generate_cover_letter_for_portal` and the
    name/company/role helpers (`split_legal_name`, `_company_from_url`,
    `_role_from_url`).
  - **Remaining in place** (explicitly NOT extracted in this plan): CLI/args,
    the async portal session loop, approval-gate wait loops, worker control
    polling, OTP application (`apply_otp_code_to_detected_field`), browser
    adapter selection.
- Existing module layout to follow: peer modules already exist and are the
  convention — `answers.py`, `jd_analysis.py`, `cover_letter_tailoring.py`,
  `resume_tailoring.py`, `documents/` package, `otp/` package,
  `browser/` package. Extractions are new peer modules, not a new framework.
- Test net: 243+ tests; the ones that import runner internals directly —
  `grep -rn "from applyocalypse_automation.runner import\|from applyocalypse_automation import runner" services/automation-python/tests` —
  list them BEFORE moving symbols, since their imports must be updated (or
  better: re-export moved names from runner.py during a deprecation window —
  see Step 3).

## Commands you will need

| Purpose | Command (repo root) | Expected on success |
|---------|---------------------|---------------------|
| Full Python suite | `pnpm test:python` | pass count == baseline (+ any new) |
| Import sanity | `services\automation-python\.venv-build\Scripts\python.exe -c "import applyocalypse_automation.runner"` (cwd `services/automation-python`) | exit 0 |
| Line count | `(Get-Content services/automation-python/applyocalypse_automation/runner.py).Count` | shrinking per step |

## Scope

**In scope**:
- `services/automation-python/applyocalypse_automation/runner.py`
- `services/automation-python/applyocalypse_automation/field_resolution.py` (create)
- `services/automation-python/applyocalypse_automation/document_stage.py` (create)
- Test files whose imports must follow moved symbols

**Out of scope** (do NOT touch):
- The async portal/approval/control-loop core of runner.py (this plan
  shrinks around it).
- Behavior of ANY function — pure moves with import updates.
- `applyocalypse_worker_entry.py` / PyInstaller spec (entry imports runner;
  runner keeps its public surface via re-exports).

## Git workflow

- Branch suggestion: `refactor/runner-decomposition`
- One commit per extraction; messages: `refactor: extract <module> from runner (no behavior change)`

## Steps

### Step 1: Map and baseline

1. `pnpm test:python` → record the pass count.
2. Build the symbol map: for each of the two clusters, list every function/
   constant and (via grep) every internal caller and every test importing it.
   Symbols used ONLY by the cluster move; symbols used by the remaining
   runner core get moved AND re-exported (Step 3).

**Verify**: baseline recorded; symbol map written into the PR description.

### Step 2: Extract `field_resolution.py`

Move the answer/field cluster verbatim into the new module (imports adjusted).
This cluster is small, pure, and already test-covered via `test_answers.py` +
runner-level tests — it is the low-risk warm-up.

**Verify**: `pnpm test:python` → baseline count; import sanity command → ok.

### Step 3: Re-export shim in runner.py

At the old definition sites, replace bodies with re-exports:

```python
from .field_resolution import (  # noqa: F401 — compatibility re-exports
    APPLICATION_PASSWORD_SENTINEL,
    is_otp_field,
    is_password_field,
    proposed_answer_for_browser_field,
    resolve_secret_reviewed_value,
)
```

Then update TEST imports to the new module and slim the shim to only what the
runner core itself still calls. (The shim means nothing breaks if a
monkeypatch in tests targets `runner.is_password_field` — check for
`monkeypatch.setattr(runner, ...)` patterns and update those targets too;
monkeypatching a re-export does NOT patch the original module's reference.)

**Verify**: `pnpm test:python` → baseline count.

### Step 4: Extract `document_stage.py`

Move the document-generation stage: the work-dir input readers, the
analysis/tailoring-plan block, markdown review artifact, master
selection, export_flow invocations, `_lazy_generate_cover_letter_for_portal`,
and the small name/URL helpers. The runner core ends up calling 1-2 entry
points, e.g.:

```python
from .document_stage import generate_application_documents, lazy_generate_cover_letter_for_portal
```

The moved code needs the runner's context (args.run_id, work_dir, output_dir,
canonical_profile, job_text, job_metadata) — pass these as parameters; do NOT
create a shared mutable context object (matches how export_flow took a spec).

CAUTION: this block is where plans 002/003/018 landed. Move the post-018
shape, and re-run the replay-fixture tests after — they lock the event
sequences (`test_portal_replay_fixtures.py` monkeypatches
`_lazy_generate_cover_letter_for_portal` THROUGH the runner module in at least
one test — update those monkeypatch targets per Step 3's caution).

**Verify**: `pnpm test:python` → baseline count; runner.py now under ~1200
lines (report the actual number).

### Step 5: Final sweep

1. `git diff --color-moved=dimmed-zebra` — confirm pure moves.
2. Dead-import cleanup in runner.py (only imports YOUR moves orphaned).
3. Full verify: `pnpm verify` (TS side unaffected but cheap insurance).

**Verify**: `pnpm verify` → exit 0.

## Test plan

No new tests required (pure moves); the 243-test suite at every step is the
lock. If Step 1's mapping finds a moved function with NO test coverage at all,
add one characterization test for it in the new module's test file before
moving it (note which in the report).

## Done criteria

- [ ] `pnpm test:python` pass count == baseline (+ characterization additions)
- [ ] runner.py ≤ ~1200 lines; new modules each < 800 lines
- [ ] No behavior diff: replay-fixture tests untouched and green
- [ ] All monkeypatch targets updated (grep `setattr(runner` in tests → only core-loop symbols remain)
- [ ] `pnpm verify` exits 0
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report back if:

- Plans 002/003/018 are not all DONE.
- The document stage turns out to share mutable state with the portal loop
  beyond parameters (e.g. module-level globals mutated by both) — list them;
  that coupling needs a design decision, not improvisation.
- Any replay-fixture test fails after a move and the cause is not an import/
  monkeypatch target — revert the step.
- runner.py cannot reach ≤ ~1200 lines without touching the portal core —
  stop at whatever the two extractions achieve and report the remainder.

## Maintenance notes

- The portal/approval core remains the next (and riskiest) candidate — only
  attempt it after this plan has soaked through a few live-run cycles.
- New document-pipeline features go into `document_stage.py`/`export_flow.py`,
  not runner.py; new field heuristics into `field_resolution.py`/`answers.py`.
- Reviewer should scrutinize: monkeypatch-target updates in tests (the classic
  silent failure of Python move-refactors) and the parameter lists of the new
  entry points (no hidden globals).
