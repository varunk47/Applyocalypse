# Plan 007: Attribute style-defined font sizes in DOCX font detection so 11pt resumes are not misclassified as 10pt

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 224c6f5..HEAD -- services/automation-python/applyocalypse_automation/documents/font_detection.py services/automation-python/tests/test_font_detection.py`
> Plan 003 adds a pypdf test to test_font_detection.py — that is expected
> drift. Any change to `detect_docx_body_font_size` itself is a STOP condition.

## Status

- **Priority**: P2
- **Effort**: S
- **Risk**: LOW (pure function; falls back to 10 on any error, same as today)
- **Depends on**: none
- **Category**: bug
- **Planned at**: commit `224c6f5`, 2026-06-11

## Why this matters

Font size selects the character-limit tier for resume bullet tailoring
(10pt → 125/240 chars, 11pt → 115/220). The detector histograms only explicit
run-level sizes (`run.font.size`). In very common real-world DOCX resumes the
body size comes from the **Normal style** and every run has `size=None` — the
histogram is empty and detection falls back to 10pt. Result: an 11pt resume
gets the looser 10pt limits (bullets overflow the line) and the profile-rebuild
path renders at the wrong size. The master plan specified "histogram over run
sizes + Normal style default".

## Current state

- `services/automation-python/applyocalypse_automation/documents/font_detection.py:17-44`:

```python
def detect_docx_body_font_size(path: Path) -> int:
    """Return dominant body font size (pt) from a DOCX file. ..."""
    try:
        from docx import Document  # type: ignore
        from docx.shared import Pt  # type: ignore
    except ImportError:
        return _FALLBACK_FONT_SIZE

    try:
        doc = Document(str(path))
        size_counts: dict[int, int] = {}
        for para in doc.paragraphs:
            for run in para.runs:
                size = run.font.size
                if size is not None:
                    pt = round(size / 12700)  # EMUs → pt
                    size_counts[pt] = size_counts.get(pt, 0) + 1
        if not size_counts:
            return _FALLBACK_FONT_SIZE
        dominant = max(size_counts, key=lambda s: size_counts[s])
        return dominant if dominant in _SUPPORTED_SIZES else _FALLBACK_FONT_SIZE
    except Exception:
        return _FALLBACK_FONT_SIZE
```

- Module constants: `_FALLBACK_FONT_SIZE = 10`, `_SUPPORTED_SIZES = {10, 11}`.
- python-docx facts the fix relies on:
  - `run.font.size` is an EMU-backed `Length` or `None` when inherited.
  - A paragraph's effective inherited size comes from
    `para.style.font.size` (paragraph style), which itself may be `None`,
    in which case `doc.styles["Normal"].font.size` applies; that may also be
    `None` (theme default).
  - `Length` values divide by `12700` to get points (the code already does this).
- Tests: `services/automation-python/tests/test_font_detection.py` — existing
  tests build DOCX files with python-docx in temp dirs and set explicit run
  sizes via `run.font.size = Pt(11)`; ImportError-guarded with `pytest.skip`.

## Commands you will need

| Purpose | Command (repo root) | Expected on success |
|---------|---------------------|---------------------|
| Targeted tests | `services\automation-python\.venv-build\Scripts\python.exe -m pytest tests/test_font_detection.py -q` (cwd `services/automation-python`) | all pass |
| Full Python suite | `pnpm test:python` | exit 0 |

## Scope

**In scope**:
- `services/automation-python/applyocalypse_automation/documents/font_detection.py`
  (`detect_docx_body_font_size` only)
- `services/automation-python/tests/test_font_detection.py`

**Out of scope** (do NOT touch):
- `detect_tex_body_font_size`, `detect_resume_font_size`, `count_pdf_pages`.
- The char-limit tier values and `_SUPPORTED_SIZES`.
- Callers in runner.py / docx_builder.py.

## Git workflow

- Commit message: `fix: count style-inherited font sizes in DOCX font detection`

## Steps

### Step 1: Resolve inherited sizes into the histogram

Modify the loop in `detect_docx_body_font_size` so a run with `size is None`
is attributed to its paragraph-style size, then the Normal style size:

```python
        doc = Document(str(path))

        def _style_size_pt(para) -> int | None:
            try:
                style_size = para.style.font.size if para.style is not None else None
            except Exception:
                style_size = None
            if style_size is None:
                try:
                    style_size = doc.styles["Normal"].font.size
                except Exception:
                    style_size = None
            return round(style_size / 12700) if style_size is not None else None

        size_counts: dict[int, int] = {}
        for para in doc.paragraphs:
            for run in para.runs:
                size = run.font.size
                if size is not None:
                    pt = round(size / 12700)
                else:
                    pt_or_none = _style_size_pt(para)
                    if pt_or_none is None:
                        continue
                    pt = pt_or_none
                size_counts[pt] = size_counts.get(pt, 0) + 1
```

Keep the rest of the function (empty-histogram fallback, supported-set check,
outer try/except) unchanged. Explicit run sizes must still dominate when
present — they do, because every run contributes exactly one vote either way.

**Verify**: `services\automation-python\.venv-build\Scripts\python.exe -m pytest tests/test_font_detection.py -q` → existing tests pass (they use explicit run sizes, untouched code path).

### Step 2: Tests for the inherited path

Add to `tests/test_font_detection.py` (same ImportError-skip guard and
temp-dir construction as the existing tests):

1. `test_detects_size_from_normal_style_when_runs_inherit` — build a doc,
   set `doc.styles["Normal"].font.size = Pt(11)`, add paragraphs with runs
   that do NOT set `run.font.size`, save, assert
   `detect_docx_body_font_size(path) == 11`.
2. `test_explicit_run_sizes_outvote_style_default` — Normal style at 11pt,
   but 3 paragraphs of runs explicitly at `Pt(10)` and only 1 inheriting →
   assert result is 10.
3. `test_unsupported_style_size_falls_back` — Normal style at `Pt(12)`, all
   runs inherit → assert result is 10 (fallback, since 12 is unsupported).

**Verify**: same pytest command → all pass including 3 new tests.

## Test plan

Covered in Step 2. Full suite: `pnpm test:python` → exit 0.

## Done criteria

- [ ] `pnpm test:python` exits 0; 3 new tests pass
- [ ] An all-inherited 11pt DOCX detects as 11 (test 1 proves it)
- [ ] Explicit run sizes still dominate (test 2 proves it)
- [ ] No files outside the in-scope list modified (`git status`)
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report back if:

- `detect_docx_body_font_size` no longer matches the excerpt (drift).
- python-docx in `.venv-build` does not expose `doc.styles["Normal"].font.size`
  (API change) — report the installed version (`pip show python-docx`).
- Test 1 fails because python-docx persists an explicit size on runs created
  via `add_paragraph().add_run()` — inspect with `run.font.size is None`
  before saving; if the library auto-assigns sizes, report instead of forcing.

## Maintenance notes

- If a third tier (e.g. 10.5pt) is ever supported, `_SUPPORTED_SIZES` and the
  char-limit table in the tailoring prompt must change together.
- Reviewer should scrutinize: rounding (`round(size / 12700)`) on style sizes
  and that the outer `except Exception` still guarantees a 10pt fallback.
