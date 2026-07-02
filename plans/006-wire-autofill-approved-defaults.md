# Plan 006: Wire the automation.autofillApprovedDefaults setting end to end (UI toggle → SQLite → worker env → answer proposals)

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 224c6f5..HEAD -- apps/desktop/src/main/ipc/registerIpc.ts apps/desktop/src/main/scheduler/localQueueScheduler.ts apps/desktop/src/renderer/screens/SettingsScreen.tsx services/automation-python/applyocalypse_automation/runner.py services/automation-python/applyocalypse_automation/answers.py`
> Plans 001/002/003/005 touch some of these files in OTHER regions. Re-confirm
> the excerpts below against live code; unexplained mismatch is a STOP condition.

## Status

- **Priority**: P2
- **Effort**: M
- **Risk**: LOW (defaults to off — behavior unchanged unless the user opts in)
- **Depends on**: none (but if plan 005 landed, the scheduler env block looks slightly different; the new env var here is a non-secret flag and stays in providerEnv)
- **Category**: bug (planned feature never wired; opt-in autofill is always off)
- **Planned at**: commit `224c6f5`, 2026-06-11

## Why this matters

`propose_answer_for_detected_field(autofill_approved_defaults=...)` exists and
is fully respected inside `answers.py` (address fields, first/last name,
LinkedIn/GitHub links auto-approve when the flag is true). But the only call
site never passes it, there is no SQLite setting, and no env plumbing — so it
is permanently `False`. Users must manually review every address and name
field on every application. This plan wires the opt-in path the master plan
specified. EEO/criminal/previous-employer answers are structurally unaffected:
they return `requires_review=True` unconditionally.

## Current state

- Python flag exists and is honored —
  `services/automation-python/applyocalypse_automation/answers.py:113-119`:
  ```python
  def propose_answer_for_detected_field(
      *,
      field_label: str,
      field_type: str,
      canonical_profile: dict[str, Any],
      autofill_approved_defaults: bool = False,
  ) -> ProposedApplicationAnswer:
  ```
- The only call site never passes it —
  `services/automation-python/applyocalypse_automation/runner.py:374-388`:
  ```python
  def proposed_answer_for_browser_field(field: BrowserField, canonical_profile: dict[str, object]) -> ProposedApplicationAnswer:
      if is_password_field(field) and os.getenv("APPLYO_APPLICATION_PASSWORD"):
          ...
      return propose_answer_for_detected_field(
          field_label=field.label,
          field_type=field.field_type,
          canonical_profile=canonical_profile,
      )
  ```
- Settings update handler uses a strict allowlist —
  `apps/desktop/src/main/ipc/registerIpc.ts:186-209`:
  ```ts
  handleContract(IpcContracts.settingsUpdate, ({ patch }) => {
    for (const [key, value] of Object.entries(patch)) {
      if (key === "automation.maxConcurrentApplications") { ...clamped integer... continue; }
      if (key !== "files.outputDir") {
        throw new Error(`Unsupported setting key: ${key}`);
      }
      ...
  ```
- Scheduler env construction —
  `apps/desktop/src/main/scheduler/localQueueScheduler.ts:152-171`: builds
  `providerEnv` (a `Record<string, string>`) and reads settings via
  `new SettingsRepository(this.db).get(key, default)` (exemplar at lines 76-85,
  `configuredMaxConcurrentApplications`).
- Renderer settings flow — `apps/desktop/src/renderer/contexts/SettingsStore.tsx:113`:
  ```ts
  const settings = await window.applyocalypse.settings.update({ 'automation.maxConcurrentApplications': value })
  ```
  and `SettingsScreen.tsx:53` reads
  `state.settings['automation.maxConcurrentApplications']`. The preload
  `settings.update` accepts an arbitrary patch record (preload/index.ts:46-49) —
  no preload change needed.
- Python tests — `tests/test_answers.py` already covers the flag's effect on
  answers (parametrized rows note "review depends on autofill flag").

## Commands you will need

| Purpose | Command (repo root) | Expected on success |
|---------|---------------------|---------------------|
| Typecheck | `pnpm typecheck` | exit 0 |
| TS tests | `pnpm test` | all pass |
| Python tests | `pnpm test:python` | all pass |

## Scope

**In scope**:
- `apps/desktop/src/main/ipc/registerIpc.ts` (settingsUpdate allowlist branch)
- `apps/desktop/src/main/scheduler/localQueueScheduler.ts` (env flag)
- `apps/desktop/src/renderer/screens/SettingsScreen.tsx` (toggle UI)
- `services/automation-python/applyocalypse_automation/runner.py` (pass the kwarg)
- `services/automation-python/tests/test_answers.py` or a small new test (env parse helper)

**Out of scope** (do NOT touch):
- `answers.py` answer logic — the flag semantics there are already correct and
  test-covered. In particular do NOT change the unconditional auto-approve of
  email/phone/legalName (`non_review_keys` block) — unifying that under this
  setting changes today's default UX and is explicitly deferred.
- EEO/criminal/previously-employed branches — must stay `requires_review=True`.
- `packages/ipc-contracts` — settingsUpdate already accepts a generic patch.

## Git workflow

- Commit message: `feat: wire automation.autofillApprovedDefaults setting end to end`

## Steps

### Step 1: Allow the key in settingsUpdate

In `registerIpc.ts`, inside the settingsUpdate loop (excerpt above), add a
branch BEFORE the `if (key !== "files.outputDir")` rejection, matching the
maxConcurrentApplications branch style:

```ts
if (key === "automation.autofillApprovedDefaults") {
  if (typeof value !== "boolean") {
    throw new Error("autofillApprovedDefaults must be a boolean");
  }
  settingsRepository.set(key, value);
  continue;
}
```

**Verify**: `pnpm typecheck` → exit 0.

### Step 2: Scheduler passes the flag as env

In `localQueueScheduler.ts`, inside `startClaimedItem` where `providerEnv` is
finalized (after the credentials block, before `supervisor.start`), add:

```ts
const autofillDefaults = new SettingsRepository(this.db).get("automation.autofillApprovedDefaults", false);
if (autofillDefaults === true) {
  providerEnv = { ...(providerEnv ?? {}), APPLYO_AUTOFILL_APPROVED_DEFAULTS: "1" };
}
```

(Reuse an existing `SettingsRepository` instance if one is already in scope in
that method — line 152 constructs one for `files.outputDir`; prefer reusing it.)

**Verify**: `pnpm typecheck` → exit 0; `pnpm test` → green.

### Step 3: Runner reads the env and passes the kwarg

In `runner.py`, change `proposed_answer_for_browser_field` (excerpt above) to:

```python
return propose_answer_for_detected_field(
    field_label=field.label,
    field_type=field.field_type,
    canonical_profile=canonical_profile,
    autofill_approved_defaults=os.getenv("APPLYO_AUTOFILL_APPROVED_DEFAULTS") == "1",
)
```

**Verify**: `pnpm test:python` → green.

### Step 4: Settings UI toggle

In `SettingsScreen.tsx`, add a toggle row to the existing automation section
(near the maxConcurrent control around line 221). Follow the screen's existing
control idioms (`classList={{ active: ... }}` buttons). Read state via
`state.settings['automation.autofillApprovedDefaults'] === true`; write via the
SettingsStore — add a store method modeled exactly on the
maxConcurrentApplications updater at `SettingsStore.tsx:113`:

```ts
const setAutofillApprovedDefaults = async (value: boolean) => {
  const settings = await window.applyocalypse.settings.update({ 'automation.autofillApprovedDefaults': value })
  // apply to state the same way the sibling updater does
}
```

Label the toggle: "Autofill approved defaults (name, address, links) without
review". Add helper text: "EEO and sensitive questions always require review."

**Verify**: `pnpm typecheck` → exit 0.

### Step 5: Tests

1. Python: in `tests/test_answers.py` (or `tests/test_runner_args.py` if more
   natural), add a test that monkeypatches
   `APPLYO_AUTOFILL_APPROVED_DEFAULTS=1` and asserts
   `proposed_answer_for_browser_field` returns `requires_review=False` for an
   address-line field with a populated profile, and `requires_review=True` for
   an EEO field (gender) with the SAME env set. Import the function from
   `applyocalypse_automation.runner`; build a `BrowserField` the way existing
   runner tests do (grep `BrowserField(` in `tests/` for the constructor shape).
2. TS: if `registerIpc` settings handling has existing tests (grep
   `settingsUpdate` in `apps/desktop/src/**/*.test.ts`), add a case: boolean
   accepted, non-boolean rejected. If no such test file exists, skip (the
   allowlist branch mirrors a tested pattern) and say so in the commit message.

**Verify**: `pnpm test:python` and `pnpm test` → green, new tests included.

## Test plan

Covered in Step 5. The critical assertion is the EEO invariance: with the env
flag ON, gender/race/veteran/etc. proposals still come back
`requires_review=True`.

## Done criteria

- [ ] `pnpm typecheck`, `pnpm test`, `pnpm test:python` all exit 0
- [ ] `grep -n "autofill_approved_defaults=os.getenv" services/automation-python/applyocalypse_automation/runner.py` → one match
- [ ] `grep -n "automation.autofillApprovedDefaults" apps/desktop/src/main/ipc/registerIpc.ts apps/desktop/src/main/scheduler/localQueueScheduler.ts apps/desktop/src/renderer/screens/SettingsScreen.tsx` → matches in all three
- [ ] New Python test proves EEO stays review-required with the flag on
- [ ] No files outside the in-scope list modified (`git status`)
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report back if:

- The settingsUpdate allowlist structure has changed (drift).
- `proposed_answer_for_browser_field` has gained an `autofill` argument already
  (someone wired it concurrently) — reconcile instead of duplicating.
- Any test shows an EEO/criminal/previously-employed answer with
  `requires_review=False` under the flag — that is a safety regression; stop.

## Maintenance notes

- Deferred on purpose: unifying the unconditional email/phone/legalName
  auto-approve under this same setting (changes default UX; needs a product
  decision).
- If plan 005 (secrets file) landed first, this flag still belongs in
  providerEnv (it is not a secret).
- Reviewer should scrutinize: default-off behavior (no setting row → flag
  absent → kwarg False) and the boolean type guard in settingsUpdate.
