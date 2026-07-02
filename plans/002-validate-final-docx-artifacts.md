# Plan 002: Validate the final mutated resume file (DOCX and TEX) so banned content cannot reach a submitted document

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 224c6f5..HEAD -- services/automation-python/applyocalypse_automation/runner.py services/automation-python/applyocalypse_automation/validation.py services/automation-python/tests/`
> If `runner.py` lines 2240-2520 or `validation.py` changed since this plan was
> written, compare the "Current state" excerpts against the live code before
> proceeding; on a mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: LOW
- **Depends on**: none (but plan 003 builds on the same region — execute 002 before 003)
- **Category**: bug (violates a core repo invariant)
- **Planned at**: commit `224c6f5`, 2026-06-11

## Why this matters

A core blocking invariant of this repo: **no em dashes and no banned words in
any generated content** (`TextArtifactValidator` enforces it). The runner
validates the *markdown review artifact* and cover letters, but the actual
DOCX file that gets uploaded to job portals — produced by mutating the user's
editable master with LLM-tailored bullets — is **never validated**. An em dash
or banned word in an LLM bullet lands in the submitted resume unchecked. The
TEX path has the same gap. This plan adds a final-file validation gate after
mutation, with one LLM retry for the bullet content, and a `VALIDATION_FAILED`
event (requiring user review) when blocking issues remain.

## Current state

- `services/automation-python/applyocalypse_automation/runner.py` — the
  orchestrator (~2700 lines). The relevant region:
  - `runner.py:2244-2247` — markdown review artifact IS validated:
    ```python
    resume_content = build_resume_markdown(canonical_profile=canonical_profile, tailoring_plan=tailoring_plan)
    resume_report = TextArtifactValidator().validate(resume_content, artifact_kind="resume")
    ```
  - `runner.py:2305` — placeholder mutation writes the output DOCX:
    `_, replaced_placeholders = mutate_docx_placeholders(master_path, output_path, replacements)`
  - `runner.py:2308-2335` — LLM deep-tailoring: `tailor_resume_sections(...)`
    produces `bullet_map`, then:
    ```python
    if bullet_map:
        _, bullet_replaced = mutate_docx_bullet_anchors(output_path, output_path, bullet_map)
    ```
    **No validation runs after this.** The next code (`runner.py:2345-2366`)
    emits `RESUME_MUTATION_COMPLETED` + `RESUME_RENDERED` and exports PDF.
  - `runner.py:2460-2497` — TEX branch: `mutate_tex_placeholders(...)` then
    emits events and compiles with Tectonic. Also unvalidated.
- `services/automation-python/applyocalypse_automation/validation.py`:
  - `TextArtifactValidator.validate(text, artifact_kind=...)` → `ValidationReport`
    with `.passed`, `.blocking_issues`, `.warnings`, `.to_dict()`.
  - `TextArtifactValidator.validate_file(path, *, artifact_kind, ...)`
    (validation.py:240) — extracts text from a DOCX/TEX file via
    `extract_artifact_text(path)` and validates it. **This is the function to
    use for the final gate — it already handles both formats.**
- `services/automation-python/applyocalypse_automation/documents/docx_mutation.py:48`
  — `extract_docx_text(path) -> str` (used elsewhere; `validate_file` is preferred here).
- Event convention — `VALIDATION_FAILED` emission pattern to copy
  (`runner.py:2275-2284`):
  ```python
  WorkerEvent(
      event_type=EventType.VALIDATION_FAILED,
      run_id=args.run_id,
      step_id=None,
      severity=Severity.ERROR,
      message="Resume artifact failed deterministic validation",
      machine_state={"format": "MD", "review_only": True},
      ui_state={"current_step": "document_review", "requires_user_review": True},
      payload={"artifact_kind": "resume", "validation_report_path": str(validation_report_path), **resume_report.to_dict()},
  ).emit()
  ```
- LLM retry convention — `cover_letter_tailoring.py:84-139` retries once by
  appending violation guidance to the user message:
  ```python
  user_message += (
      "\n\nIMPORTANT: The previous attempt failed validation. "
      "Return raw JSON only. No markdown fences. No bold markers. "
      "No banned words. No em dashes. Stay under 400 words."
  )
  ```

## Commands you will need

| Purpose | Command (repo root `C:\Jobs\Codex\applyocalypse`) | Expected on success |
|---------|----------------------------------------------------|---------------------|
| Targeted tests | `services\automation-python\.venv-build\Scripts\python.exe -m pytest tests/test_final_artifact_validation.py -q` (cwd `services/automation-python`) | all pass |
| Full Python suite | `pnpm test:python` | 243+ passed, exit 0 |

If `.venv-build` is missing: `node scripts/dev/ensure-python-env.mjs` from repo root.

## Scope

**In scope**:
- `services/automation-python/applyocalypse_automation/runner.py` (the DOCX
  mutation block ~2305-2345 and TEX block ~2460-2500 only)
- `services/automation-python/tests/test_final_artifact_validation.py` (create)

**Out of scope** (do NOT touch):
- `validation.py` — `validate_file` already does what's needed.
- The markdown-artifact validation at runner.py:2245 — keep as is.
- Cover-letter generation paths — they already validate.
- `tailor_resume_sections` internals (`resume_tailoring.py`) — retry happens at
  the call site, not inside.
- PDF export / page-count logic — that is plan 003.

## Git workflow

- Commit message: `fix: validate mutated resume files before render events (em-dash/banned-word gate)`

## Steps

### Step 1: Pre-mutation bullet validation with one retry

In `runner.py`, immediately after `tailored = asyncio.run(tailor_resume_sections(...))`
returns (line ~2318-2323) and `bullet_map` is built (line ~2325-2332), insert
validation of the LLM bullet content BEFORE `mutate_docx_bullet_anchors` runs:

1. Join all bullet strings: `bullet_text = "\n".join(b for bullets in bullet_map.values() for b in bullets)`
2. `bullet_report = TextArtifactValidator().validate(bullet_text, artifact_kind="resume")`
3. If `not bullet_report.passed`: re-run `tailor_resume_sections` ONCE with the
   violation codes appended to the `job_description` argument:
   ```python
   violation_codes = ", ".join(issue.code for issue in bullet_report.blocking_issues)
   retry_jd = job_text + (
       "\n\nIMPORTANT: The previous bullet set failed validation ("
       + violation_codes
       + "). No em dashes. No banned words. Plain text bullets only."
   )
   ```
   Rebuild `bullet_map` from the retry result and re-validate.
4. If the retry's report still has blocking issues: set `bullet_map = {}` (skip
   bullet mutation entirely — the placeholders-only DOCX remains valid) and
   emit a `VALIDATION_FAILED` event (severity `Severity.WARN`,
   `ui_state={"current_step": "document_review", "requires_user_review": True}`,
   payload includes `{"artifact_kind": "resume", "stage": "llm_bullets", **report.to_dict()}`).
   Copy the event shape from the excerpt in "Current state".

**Verify**: `pnpm test:python` → existing suite still green (this step adds no
behavior change when bullets are clean).

### Step 2: Final-file gate for the DOCX path

Still in `runner.py`, after the `if bullet_map:` mutation block and the
anchored-candidate fallback (after line ~2343, just BEFORE
`if replaced_placeholders:` at ~2345), insert:

```python
final_report = TextArtifactValidator().validate_file(output_path, artifact_kind="resume") if output_path.exists() else None
if final_report is not None and not final_report.passed:
    WorkerEvent(
        event_type=EventType.VALIDATION_FAILED,
        run_id=args.run_id,
        step_id=None,
        severity=Severity.ERROR,
        message="Mutated DOCX resume failed deterministic validation",
        machine_state={"format": "DOCX", "review_only": False},
        ui_state={"current_step": "document_review", "requires_user_review": True},
        payload={"artifact_kind": "resume", "stage": "final_file", "generated_path": str(output_path), **final_report.to_dict()},
    ).emit()
