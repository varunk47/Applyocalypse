# Plan 018: Consolidate the triplicated document export sequence (mutate → validate → emit → PDF) into one shared flow

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 224c6f5..HEAD -- services/automation-python/applyocalypse_automation/runner.py`
> Plans 002 and 003 land in this exact region FIRST and are prerequisites.
> Re-read the whole resume/cover-letter export region before starting; the
> line numbers below describe the 224c6f5 baseline and WILL have shifted.

## Status

- **Priority**: P3
- **Effort**: M
- **Risk**: MED (touches the live export path; mitigated by the event-sequence replay tests)
- **Depends on**: plans/002-validate-final-docx-artifacts.md, plans/003-pypdf-dep-and-one-page-enforcement.md (their gates become part of the shared flow)
- **Category**: tech-debt
- **Planned at**: commit `224c6f5`, 2026-06-11

## Why this matters

The same export sequence — produce/mutate an artifact, validate it, write a
validation report, emit a RENDERED/MUTATION event, export to PDF, emit the
PDF event or a VALIDATION_FAILED with stdout/stderr tails — is implemented
three times in `runner.py` with copy-drift between them:

1. Resume DOCX path (baseline ~2286-2459, incl. the anchor-free fallback)
2. Resume TEX path (~2460-2540, Tectonic compile instead of DOCX→PDF)
3. Cover letter path (~2560-2627) plus the lazy portal-gate variant
   (`_lazy_generate_cover_letter_for_portal`, ~843-986)

Bug fixes (like plans 002/003's validation and page-count gates) must be
applied 2-4 times or silently diverge — the lazy CL path already lacks
behaviors the resume path has. One `run_export_flow` helper collapses
~500 duplicated lines to ~150 and makes the next gate a one-place change.

## Current state

Read these regions fully before designing (baseline anchors; re-locate by
grepping the quoted strings):

- Resume DOCX: anchor `\"DOCX editable master mutated through explicit Applyocalypse anchors\"`.
  Sequence: `mutate_docx_placeholders` → LLM bullets (`tailor_resume_sections`
  + `mutate_docx_bullet_anchors`) → [plan 002's `validate_file` gate] →
  `RESUME_MUTATION_COMPLETED` + `RESUME_RENDERED(DOCX)` →
  `export_docx_to_pdf` → `RESUME_RENDERED(PDF)` + [plan 003's page-count gate]
  or `VALIDATION_FAILED` with `stdout[-4000:]/stderr[-4000:]` tails.
- Resume DOCX anchor-free fallback: anchor `\"Anchor-free DOCX fallback generated\"`
  — `build_resume_docx` then the same render/PDF/event tail with
  `review_only=True` and WARN severity.
- Resume TEX: anchor `\"TEX editable master mutated\"` —
  `mutate_tex_placeholders` → events → `compile_tex_with_tectonic` → same
  shape with `exporter`/Tectonic specifics.
- Cover letter: anchor `\"cover_letter\"` validations near
  `TextArtifactValidator().validate(cover_letter_content, artifact_kind=\"cover_letter\")`
  (baseline ~2579) and the lazy variant `_lazy_generate_cover_letter_for_portal`.
- Event types involved: `RESUME_MUTATION_COMPLETED`, `RESUME_RENDERED`,
  `COVER_LETTER_RENDERED`, `VALIDATION_FAILED`, `USER_REVIEW_REQUIRED` —
  the exact per-path event types, severities, `machine_state`, `ui_state`, and
  payload keys MUST be preserved byte-for-byte; the consolidation
  parameterizes them, it does not normalize them.
- The regression net — `services/automation-python/tests/test_portal_replay_fixtures.py`
  asserts event SEQUENCES (e.g. `COVER_LETTER_RENDERED` strictly before
  `USER_REVIEW_REQUIRED`); `test_document_mutation.py`, `test_docx_builder.py`,
  `test_cover_letter_tailoring.py` cover the pieces. These must pass unchanged.

## Commands you will need

| Purpose | Command (repo root) | Expected on success |
|---------|---------------------|---------------------|
| Full Python suite | `pnpm test:python` | all pass, count unchanged or higher |
| Targeted | `services\\automation-python\\.venv-build\\Scripts\\python.exe -m pytest tests/test_portal_replay_fixtures.py tests/test_export_flow.py -q` (cwd `services/automation-python`) | all pass |

## Scope

**In scope**:
- `services/automation-python/applyocalypse_automation/documents/export_flow.py` (create)
- `services/automation-python/applyocalypse_automation/runner.py` (the four call sites only)
- `services/automation-python/tests/test_export_flow.py` (create)

**Out of scope** (do NOT touch):
- The mutation primitives (`docx_mutation.py`), converters
  (`export_docx_to_pdf`, `compile_tex_with_tectonic`), validators, builders.
- Event names, severities, payload shapes — zero behavioral change is the
  contract.
- The markdown review-artifact block (validate→write report→emit) at baseline
  ~2244-2284 — it is a different shape (no file mutation/PDF); leave it.

## Git workflow

- Branch suggestion: `refactor/export-flow`
- Commit per step; messages: `refactor: extract document export flow (step N)`

## Steps

### Step 1: Characterize before touching

Run the full suite and capture the baseline:
`pnpm test:python` → note the pass count. Then read all four regions and
write down (in a scratch comment in the new file, deleted before commit) the
table of per-path differences: event type, severity, machine_state keys,
ui_state, payload keys, review_only flag, exporter kind. This table IS the
parameterization spec.

**Verify**: baseline suite green; the difference table covers all four paths.

### Step 2: Build `export_flow.py` around the most complex path

Create a dataclass-driven helper:

```python
@dataclass(frozen=True, slots=True)
class ExportFlowSpec:
    run_id: str
    artifact_kind: str                  # "resume" | "cover_letter"
    file_kind: str                      # "RESUME" | "COVER_LETTER"
    source_format: str                  # "DOCX" | "TEX"
    review_only: bool
    rendered_event: EventType           # RESUME_RENDERED / COVER_LETTER_RENDERED
    mutation_event: EventType | None    # RESUME_MUTATION_COMPLETED or None
    severity: Severity                  # INFO normal, WARN fallback
    pdf_exporter: Callable[[Path, Path], ExportResult]  # export_docx_to_pdf or compile_tex_with_tectonic
    extra_machine_state: dict[str, Any] = field(default_factory=dict)

def run_export_flow(spec: ExportFlowSpec, *, output_path: Path, output_dir: Path,
                    mutation_payload: dict[str, Any] | None) -> None:
    """validate_file gate -> mutation/rendered events -> PDF export -> PDF event
    or VALIDATION_FAILED with stdout/stderr tails. Emits exactly the events the
    inline blocks emitted; see test_export_flow for the locked sequences."""
```

Implement it to reproduce the resume-DOCX path's behavior (the superset:
plan 002 validation gate, both events, PDF export, plan 003 page-count hook —
expose the page-count/retailor step as an optional callback in the spec since
only the resume path uses it).

**Verify**: `python -c "from applyocalypse_automation.documents.export_flow import run_export_flow"` imports clean (cwd `services/automation-python`, venv python).

### Step 3: Switch the four call sites one at a time

Order: resume DOCX → anchor-free fallback → TEX → cover letter (incl. lazy).
After EACH switch, run the full suite — the replay-fixture tests are the
event-sequence lock. A failure means the parameterization missed a per-path
difference; fix the spec, not the test.

**Verify** (after each): `pnpm test:python` → same pass count as baseline.

### Step 4: Lock the flow with direct tests

`tests/test_export_flow.py` — monkeypatch `WorkerEvent.emit` to capture
(pattern: `test_portal_replay_fixtures.py:366-371`), stub the pdf_exporter
callable, and assert for each spec shape:
1. success path emits [mutation_event?, rendered_event, rendered_event(PDF)]
   in order with the expected machine_state formats;
2. failed PDF export emits VALIDATION_FAILED with `stdout`/`stderr` tails and
   `requires_user_review` ui_state;
3. validation-gate failure emits VALIDATION_FAILED and still proceeds/halts
   exactly as the inline code did (encode whatever Step 1's table said).

**Verify**: targeted pytest → all pass; full suite ≥ baseline count + new tests.

## Test plan

Steps 1/3/4. The replay fixtures are the acceptance bar: identical event
sequences before and after.

## Done criteria

- [ ] `pnpm test:python` exits 0; pass count ≥ baseline + new export-flow tests
- [ ] `grep -c "export_docx_to_pdf(output_path" services/automation-python/applyocalypse_automation/runner.py` → 0 (all via the flow)
- [ ] runner.py shrank by ≥ 250 lines (`git diff --stat`)
- [ ] No event name/severity/payload-key changes (`git diff` review of test fixtures: zero fixture edits)
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report back if:

- Plans 002/003 are not DONE.
- Step 1's difference table reveals a path difference that cannot be expressed
  as data (e.g. interleaved control flow unique to one path) — report the
  specific divergence; a partial consolidation (3 of 4 paths) needs operator
  sign-off.
- Any replay-fixture test fails in a way that requires editing the FIXTURE to
  pass — that is a behavior change; revert the step.

## Maintenance notes

- Plans 002/003's gates now live in one place; future gates (e.g. TEX page
  count) are a spec field away.
- This is the enabling step for plan 020 (runner decomposition) — export_flow
  is the first module extracted out of runner.py.
- Reviewer should scrutinize: the per-path `machine_state`/payload parity
  (diff the captured event dicts in tests against the old inline literals).
