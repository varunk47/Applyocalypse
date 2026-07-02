# Plan 003: Install pypdf and enforce the one-page resume rule in the live pipeline

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 224c6f5..HEAD -- services/automation-python/requirements.txt services/automation-python/applyocalypse_automation/runner.py services/automation-python/applyocalypse_automation/documents/font_detection.py`
> Plan 002 intentionally modifies `runner.py` in the same region — that is
> expected drift; re-locate insertion points by grepping for the anchors named
> in the steps. Any OTHER mismatch with the excerpts is a STOP condition.

## Status

- **Priority**: P1
- **Effort**: M
- **Risk**: MED (touches the live document-export path)
- **Depends on**: plans/002-validate-final-docx-artifacts.md (same runner.py region; execute 002 first)
- **Category**: bug
- **Planned at**: commit `224c6f5`, 2026-06-11

## Why this matters

The product promises one-page tailored resumes. Two defects make that promise
unverifiable at runtime:

1. `count_pdf_pages` imports `pypdf` and **returns 0 on ImportError** —
   and `pypdf` is not in `requirements.txt`. The PyInstaller build declares it
   in hiddenimports, but a package that is not installed cannot be bundled.
   Page counting is silently dead in dev AND packaged builds.
2. Even with pypdf installed, the page-count check
   (`TextArtifactValidator.check_docx_page_count`) is only reachable via
   `validate_file`, which only `pipeline_cli.py` and tests call. The runner
   never checks page count after PDF export, never re-tailors on overflow, and
   never emits an overflow event.

## Current state

- `services/automation-python/requirements.txt` — no `pypdf` line (verify with
  `grep pypdf services/automation-python/requirements.txt` → no output).
- `services/automation-python/applyocalypse_automation/documents/font_detection.py:88-100`:
  ```python
  def count_pdf_pages(path: Path) -> int:
      """Return page count of a PDF using pypdf. Returns 0 on import error or parse error."""
      try:
          from pypdf import PdfReader  # type: ignore
          reader = PdfReader(str(path))
          return len(reader.pages)
      except ImportError:
          return 0
      except Exception:
          return 0
  ```
- `scripts/build/build-python-worker.mjs:65-69` — hiddenimports already list
  `pypdf`, `pypdf._reader`, `pypdf._page`, `pypdf.filters`. No change needed there.
- `services/automation-python/applyocalypse_automation/runner.py` — the primary
  DOCX export path. After mutation succeeds (`if replaced_placeholders:`), PDF
  export happens at ~line 2367 (line numbers will have shifted after plan 002;
  grep for the anchor):
  ```python
  pdf_export = export_docx_to_pdf(output_path, output_dir)
  if pdf_export.ok and pdf_export.pdf_path:
      ...emits RESUME_RENDERED (format PDF)...
  ```
  There is NO page-count check after this. The LLM bullet tailoring that could
  be re-run on overflow lives just above (grep `tailor_resume_sections`), with:
  ```python
  tailored = asyncio.run(tailor_resume_sections(
      job_description=job_text,
      resume_text=resume_text_for_tailor,
      llm_client=LiteLlmClient(model=llm_model),
      font_size=detected_font_size,
  ))
  ```
  and the mutation pair:
  ```python
  _, replaced_placeholders = mutate_docx_placeholders(master_path, output_path, replacements)
  ...
  _, bullet_replaced = mutate_docx_bullet_anchors(output_path, output_path, bullet_map)
  ```
- Event conventions: `VALIDATION_FAILED` with
  `ui_state={"current_step": "document_review", "requires_user_review": True}` —
  copy the shape from the markdown-validation failure emission (grep
  `"Resume artifact failed deterministic validation"` in runner.py).
- The master plan names the overflow code `RESUME_OVERFLOWS_ONE_PAGE` (use this
  string in the event payload). The existing heuristic warning in
  `validation.py:check_docx_page_count` uses `RESUME_LENGTH_WARNING` — leave it
  untouched.

## Commands you will need

| Purpose | Command (repo root) | Expected on success |
|---------|---------------------|---------------------|
| Recreate venv with new dep | `node scripts/dev/ensure-python-env.mjs` | exit 0 |
| Confirm pypdf installed | `services\automation-python\.venv-build\Scripts\python.exe -c "import pypdf; print(pypdf.__version__)"` | prints a version >= 5 |
| Targeted tests | `services\automation-python\.venv-build\Scripts\python.exe -m pytest tests/test_font_detection.py tests/test_one_page_enforcement.py -q` (cwd `services/automation-python`) | all pass |
| Full Python suite | `pnpm test:python` | exit 0 |

## Scope

**In scope**:
- `services/automation-python/requirements.txt`
- `services/automation-python/applyocalypse_automation/runner.py` (primary DOCX
  export path only)
- `services/automation-python/tests/test_one_page_enforcement.py` (create)
- `services/automation-python/tests/test_font_detection.py` (extend)

**Out of scope** (do NOT touch):
- `validation.py` / `check_docx_page_count` — heuristic path stays as is.
- `scripts/build/build-python-worker.mjs` — hiddenimports already correct.
- The TEX/Tectonic branch and the anchor-free fallback branch — overflow
  handling there is explicitly deferred (emit nothing extra there in this plan).
- `tailor_resume_sections` internals.

## Git workflow

- Commit message: `fix: add pypdf dependency and enforce one-page resume in live export path`

## Steps

### Step 1: Add the dependency

Append to `services/automation-python/requirements.txt` (match the existing
`name>=version` style used by the other lines):

```
pypdf>=5.0
```

**Verify**: `node scripts/dev/ensure-python-env.mjs` (repo root) → exit 0, then
`services\automation-python\.venv-build\Scripts\python.exe -c "import pypdf; print(pypdf.__version__)"` → prints version.

### Step 2: Extract a re-export helper in runner.py

The overflow retry needs to re-run mutation + PDF export. In `runner.py`, the
primary DOCX path currently does (in order): `mutate_docx_placeholders(master_path,
output_path, replacements)` → bullet tailoring → `mutate_docx_bullet_anchors` →
`export_docx_to_pdf(output_path, output_dir)`. Refactor MINIMALLY: extract a
local closure or module-level function

```python
def _remutate_and_export(master_path, output_path, replacements, bullet_map, output_dir):
    """Re-run placeholder + bullet mutation from the master and export PDF. Returns the export result."""
    mutate_docx_placeholders(master_path, output_path, replacements)
    if bullet_map:
        mutate_docx_bullet_anchors(output_path, output_path, bullet_map)
    return export_docx_to_pdf(output_path, output_dir)