```

Do not block the subsequent events — the artifact still renders, but the run
surfaces a review-required validation failure (matching how the markdown-path
failure at runner.py:2274-2284 behaves: it emits and continues).

**Verify**: `pnpm test:python` → green.

### Step 3: Final-file gate for the TEX path

In the TEX branch, after `mutate_tex_placeholders(...)` succeeds
(`if replaced_placeholders:` at ~2476), insert the same `validate_file` gate
with `machine_state={"format": "TEX", ...}`. `validate_file` handles `.tex`
extraction already.

**Verify**: `pnpm test:python` → green.

### Step 4: Write the tests

Create `services/automation-python/tests/test_final_artifact_validation.py`
(pattern: follow `tests/test_document_mutation.py` — it builds DOCX files with
python-docx inside `tempfile.TemporaryDirectory()` and guards with
`pytest.skip("python-docx not installed")` on ImportError):

1. `test_validate_file_blocks_em_dash_in_docx` — build a DOCX whose paragraph
   text contains an em dash (`"Led teams — delivered results"`), run
   `TextArtifactValidator().validate_file(path, artifact_kind="resume")`,
   assert `report.passed is False` and some blocking issue code mentions the
   em dash (inspect the validator's actual code string first — find it with
   `grep -n "em" services/automation-python/applyocalypse_automation/validation.py`).
2. `test_validate_file_passes_clean_docx` — same construction without banned
   content → `report.passed is True`.
3. `test_bullet_retry_message_includes_violation_codes` — unit-test whatever
   small helper you extracted in Step 1 (if you inlined it, extract a module
   function `_build_bullet_retry_jd(job_text, report) -> str` in runner.py so
   it is testable) — assert the returned string contains the violation code
   and the "No em dashes" instruction.

**Verify**: `services\automation-python\.venv-build\Scripts\python.exe -m pytest tests/test_final_artifact_validation.py -q` → 3 passed.

## Test plan

Covered in Step 4. Full-suite verification: `pnpm test:python` → exit 0 with
3 new tests included.

## Done criteria

- [ ] `pnpm test:python` exits 0; the 3 new tests pass
- [ ] `grep -n "validate_file" services/automation-python/applyocalypse_automation/runner.py` shows at least 2 call sites (DOCX path, TEX path)
- [ ] An em dash in LLM bullet content can no longer reach the mutated DOCX silently: either the retry cleans it, mutation is skipped, or `VALIDATION_FAILED` is emitted (assert via the new unit tests + code review of Step 1 branch logic)
- [ ] No files outside the in-scope list modified (`git status`)
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report back if:

- `runner.py:2305-2345` does not match the "Current state" excerpts (drift —
  plan 003 or other work may have landed first; re-locate the region by
  grepping `mutate_docx_bullet_anchors` and re-confirm the surrounding logic
  before changing anything).
- `TextArtifactValidator.validate_file` does not exist at validation.py:240 or
  its signature differs from the excerpt.
- `tailor_resume_sections` cannot be safely re-invoked (e.g., it mutates state
  or its signature differs from `(job_description=..., resume_text=..., llm_client=..., font_size=...)`).
- Existing tests fail after Step 1 in a way not explained by your changes.

## Maintenance notes

- Plan 003 (one-page enforcement) inserts logic into the SAME region after PDF
  export; execute 002 first so 003's diffs apply on top.
- Plan 014 (export-path dedup) will later consolidate this validation gate into
  a shared export flow — keep the gate as a small, extractable block.
- Reviewer should scrutinize: the retry must run at most ONCE (no loops), and
  the `bullet_map = {}` fallback must leave the placeholders-only DOCX intact.
