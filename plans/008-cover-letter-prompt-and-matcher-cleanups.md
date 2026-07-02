# Plan 008: Align the cover-letter prompt with the validator and plan spec; widen the previously-employed matcher

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 224c6f5..HEAD -- services/automation-python/applyocalypse_automation/cover_letter_tailoring.py services/automation-python/applyocalypse_automation/answers.py services/automation-python/tests/test_cover_letter_tailoring.py services/automation-python/tests/test_answers.py`
> Plan 001 edits answers.py's EEO block (different region); plan 006 edits
> nothing in these files. Re-confirm excerpts; unexplained mismatch = STOP.

## Status

- **Priority**: P3
- **Effort**: S
- **Risk**: LOW (prompt text + one keyword tuple; validator still backstops everything)
- **Depends on**: none
- **Category**: bug (quality drift; avoidable validator retries)
- **Planned at**: commit `224c6f5`, 2026-06-11

## Why this matters

Three small drifts reduce output quality or waste an LLM retry:

1. The cover-letter system prompt's banned-word list omits **"deep dive"**,
   which IS in the blocking validator list — the model can produce it, fail
   validation, and burn the single retry for an avoidable reason.
2. The prompt itself **contains an em dash** ("candidate context — do not
   invent") while telling the model not to use em dashes — modeling the banned
   style. The word range is 100–400 vs the plan's 250–350 (letters can come
   out too short to be useful).
3. The "previously employed" matcher misses common phrasings "ever been
   employed by" / "employed with", so those questions fall through to generic
   handling instead of the safe "No"+review proposal.

## Current state

- `services/automation-python/applyocalypse_automation/cover_letter_tailoring.py:10-33`
  — `COVER_LETTER_SYSTEM_PROMPT`:
  ```
  1. Use only verified facts from the candidate context — do not invent experience.
  ...
  7. Do not use any of these banned words: leverage, utilize, spearheaded, robust, \
     comprehensive, seamless, transformative, passionate, excited, thrilled, dynamic, \
     innovative, holistic, empower, foster, harness.
  8. Maximum 400 words. Minimum 100 words.
  ```
  (note: rule 1 contains a literal em dash; rule 7 lacks "deep dive";
  rule 8 says 100–400.)
- The authoritative banned list —
  `services/automation-python/applyocalypse_automation/validation.py:9-27`:
  `leverage, utilize, spearheaded, robust, comprehensive, seamless,
  transformative, passionate, excited, thrilled, dynamic, innovative,
  holistic, empower, foster, harness, deep dive` (17 entries; "deep dive" is
  the one missing from the prompt). The TS validator
  (`packages/validator/src/index.ts:16-33`) carries the same list.
- The retry guidance appended on validation failure
  (`cover_letter_tailoring.py:128-132`) says "Stay under 400 words" — update
  consistently with the new range.
- `services/automation-python/applyocalypse_automation/answers.py:175`:
  ```python
  if any(kw in label for kw in ("previously employed", "former employee", "worked for us", "worked here", "previously worked", "ever worked for")):
  ```
- Tests: `tests/test_cover_letter_tailoring.py` (mocked llm_client, asserts on
  generated text paths) and `tests/test_answers.py` (parametrized label table).

## Commands you will need

| Purpose | Command (repo root) | Expected on success |
|---------|---------------------|---------------------|
| Targeted | `services\automation-python\.venv-build\Scripts\python.exe -m pytest tests/test_cover_letter_tailoring.py tests/test_answers.py -q` (cwd `services/automation-python`) | all pass |
| Full | `pnpm test:python` | exit 0 |

## Scope

**In scope**:
- `services/automation-python/applyocalypse_automation/cover_letter_tailoring.py`
  (prompt text and retry-message text only)
- `services/automation-python/applyocalypse_automation/answers.py` (the one keyword tuple at line 175)
- `services/automation-python/tests/test_cover_letter_tailoring.py`
- `services/automation-python/tests/test_answers.py`

**Out of scope** (do NOT touch):
- `validation.py` / `packages/validator` — the banned list is the source of truth; do not edit it.
- The generation/retry control flow in `generate_cover_letter`.
- The user-message builder's top-3 experience selection and 1200-char sample
  truncation (audit noted them as quality drift, but changing input shaping
  alters token cost and output character — deferred pending a product call).

## Git workflow

- Commit message: `fix: align cover-letter prompt with validator; widen previously-employed matcher`

## Steps

### Step 1: Fix the system prompt

In `COVER_LETTER_SYSTEM_PROMPT`:

1. Rule 1: replace the em dash with a period or colon:
   `Use only verified facts from the candidate context. Do not invent experience.`
2. Rule 7: regenerate the banned list to match `validation.py:BANNED_WORDS`
   exactly, including `deep dive` (17 items).
3. Rule 8: `Target 250-350 words. Hard maximum 400 words.` (validator does not
   block on word count, so 400 stays the stated ceiling while steering to the
   plan's range).
4. Scan the whole prompt string for any other em dash characters and remove
   them (`grep -n "—" cover_letter_tailoring.py` must return no matches after).

Also update the retry-guidance string (line ~128-132): keep "No banned words.
No em dashes." and change "Stay under 400 words." to
"Target 250-350 words; never exceed 400."

**Verify**: `grep -c "deep dive" services/automation-python/applyocalypse_automation/cover_letter_tailoring.py` → at least 1; `grep -c "—" services/automation-python/applyocalypse_automation/cover_letter_tailoring.py` → 0.

### Step 2: Keep prompt and validator from drifting again

Replace the hand-typed list in rule 7 with a programmatic join so the prompt
always reflects the validator:

```python
from .validation import BANNED_WORDS

