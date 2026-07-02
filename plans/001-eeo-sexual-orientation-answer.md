# Plan 001: Make "sexual orientation" questions answer from the sexualOrientation profile field, not the LGBTQ Yes/No

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 224c6f5..HEAD -- services/automation-python/applyocalypse_automation/answers.py services/automation-python/tests/test_answers.py`
> If either file changed since this plan was written, compare the
> "Current state" excerpts against the live code before proceeding; on a
> mismatch, treat it as a STOP condition.

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: bug (safety-sensitive answer proposal)
- **Planned at**: commit `224c6f5`, 2026-06-11

## Why this matters

Applyocalypse proposes answers for detected form fields during job applications.
EEO questions are legally sensitive and always require user review, but the
*proposed value* should still be correct. Today a question like "How would you
describe your sexual orientation?" matches the LGBTQ rule and proposes the
LGBTQ Yes/No value (e.g. **"No"**) instead of the actual sexual-orientation
value (e.g. **"Heterosexual"**). The profile schema has a dedicated
`sexualOrientation: string[]` field that is currently never used. Additionally,
if any EEO value is a list, the generic `str(raw)` renders it as
`"['Heterosexual']"` — Python repr syntax leaking into a form answer.

## Current state

- `services/automation-python/applyocalypse_automation/answers.py` — answer
  proposal logic. The EEO rules table and matching loop:

```python
# answers.py:102-110
_EEO_RULES: list[tuple[tuple[str, ...], str]] = [
    (("gender", "sex"), "gender"),
    (("disability", "disabled"), "disability"),
    (("veteran", "military service"), "veteran"),
    (("race",), "race"),
    (("ethnicity", "ethnic"), "race"),
    (("hispanic", "latino"), "hispanicOrLatino"),
    (("lgbtq", "sexual orientation"), "lgbtq"),
]
```

```python
# answers.py:148-160 (inside propose_answer_for_detected_field)
    # ── EEO fields — always requires_review (legal sensitivity) ──────────────────
    # Must come before address rules because "ethnicity" contains "city"
    eeo = _eeo(profile)
    for aliases, eeo_key in _EEO_RULES:
        if any(alias in label for alias in aliases):
            raw = eeo.get(eeo_key)
            value = str(raw) if raw is not None else None
            return ProposedApplicationAnswer(
                field_label=field_label, field_type=field_type,
                proposed_value=value,
                confidence=0.88 if value else 0.20, source="PROFILE" if value else "UNKNOWN",
                requires_review=True,
            )
```

- The canonical profile schema (TypeScript source of truth) defines the field:

```ts
// packages/shared-schemas/src/domain.ts:63
sexualOrientation: z.array(z.string()).nullable().default(null),
// packages/shared-schemas/src/domain.ts:78 (seed default)
sexualOrientation: ["Heterosexual"],
```

- `services/automation-python/tests/test_answers.py` — table-driven tests via
  `@pytest.mark.parametrize("label,field_type,expected_value,expected_review,expected_source", [...])`
  against a module-level `PROFILE` fixture dict. The fixture's
  `equalEmploymentDefaults` currently has keys `gender`, `lgbtq`, `veteran`,
  `race`, `hispanicOrLatino`, `disability`, etc. — it does **not** yet contain
  `sexualOrientation`.

Convention: rules are matched by `alias in label` substring checks on the
lowercased label; EEO answers always return `requires_review=True`.

## Commands you will need

| Purpose | Command (run from repo root `C:\Jobs\Codex\applyocalypse`) | Expected on success |
|---------|------------------------------------------------------------|---------------------|
| Targeted tests | `services\automation-python\.venv-build\Scripts\python.exe -m pytest tests/test_answers.py -q` (cwd: `services/automation-python`) | all pass, exit 0 |
| Full Python suite | `pnpm test:python` | 243+ passed, exit 0 |

If `.venv-build` does not exist, run `node scripts/dev/ensure-python-env.mjs` from the repo root first.

## Scope

**In scope** (the only files you should modify):
- `services/automation-python/applyocalypse_automation/answers.py`
- `services/automation-python/tests/test_answers.py`

**Out of scope** (do NOT touch, even though they look related):
- `packages/shared-schemas/src/domain.ts` — the schema already has the field; no change needed.
- The `requires_review` flag on any EEO answer — it must stay `True` unconditionally.
- Any other rule in `_EEO_RULES` or the address/name/criminal blocks.

## Git workflow

- Branch: work directly on the current branch unless the operator says otherwise.
- Commit message style (conventional commits, matches `git log`): `fix: route sexual-orientation questions to sexualOrientation profile field`

## Steps

### Step 1: Split the sexual-orientation rule from the LGBTQ rule

In `answers.py`, change the last entry of `_EEO_RULES` from:

```python
    (("lgbtq", "sexual orientation"), "lgbtq"),