```

and call it from the existing flow so behavior is unchanged for the first pass
(or keep the first pass inline and use the helper only for the retry — choose
whichever produces the smaller diff).

**Verify**: `pnpm test:python` → green (pure refactor, no behavior change).

### Step 3: Page-count check + one retry + overflow event

After the first successful PDF export in the primary DOCX path
(`if pdf_export.ok and pdf_export.pdf_path:` — AFTER the existing
`RESUME_RENDERED` PDF event), insert:

1. `pages = count_pdf_pages(pdf_export.pdf_path)` (import from
   `.documents.font_detection`, an import of `detect_resume_font_size` from the
   same module already exists nearby).
2. If `pages > 1` and `llm_model and job_text` (the same guard the tailoring
   block uses): re-run `tailor_resume_sections` ONCE with the overflow
   instruction appended to the job description:
   ```python
   overflow_jd = job_text + (
       "\n\nIMPORTANT: The tailored resume overflowed to "
       + str(pages)
       + " pages. Cut the weakest bullets and tighten wording so the resume fits ONE page."
   )
   ```
   rebuild `bullet_map` from the result (same loop shape as the existing
   `bullet_map` construction), call `_remutate_and_export(...)`, and re-count
   pages on the new PDF.
3. If pages is still > 1 (or the retry was not possible): emit
   `VALIDATION_FAILED` with `severity=Severity.WARN`,
   `machine_state={"format": "PDF", "pages": pages}`,
   `ui_state={"current_step": "document_review", "requires_user_review": True}`,
   `payload={"artifact_kind": "resume", "blocking_issues": [{"code": "RESUME_OVERFLOWS_ONE_PAGE"}], "pages": pages, "pdf_path": str(...)}`.
4. If `pages == 0` (counting failed), do nothing — preserve current behavior.

**Verify**: `pnpm test:python` → green.

### Step 4: Tests

1. Extend `tests/test_font_detection.py`: add
   `test_count_pdf_pages_counts_real_pdf` — build a 2-page PDF in a temp dir
   using pypdf itself:
   ```python
   from pypdf import PdfWriter
   writer = PdfWriter()
   writer.add_blank_page(width=612, height=792)
   writer.add_blank_page(width=612, height=792)
   with open(pdf_path, "wb") as fh:
       writer.write(fh)
   assert count_pdf_pages(pdf_path) == 2
   ```
   No skipif needed once Step 1 lands (pypdf is now a hard dependency) — but
   check whether existing tests in this file use `pytest.skip` ImportError
   guards for pypdf and REMOVE those guards so the tests can never silently
   skip again.
2. Create `tests/test_one_page_enforcement.py`:
   - `test_overflow_jd_mentions_page_count_and_one_page` — unit-test the
     overflow-instruction builder (extract it as a module function
     `_build_overflow_jd(job_text, pages) -> str` if you inlined it).
   - `test_remutate_and_export_runs_mutations_in_order` — call
     `_remutate_and_export` with monkeypatched `mutate_docx_placeholders`,
     `mutate_docx_bullet_anchors`, `export_docx_to_pdf` (use
     `pytest.MonkeyPatch` on the runner module attributes, the same technique
     `tests/test_portal_replay_fixtures.py` uses with `monkeypatch.setattr`)
     and assert call order placeholders → bullets → export.

**Verify**: `services\automation-python\.venv-build\Scripts\python.exe -m pytest tests/test_font_detection.py tests/test_one_page_enforcement.py -q` → all pass.

## Test plan

Covered in Step 4. Full suite: `pnpm test:python` → exit 0. The previously
skipped pypdf-dependent tests in `test_font_detection.py` now RUN (check the
pytest summary contains no skips attributed to "pypdf not installed").

## Done criteria

- [ ] `grep pypdf services/automation-python/requirements.txt` → one line `pypdf>=5.0`
- [ ] `...python.exe -c "import pypdf"` in `.venv-build` → exit 0
- [ ] `grep -n "RESUME_OVERFLOWS_ONE_PAGE" services/automation-python/applyocalypse_automation/runner.py` → at least one match
- [ ] `pnpm test:python` exits 0; new tests pass; no pypdf-ImportError skips remain
- [ ] No files outside the in-scope list modified (`git status`)
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report back if:

- Plan 002 has NOT been executed (check `plans/README.md`) — the shared region
  must be stable first.
- The primary DOCX path no longer matches the anchors named in Step 2/3
  (cannot find `export_docx_to_pdf(output_path, output_dir)` following
  `mutate_docx_bullet_anchors`).
- `ensure-python-env.mjs` fails to install pypdf (network/dependency conflict).
- Re-running `tailor_resume_sections` appears to have side effects beyond
  returning tailored sections.

## Maintenance notes

- Plan 014 (export-path dedup) will consolidate `_remutate_and_export` into a
  shared export flow — keep it small and dependency-free.
- The retry costs one extra LLM call only on overflow; if overflow becomes
  common, consider tightening the initial char-limit tiers (see
  `font_detection.py` docstring: 10pt → 125/240, 11pt → 115/220).
- Reviewer should scrutinize: the retry guard (at most one re-tailor), and that
  `pages == 0` (pypdf parse failure) never triggers the overflow path.