COVER_LETTER_SYSTEM_PROMPT = f"""\
...
7. Do not use any of these banned words: {", ".join(BANNED_WORDS)}.
...
"""
```

(The module already imports from `.validation`; extend that import. Keep the
f-string conversion minimal — only rule 7 interpolates; double any literal
`{`/`}` braces in the JSON example block as `{{`/`}}`.)

**Verify**: `services\automation-python\.venv-build\Scripts\python.exe -c "from applyocalypse_automation.cover_letter_tailoring import COVER_LETTER_SYSTEM_PROMPT; assert 'deep dive' in COVER_LETTER_SYSTEM_PROMPT; assert chr(8212) not in COVER_LETTER_SYSTEM_PROMPT; print('ok')"` (cwd `services/automation-python`) → `ok`.

### Step 3: Widen the previously-employed matcher

In `answers.py:175`, extend the tuple with two aliases:

```python
("previously employed", "former employee", "worked for us", "worked here", "previously worked", "ever worked for", "employed by", "employed with")
```

NOTE: "employed by" is a substring of phrasings like "Are you currently
employed by ..." — that still correctly proposes "No" + review for the
previous-employer block ONLY if the question concerns this company; the
proposal is always `requires_review=True`, so a wrong guess is reviewable, and
the matcher block sits AFTER the EEO block so no EEO label can be shadowed.
Confirm ordering by reading the surrounding function before editing.

**Verify**: targeted pytest command → green.

### Step 4: Tests

1. `tests/test_answers.py`: add parametrized rows
   - `("Have you ever been employed by this company?", "select", "No", True, "PROFILE")`
   - `("Are you or have you been employed with CertCo?", "select", "No", True, "PROFILE")`
2. `tests/test_cover_letter_tailoring.py`: add
   `test_system_prompt_matches_validator_banned_words` —
   ```python
   from applyocalypse_automation.validation import BANNED_WORDS
   from applyocalypse_automation.cover_letter_tailoring import COVER_LETTER_SYSTEM_PROMPT
   def test_system_prompt_matches_validator_banned_words():
       for word in BANNED_WORDS:
           assert word in COVER_LETTER_SYSTEM_PROMPT
       assert "—" not in COVER_LETTER_SYSTEM_PROMPT
   ```

**Verify**: targeted pytest command → all pass, 3 new tests included.

## Test plan

Covered in Step 4. Full suite: `pnpm test:python` → exit 0.

## Done criteria

- [ ] `pnpm test:python` exits 0; new tests pass
- [ ] Prompt contains every `BANNED_WORDS` entry and zero em dashes (test proves it)
- [ ] "employed by"/"employed with" labels propose "No" with `requires_review=True`
- [ ] No files outside the in-scope list modified (`git status`)
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report back if:

- The prompt or matcher excerpts do not match live code (drift).
- Converting the prompt to an f-string breaks the JSON example braces in a way
  you cannot resolve with `{{`/`}}` doubling (assert the rendered prompt still
  contains the literal `"cover_letter_text"` JSON skeleton).
- Any existing cover-letter test asserts on the exact 100-word minimum.

## Maintenance notes

- The programmatic banned-list join makes future validator additions flow into
  the prompt automatically — reviewer should confirm the rendered prompt reads
  naturally with the joined list.
- Deferred (needs product input): feeding the tailored resume content instead
  of top-3 raw experience entries into the CL user message; raising the
  1200-char sample cap.