```

to two entries, with sexual orientation FIRST (so a label containing both
phrases resolves to the orientation value):

```python
    (("sexual orientation", "sexualorientation"), "sexualOrientation"),
    (("lgbtq",), "lgbtq"),
]
```

Do NOT add a bare `"orientation"` alias — labels like "orientation date" or
"new-hire orientation" would false-positive.

**Verify**: `services\automation-python\.venv-build\Scripts\python.exe -m pytest tests/test_answers.py -q` (cwd `services/automation-python`) → existing tests still pass (the old combined rule's lgbtq-label cases must still resolve to the `lgbtq` value).

### Step 2: Render list values as comma-joined strings in the EEO loop

In the EEO matching loop (excerpt above), replace:

```python
            raw = eeo.get(eeo_key)
            value = str(raw) if raw is not None else None
```

with:

```python
            raw = eeo.get(eeo_key)
            if isinstance(raw, list):
                value = ", ".join(str(v) for v in raw) if raw else None
            else:
                value = str(raw) if raw is not None else None
```

**Verify**: same pytest command → still passing.

### Step 3: Add test cases

In `tests/test_answers.py`:

1. Add `"sexualOrientation": ["Heterosexual"]` to the `equalEmploymentDefaults`
   dict inside the module-level `PROFILE` fixture.
2. Add parametrized rows (match the existing tuple shape
   `(label, field_type, expected_value, expected_review, expected_source)`):
   - `("How would you describe your sexual orientation?", "select", "Heterosexual", True, "PROFILE")`
   - `("Sexual Orientation", "select", "Heterosexual", True, "PROFILE")`
   - A row asserting the LGBTQ question still works:
     `("Do you identify as LGBTQ+?", "select", "No", True, "PROFILE")`
3. Add one non-parametrized test for the list-join behavior: temporarily build
   a profile where `sexualOrientation` is `["Heterosexual", "Prefer not to say"]`
   and assert `proposed_value == "Heterosexual, Prefer not to say"` and
   `requires_review is True`.

**Verify**: `services\automation-python\.venv-build\Scripts\python.exe -m pytest tests/test_answers.py -q` → all pass, including the 4 new cases.

## Test plan

- New cases listed in Step 3, in `tests/test_answers.py`, following the
  existing parametrize table pattern at the top of that file.
- Verification: `pnpm test:python` from repo root → exit 0, total test count
  increases by 4.

## Done criteria

- [ ] `pnpm test:python` exits 0; 4 new test cases pass
- [ ] `grep -n "sexual orientation" services/automation-python/applyocalypse_automation/answers.py` shows the alias only in a rule mapping to `sexualOrientation`, not `lgbtq`
- [ ] All EEO answers still return `requires_review=True` (covered by existing + new tests)
- [ ] No files outside the in-scope list modified (`git status`)
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report back (do not improvise) if:

- `_EEO_RULES` at `answers.py:102` does not match the excerpt (drift).
- The Python-side canonical profile uses a different key than
  `sexualOrientation` under `equalEmploymentDefaults` (check `_eeo()` in
  answers.py and one fixture in `tests/` to confirm the nesting).
- Any pre-existing test in `test_answers.py` fails after Step 1 for a reason
  other than the lgbtq/orientation split.

## Maintenance notes

- If new multi-valued EEO fields are added to the schema (arrays), the Step 2
  list-join handles them automatically; single-valued fields keep `str()`.
- Reviewer should scrutinize: the rule ORDER (sexualOrientation before lgbtq)
  and that no EEO branch can ever return `requires_review=False`.
- Deferred (out of scope here, tracked as small cleanups in audit): adding
  "employed by"/"employed with" aliases to the previously-employed matcher.
