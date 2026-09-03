# Portal Filling Audit

Scope: `services/automation-python/applyocalypse_automation/browser/**`, `field_resolution.py`,
`answers.py`, `runner.py`, `tests/`. Read-only audit, 2026-07-27. Line numbers are as-of this
working tree (branch `chore/audit-and-reskin-2026-07`).

## Verdict

The filling pipeline is a single generic label-text heuristic wearing 26 portal names: there is not
one portal-specific selector anywhere in the worker (the only hardcoded selectors in the entire
`browser/` package are Cloudflare challenge markers at `browser/field_detection.py:206`). Field
discovery is limited to `input, textarea, select` in the top document's light DOM
(`browser/field_detection.py:91`) and silently discards anything without a resolvable label
(`browser/field_detection.py:142`), which means Workday's ARIA comboboxes, Ashby's and Greenhouse's
react-select widgets, and every iframe-embedded Greenhouse/Lever board are invisible to the worker —
it will report "0 fields" or a partial set and never know it was wrong. There is no post-write
verification anywhere (`browser/field_detection.py:504`), so `FIELD_VALUE_APPLIED` is an assertion
about a JS return value, not about the page. The specific failure you named,
`"Final submit approval was received, but no exact final submit control could be clicked"`
(`runner.py:202`), has two independent causes that I traced end to end: (a) the loop **abandons
wizard progression and jumps to the final-submit gate** whenever a required field could not be
filled twice in a row (`runner.py:1833`, `runner.py:1960-1961`), so the click lands on page 1 of a
multi-page form where no submit button exists; and (b) even on the real last page, `runner.py:195`
passes a hardcoded module-level label list (`runner.py:39-45`) instead of the per-portal list
`final_submit_labels_for_workflow` (`browser/portal_adapters.py:250`) that is defined and unit-tested
but **never called from `runner.py`**, and the matcher requires an exact normalized string match
(`browser/field_detection.py:612`). Two of the findings below are not even news to the codebase:
`browser/portal_workflows.py:158` states `"Workday React fields ignore set-value; fill with real
keystrokes."` and `:159` states `"Yes/No dropdowns reorder per question; select by type-ahead text,
never by position."` — both describe defects that are still present, because that table is inert prose
emitted in an event and nothing acts on it. My honest assessment: this pipeline can complete a
hand-written ideal HTML form (which is precisely what its fixtures are) and would need real work
before it reliably completes a live Workday, Greenhouse, or iCIMS application.

## Coverage matrix

"Selectors" means portal-specific field selectors. There are none, for any portal — see the grep
result above. "Tests" means tests that exercise that portal specifically. "Adapter" is
`PortalDefinition.default_adapter` (`portal_registry.py:17-42`); note that **every one of the six real
ATSes defaults to `playwright`**, whose method bodies have zero executable test coverage — the single
playwright test (`tests/test_portal_registry.py:391`) early-returns when playwright *is* installed, so
on any dev machine it asserts nothing at all.

> **Update.** This understated the problem. Playwright is not installed *anywhere*: it is absent from
> `requirements.in`, from the lock file, from `pyproject.toml` and from the packaged worker's hidden
> imports. So the declared default could never launch, and every ATS run silently fell back to nodriver.
> All defaults are now `nodriver`. Read the "Adapter" column below as "was playwright"; the correction
> at row 9 has the details and the guard that stops it recurring.
>
> **Second update, `d680eaa`.** The adapter is installed now. Its driver is Patchright, a drop-in
> fork of Playwright with the automation tells patched out of the driver itself, and it is in
> `requirements.in`, in the lock, in the PyInstaller bundle and required by `self-check`. The
> defaults stay `nodriver`, but the fallback chain is `nodriver -> playwright -> seleniumbase` for
> every portal, because the playwright adapter can enumerate frames and write inside the one that
> owns a field and seleniumbase cannot. `tests/test_portal_registry.py` no longer has a test that
> asserts nothing when the driver is present: the early-return case is the absent-driver case now.

| Portal | Registered | Adapter | Workflow | Selectors | Tests | Genuinely usable? | Notes |
|---|---|---|---|---|---|---|---|
| workday | `portal_registry.py:37` | playwright | `ATS_DIRECT_FORM`, entry actions `portal_workflows.py:41` | none | ideal-HTML replay fixture `tests/test_portal_replay_fixtures.py:23-40` | **Partial** | ARIA comboboxes are now discovered and safely handled (`69c898f`); they were previously invisible. Still uncertified against a live posting, and the account-creation wall remains unhandled. Was: real Workday uses `data-automation-id` ARIA comboboxes, not `select`, so discovery could not see them. The repo's own quirk note says so (`portal_workflows.py:158-159`). Also an account-creation wall before the form, unhandled. |
| greenhouse | `portal_registry.py:38` | playwright | `ATS_DIRECT_FORM`, `portal_workflows.py:42` | none | ideal-HTML fixture `tests/test_portal_replay_fixtures.py:42-52` | **No** | Most Greenhouse boards are `<iframe id="grnhse_iframe">` embeds on the employer domain; `field_detection.py:91` never enters the iframe. Quirk note acknowledges the host handoff (`portal_workflows.py:170-172`) but nothing acts on it. |
| lever | `portal_registry.py:39` | playwright | `ATS_DIRECT_FORM`, `portal_workflows.py:43` | none | ideal-HTML fixture `tests/test_portal_replay_fixtures.py:58-68` | **Partial at best** | Closest to plausible: Lever's hosted form is largely native inputs with `<label for>`, and playwright's `.fill()` is framework-safe. But the repo's own note says hCaptcha intercepts checkbox/radio clicks (`portal_workflows.py:161-163`) and nothing enforces that. Unverified live. |
| ashby | `portal_registry.py:40` | playwright | `ATS_DIRECT_FORM`, `portal_workflows.py:44` | none | ideal-HTML fixture `tests/test_portal_replay_fixtures.py:74-85` | **Partial** | The Ashby custom listbox widgets are now discovered, and rendered options are selectable (`69c898f`). Still uncertified against a live posting. Was: not `select`, so invisible. |
| icims | `portal_registry.py:41` | playwright | `ATS_DIRECT_FORM`, `portal_workflows.py:45` | none | ideal-HTML fixture `tests/test_portal_replay_fixtures.py:91-104` | **No — provably broken** | See F7: its declared labels make it unable to either progress *or* submit. |
| taleo | `portal_registry.py:42` | playwright | `ATS_DIRECT_FORM`, `portal_workflows.py:46` | none | ideal-HTML fixture `tests/test_portal_replay_fixtures.py:107-120` | **No** | Taleo career sections are frameset/iframe-based and heavily multi-step with per-page validation. |
| usajobs | `portal_registry.py:25` | playwright | `ATS_DIRECT_FORM`, `portal_workflows.py:48` | none | none | **No** | No adapter plan (`ATS_ADAPTER_PLANS` has 6 keys, `portal_adapters.py:98`) → generic fallback plan, `live_certification_status="REQUIRES_PORTAL_SPECIFIC_ADAPTER"` (`portal_adapters.py:226-243`). USAJobs hands off to agency systems entirely. |
| governmentjobs | `portal_registry.py:26` | playwright | `ATS_DIRECT_FORM`, `portal_workflows.py:47` | none | none | **No** | Same generic fallback. NEOGOV requires an account. |
| ncs | `portal_registry.py:36` | nodriver | `ATS_DIRECT_FORM`, `portal_workflows.py:49` | none | none | **No** | Same generic fallback. |
| indeed | `portal_registry.py:17` | nodriver, high-stealth | `JOB_BOARD_REDIRECT_OR_STEALTH`, `portal_workflows.py:60` | none | generic job-board replay `tests/test_portal_replay_fixtures.py:204` | **No** | Indeed Apply is an overlay iframe; also the most aggressively bot-defended surface in the list. |
| linkedin | `portal_registry.py:27` | nodriver, high-stealth | `portal_workflows.py:62` | none | none | **No** | Easy Apply is a modal wizard with `artdeco` custom controls; requires an authenticated session the worker has no flow for. |
| glassdoor | `portal_registry.py:18` | nodriver, high-stealth | `portal_workflows.py:57` | none | none | **No** | Entry-click only. |
| ziprecruiter | `portal_registry.py:19` | nodriver, high-stealth | `portal_workflows.py:69` | none | none | **No** | Entry-click only. |
| dice | `portal_registry.py:20` | nodriver, high-stealth | `portal_workflows.py:54` | none | none | **No** | Entry-click only. |
| wellfound | `portal_registry.py:21` | nodriver, high-stealth | `portal_workflows.py:68` | none | none | **No** | Entry-click only. |
| otta | `portal_registry.py:22` | nodriver, high-stealth | `portal_workflows.py:65` | none | none | **No** | Entry-click only. |
| careerbuilder | `portal_registry.py:23` | nodriver, high-stealth | `portal_workflows.py:53` | none | none | **No** | Entry-click only. |
| monster | `portal_registry.py:24` | nodriver, high-stealth | `portal_workflows.py:63` | none | none | **No** | Entry-click only. |
| naukri | `portal_registry.py:28` | nodriver, high-stealth | `portal_workflows.py:64` | none | none | **No** | Entry-click only; requires login. |
| instahyre | `portal_registry.py:29` | nodriver, high-stealth | `portal_workflows.py:61` | none | none | **No** | Entry-click only; requires login. |
| hirist | `portal_registry.py:30` | nodriver, high-stealth | `portal_workflows.py:58` | none | none | **No** | Entry-click only. |
| iimjobs | `portal_registry.py:31` | nodriver, high-stealth | `portal_workflows.py:59` | none | none | **No** | Entry-click only. |
| foundit | `portal_registry.py:32` | nodriver, high-stealth | `portal_workflows.py:55` | none | none | **No** | Entry-click only. |
| shine | `portal_registry.py:33` | nodriver, high-stealth | `portal_workflows.py:66` | none | none | **No** | Entry-click only. |
| timesjobs | `portal_registry.py:34` | nodriver, high-stealth | `portal_workflows.py:67` | none | none | **No** | Entry-click only. |
| freshersworld | `portal_registry.py:35` | nodriver, high-stealth | `portal_workflows.py:56` | none | none | **No** | Entry-click only. |

Honest summary of the matrix: **26 registered portals, 6 with an adapter plan
(`portal_adapters.py:98-220`), 0 with portal-specific selectors, 6 with an idealized offline HTML
fixture, 0 with any evidence of a completed live application, and 0 executed lines of the adapter that
all 6 ATSes actually use.** `browser/portal_workflows.py:164-166`
carries a quirk note for `workable`, which is not in `PORTALS` at all, so it is unreachable dead
data — a good illustration of the gap between the registry and reality.

Missing major ATSes (each is a distinct DOM the pipeline has never seen): SAP SuccessFactors, Oracle
Recruiting Cloud / iRecruitment, Workable, SmartRecruiters, Jobvite, BambooHR, JazzHR, Breezy,
Recruitee, Teamtailor, Pinpoint, Rippling, Dover, Ripplematch, ADP Recruiting, UKG/UltiPro,
Paylocity, Paycom, Bullhorn, Avature. Between them these cover a large share of mid-market and
enterprise postings.

> **Status (registration done).** 18 of those 20 are now in `PORTALS`, with matching
> `ATS_ENTRY_ACTIONS` and quirk notes; the registry is 44 portals. Dover and Ripplematch are
> deliberately still out, because I could not confirm the hosts their postings are actually served
> from and a wrong domain is worse than none. `_LOGIN_WALLED_PORTALS` now drives
> `requires_login_watch` and covers the eight enterprise suites that gate the form behind a candidate
> account, so a run that lands on a sign-in screen hands the page back instead of reporting an
> application with no fields. The `workable` quirk note is no longer dead data.
>
> **What registration does and does not buy.** It stops an ordinary ATS form from falling through to
> `GENERIC_REVIEW_FIRST` — Nodriver, high stealth, and no field detection at all until the user
> confirms the page. It does not add portal-specific selectors, and it does not move any of these off
> `FILL_CAPABILITY_UNPROVEN`: they get the conservative generic plan, every review gate, and the
> submit gate. The rest of this matrix's honesty still stands — none of these has a completed live
> application behind it. `tests/test_ats_registry_coverage.py` pins the routing, the unchanged gates,
> and a domain-collision guard (`detect_portal` returns the first match, so an overlap would silently
> pick a winner by tuple order).

## Findings

### F1. Wizard progression is abandoned and the run jumps to final submit on page 1 [CRITICAL]

**Where:** `runner.py:1833`, `runner.py:1960-1961`, `runner.py:2010-2019`, `runner.py:195`

**What:** In the fill loop, step progression is attempted only inside
`if not missing_required_documents and not missing_required_answers:` (`runner.py:1833`). Any
required field the worker could not fill — because discovery never saw it (F3), because its label was
unresolvable (F4), or because the profile has no value for it — lands in
`missing_required_answers` (`runner.py:1794-1795`). The first time, the run pauses with
`FIELD_REVIEW_REQUIRED` (`runner.py:1912-1955`). If the resume brings no *new* missing key
(`runner.py:1908-1911`), the next pass hits:

```python
1960:        if missing_required_answers and not missing_required_documents:
1961:            break
```

`break` exits the loop entirely and falls straight through to `READY_TO_SUBMIT`
(`runner.py:2010`) and then `click_final_submit` (`runner.py:195`).

**Why it breaks a real application:** On any multi-page form (Workday, Taleo, iCIMS, Greenhouse
multi-section) the very common case is "page 1 has one field I can't fill". The worker then never
clicks Next, never sees pages 2..N, and asks the DOM for a final-submit button on a page whose only
control is "Next" — producing exactly `FINAL_SUBMIT_CONTROL_NOT_FOUND` (`runner.py:203`). The user
sees "approval received but nothing could be clicked" and has no signal that the real problem was an
unfilled field three steps earlier. Worse: if the user *does* fill the leftover field by hand in the
visible browser (which the comment at `runner.py:1957-1959` explicitly invites), the loop has already
`break`ed, so their input is never re-detected and progression still never happens.

**Fix direction:** Do not treat "cannot fill everything on this page" as "done with the form".
Separate the two states: (a) page-level completion → progress; (b) form-level completion → submit.
Only allow the final-submit gate when the current page actually presents a final-submit control
(probe for it before emitting `READY_TO_SUBMIT`), otherwise re-detect and re-loop. When the user
resumes from `FIELD_REVIEW_REQUIRED`, always re-detect and re-evaluate rather than comparing against
`presented_missing_answer_keys` alone.

### F2. Final submit ignores the per-portal label list and requires an exact match [CRITICAL]

**Where:** `runner.py:39-45`, `runner.py:195`, `browser/portal_adapters.py:250`,
`browser/field_detection.py:595`, `browser/field_detection.py:612-617`

**What:** `perform_final_submit_with_control` calls

```python
195:    result = await adapter.click_final_submit(list(FINAL_SUBMIT_LABELS))
```

with the module-level constant `FINAL_SUBMIT_LABELS = ("Submit", "Submit application", "Send
application", "Finish application", "Complete application")` (`runner.py:39-45`). The per-portal
accessor `final_submit_labels_for_workflow` (`portal_adapters.py:250`) exists, returns the plan's
real labels, and is asserted by `tests/test_portal_registry.py:257` — but grep shows it is referenced
**only** in `portal_adapters.py:250` and `tests/test_portal_registry.py:17,257`. It is never called
from `runner.py`. The matcher then does exact normalized set membership:

```js
595:  const requested = new Set(labels.map(normalize).filter(Boolean));
612:    .filter((entry) => requested.has(entry.normalized));
613:  if (matches.length === 0) {
617:      message: 'no exact final submit control was found',
```

**Why it breaks a real application:** Any real button text outside those five strings fails. Real
examples: "Submit Application" is fine (case-normalized), but "Submit Profile" (iCIMS, declared at
`portal_adapters.py:184`), "Submit my application", "Apply", "Send", "Submit and finish", "I certify
and submit", or a button whose accessible name includes a trailing icon-text are all misses. The user
has approved the submit — the highest-friction moment in the product — and the run dies there.

**Fix direction:** Pass `final_submit_labels_for_workflow(workflow)` (merged with the generic list)
at `runner.py:195`. Add a scored fallback: if no exact match, look for a single visible
`type="submit"` inside the form containing the fields we filled, or a unique candidate whose
normalized label starts with a submit verb — and surface it as a *confirmation* to the user rather
than clicking blind, so the no-auto-submit invariant is preserved.

### F3. Field discovery cannot see iframes, shadow DOM, or ARIA widgets [CRITICAL]

**Where:** `browser/field_detection.py:91`

**What:** Discovery is one query in one document:

```js
91:  const elements = Array.from(document.querySelectorAll('input, textarea, select'));
```

No `iframe` traversal, no `shadowRoot` walk, no `[role="combobox"]`, `[role="listbox"]`,
`[aria-haspopup="listbox"]`, `[contenteditable]`, or `[role="radiogroup"]`.

**Why it breaks a real application:**
- **Greenhouse and Lever embeds.** The canonical Greenhouse integration is an iframe on the employer
  careers page. The worker sees zero fields, `observe_portal_page_state` sees
  `multiple_fields_detected=False`, and the run pauses or falls through with nothing filled.
- **Workday.** Country, phone country code, "How did you hear about us", source, degree, and every
  yes/no compliance question are custom `data-automation-id` buttons that open popup listboxes.
  None are `select`. The worker fills name/email and treats the rest as missing → F1 fires.
- **Ashby / modern React ATSes.** Same, via react-select.
- **Rich-text cover-letter boxes** are `contenteditable` divs, not `textarea`, so "paste cover letter
  inline" silently does nothing.

**Fix direction:** Recursive discovery across `document`, all same-origin frames, and open shadow
roots; extend the selector set to ARIA widget roles and `[contenteditable]`; give each discovered
field a frame path so the adapters can re-enter the right frame to write. This is the single largest
functional gap.

> **F3 status (2026-09-01).** Closed in four pieces. ARIA widget roles shipped in `69c898f`;
> cross-origin iframes in the nodriver frame port; same-origin iframes and open shadow roots in
> `a66d223`; `[contenteditable]` rich-text editors in `a753401`. Discovery now sweeps the top
> document, every frame worth scanning, and every open shadow root, and each field records the
> path back so the adapters re-enter the exact root to write. The rich-text case needed more than
> a selector: Quill and ProseMirror keep their own document model and treat the DOM as a
> projection, so the write goes through `execCommand('insertText')` rather than assigning
> `textContent`, which the editor would simply repaint over.

### F4. Fields without a resolvable label are silently dropped [CRITICAL]

**Where:** `browser/field_detection.py:117-130`, `browser/field_detection.py:142`

**What:** The label chain is `label[for]` → ancestor `<label>` → `aria-label` → `name` →
`placeholder` → `id` (`field_detection.py:117-130`), and then:

```js
142:    if (!label) continue;
```

Missing from the chain: `aria-labelledby`, `<legend>` of the enclosing fieldset, `title`,
`aria-describedby`, and the extremely common ATS pattern of a sibling `<div>`/`<span>` label that is
not a `<label>` element at all.

**Why it breaks a real application:** A dropped field is not merely unfilled — it is *invisible*, so
it never appears in `missing_required_answers` either, which means the user is never told about it and
never gets a chance to fill it. The portal then rejects the submit with its own "this field is
required", which the worker cannot read (F6). Combined with F1, one `aria-labelledby`-only required
input is enough to kill the run.

**Fix direction:** Add `aria-labelledby`, enclosing `legend`, `title`, and a bounded
nearest-preceding-text-node heuristic to the chain. Do **not** `continue` on empty label: emit the
field with `label=""`, low confidence, and a distinct reason code so the UI can ask the user. The
`"Unlabeled field"` fallback already exists at `field_detection.py:355-356` but is unreachable
because of line 142.

### F5. Values written by the injected script do not register with React/Vue-controlled inputs [CRITICAL]

**Where:** `browser/field_detection.py:383-386`, `:442-443`, `:463-464`, `:490-491`, `:501-504`

**What:** Every write is a direct property assignment followed by two bubbling events:

```js
383:  const dispatchChange = (element) => {
384:    element.dispatchEvent(new Event('input', { bubbles: true }));
385:    element.dispatchEvent(new Event('change', { bubbles: true }));
386:  };
```

used by `element.value = partial.option.value` (`:442`), `element.checked = desired` (`:463`),
`match.checked = true` (`:490`), and `element.value = reviewedValue` (`:502`). There is no use of the
native prototype descriptor setter, no `focus`/`blur`, and no `keydown`/`keyup`.

React installs an instance-level `value`/`checked` accessor (`trackValueOnNode`) whose setter updates
its own cached value before delegating to the native setter. A direct `element.value = x` therefore
updates React's cache to `x`, and React's `updateValueIfChanged` check then sees no difference and
**discards** the synthetic change event. The standard workaround is
`Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(el, v)` before
dispatching; it is absent here.

**Why it breaks a real application:** On React-based portals the control shows the new value visually
but component state never updates, so on submit the framework sends the *old* (empty) value and/or
the field's own validator reports it as untouched/required. The highest-impact instances are consent
and EEO checkboxes (`:463`) and native `<select>` answers on Greenhouse/Lever (`:442`) — a ticked-but-
not-registered "I agree" checkbox blocks the submit with no diagnosable cause.

Note on scope, so this is not overstated: for **text** fields none of the three adapters reaches this
script at all — `apply_field_value` routes only `{select, checkbox, radio}` to the JS
(`nodriver_adapter.py:170`, `playwright_adapter.py:187-195` [routing check], `seleniumbase_adapter.py:249`).
So `field_detection.py:501-504` is effectively dead for nodriver and playwright, and the React
problem here bites **select, checkbox, and radio** on all three adapters.

**Fix direction:** In `build_apply_field_value_script`, write through the native prototype descriptor
setter for `value` and `checked`, and dispatch `focus` → input/change → `blur`. Add `option.selected`
alongside `element.value` for `<select>`.

### F6. Nothing verifies that a value actually landed, and portal validation errors are never read [HIGH]

**Where:** `browser/field_detection.py:504`, `runner.py:1797-1820`, `runner.py:1148-1244`

**What:** The script returns `{ok:true, action:'set_value'}` (`field_detection.py:504`) immediately
after assignment — it never re-reads `element.value`, never checks `element.validity`, and never
looks for `aria-invalid`, `[role="alert"]`, or the portal's own error text. `runner.py:1798-1820`
converts that into `FIELD_VALUE_APPLIED` with severity INFO. `attempt_safe_step_progression`
(`runner.py:1148-1244`) checks blockers after the click (`runner.py:1191`) but never checks whether
validation errors appeared or whether the page content actually changed.

**Why it breaks a real application:** Every failure mode in F3/F4/F5 is *silent*. The event log says
the field was applied; the portal disagrees. The run then either submits an incomplete application or
dies at the submit gate with a misleading reason. A user watching the UI has no way to tell which of
40 fields is the problem.

**Fix direction:** After each write, read the value back in the same script and compare (normalized);
return `ok:false` with `expected`/`actual` on mismatch. After each progression click, scan for
`[aria-invalid="true"]`, `[role="alert"]`, and known error class text, and pause with the extracted
messages instead of pressing on.

### F7. iCIMS can neither advance a step nor submit [HIGH]

**Where:** `browser/portal_adapters.py:183-184`, `browser/field_detection.py:524-532`,
`browser/field_detection.py:550`, `browser/field_detection.py:612`

**What:** The iCIMS plan declares:

```python
183:        step_progression_labels=("Next", "Continue", "Save and Continue", "Review", "Submit Profile"),
184:        final_submit_labels=("Submit Profile", "Submit application"),
```

`"Submit Profile"` as a *progression* label is filtered out by `isFinalSubmitLike`, which rejects any
normalized label starting with `submit ` (`field_detection.py:527`, applied at `:550`). And
`"Submit Profile"` as a *final submit* label never reaches the matcher because of F2 — `runner.py:195`
passes the hardcoded list. So the one label iCIMS actually needs is blocked on the progression path
and never requested on the submit path.

**Why it breaks a real application:** iCIMS applications terminate on a "Submit Profile" button. This
is a guaranteed dead end, not a probabilistic one.

**Fix direction:** Fix F2 (pass the per-portal labels). Keep the `isFinalSubmitLike` guard on the
progression path — it is a correct safety measure — but stop declaring final-submit labels in
`step_progression_labels`; that mixing is what makes the plan data self-contradictory.

### F8. The default adapter appends to existing field contents instead of replacing them [HIGH]

**Where:** `browser/nodriver_adapter.py:160-167`, `browser/nodriver_adapter.py:170-171`

**What:** nodriver is the default adapter for 24 of 26 portals (`portal_registry.py:17-42`) and the
first candidate for ATS workflows (`adapter_factory.py:36-41`). Its `apply_field_value` routes every
non-`{select,checkbox,radio}` field to `fill_field`:

```python
170:        if field.field_type not in {"select", "checkbox", "radio"}:
171:            return await self.fill_field(field, value)
```

and `fill_field` types without clearing:

```python
166:        await element.send_keys(value)
```

The other two adapters do clear: `seleniumbase_adapter.py:241-242` (`el.clear(); el.send_keys(...)`)
and `playwright_adapter.py:181` (`.fill()`, which replaces).

**Why it breaks a real application:** Every prefilled field is corrupted. This is the normal state on
a real portal: Workday prefills from the parsed resume before you reach the form; iCIMS prefills from
the account you just created; returning-candidate flows prefill everything; browsers autofill
name/email/phone. Result: `[email protected]@example.com`, `AlexAlex Rivera`, phone numbers of
20 digits — which then fail the portal's own format validation, unreadably (F6). This is a
three-line fix with outsized impact.

**Fix direction:** Clear before typing in `nodriver_adapter.fill_field` (select-all + delete, or set
`.value=''` through the native setter first, then type). Then add a cross-adapter contract test that
asserts replace-not-append semantics for all three implementations.

### F9. `<select>` option matching is bidirectional-substring and can select the wrong answer [HIGH]

**Where:** `browser/field_detection.py:424-443`

**What:** After an exact attempt (`:424-426`), the fallback accepts a match in *either* direction:

```js
430:      return (label && (label.includes(normalizedReviewedValue) || normalizedReviewedValue.includes(label)))
431:        || (value && (value.includes(normalizedReviewedValue) || normalizedReviewedValue.includes(value)));
```

then takes the **first** such option (`.find`), writes `element.value` without setting
`option.selected`, and does not verify (`:442-443`).

**Why it breaks a real application:** `normalizedReviewedValue.includes(label)` is the dangerous
direction: a reviewed value of `"No, I do not require sponsorship"` matches the option `"No"` — but it
equally matches an earlier option whose label is `"o"`-containing, and in practice matches whichever
compliance option happens to appear first. `"India"` matches `"Indiana"`. `"Master of Science"`
matches `"Master"` and also `"Science"`. Concretely: a work-authorization or sponsorship dropdown
answered *incorrectly* is worse than not answered — it is a knockout answer submitted under the
user's name. Note that `answers.py` correctly review-gates knockout *text* (`answers.py:286+`), but
that protection does not extend to which option this matcher picks once a value is approved.

**Fix direction:** Rank candidates (exact → startsWith → label-contains-value only) and require a
unique winner; if two or more options tie, return `ok:false` with the option list and let the run
pause for review — consistent with the existing ambiguity guard used for clicks
(`field_detection.py:560-572`). Set `option.selected = true` and verify after write.

### F10. Drag-and-drop-only upload zones are unsupported, and no adapter waits for the upload to be processed [HIGH]

**Where:** `browser/playwright_adapter.py:223`, `browser/nodriver_adapter.py:209`,
`browser/seleniumbase_adapter.py:286-287`, `runner.py:1714-1789`

**What:** All three implementations require a real, selectable `<input type="file">`:
`set_input_files` (`playwright_adapter.py:223`), `element.send_file(path)`
(`nodriver_adapter.py:209`), `el.send_keys(str(path))` (`seleniumbase_adapter.py:286-287`). Discovery
only finds file inputs that pass the visibility gate at `field_detection.py:138` — and modern ATS
dropzones deliberately hide the input (`opacity:0`, `width:0`, or off-screen) behind a styled div.
After a successful upload the code emits `FILE_UPLOADED` and immediately `continue`s
(`runner.py:1772`, `:1789`) with no settle wait and no re-detect.

**Why it breaks a real application:** Two distinct failures. (a) A hidden-input dropzone means the
resume field is never discovered at all → `REQUIRED_DOCUMENT_MISSING` or, worse, silent omission.
(b) See F11 for what the missing settle wait does on Workday.

**Fix direction:** Relax the visibility gate specifically for `input[type=file]` (accept
zero-size/opacity-0 inputs; they are still settable). Where no input exists, fall back to a synthetic
`DataTransfer` + `drop` event on the dropzone (Playwright and CDP can both do this). Then re-detect
after upload.

> **Status (discovery and the Selenium write are fixed).** The gate in
> `_FIELD_DISCOVERY_BODY_JS` now exempts `input[type=file]`, so a zero-size or
> `display:none` dropzone input is discovered and carries `visually_hidden: true` in its
> metadata; a *disabled* hidden input is still dropped, since nothing can write to it
> either way. Playwright's `set_input_files` and nodriver's `send_file` both go through a
> driver API that ignores visibility and needed no change. Selenium's `send_keys` does
> not, so `seleniumbase_adapter.upload_file` now retries behind a temporary reveal and
> restores the inline style afterwards, on the failure path too — a run that leaves the
> form altered is a run the human reviewer cannot trust. Covered by
> `tests/test_hidden_file_input_discovery.py` (real JS against the DOM stub) and
> `tests/test_seleniumbase_file_upload.py` (fake driver).
>
> The re-detect after upload, the other half of this finding, shipped under F11 —
> see the status block there.
>
> **Still open from this finding:** the synthetic `DataTransfer` + `drop` fallback for a
> dropzone with no `<input type="file">` at all. No evidence yet that a major ATS ships a
> dropzone without a backing input — react-dropzone, which Greenhouse, Lever and Ashby
> build on, always renders one. Left unbuilt deliberately: writing a drop-event path
> against a portal shape nobody has produced would be speculative, and it is the kind of
> code that rots untested. If a real dropzone without an input turns up, this is the fix.

### F11. Workday's resume parse overwrites the fields we just filled, and nothing re-checks [HIGH]

**Where:** `runner.py:1710-1797`, `browser/portal_workflows.py:157-163`

**What:** The fill loop iterates `for field in fields:` in discovery order (`runner.py:1710`),
handling file fields inline (`:1714-1789`) and text fields in the same pass (`:1791-1797`). If the
resume `<input type=file>` precedes the text inputs in the DOM (the normal Workday layout), the upload
fires and then text fields are written *immediately*, while the portal's server-side resume parse is
still in flight. When it returns, Workday repopulates name/email/phone/experience from the parse,
overwriting our values. Nothing re-reads or re-detects: the next `detect_fields` happens only after a
successful progression click (`runner.py:1890`) or an upload retry (`runner.py:1691`). The quirk table
at `portal_workflows.py:157-163` has a Workday entry but it is inert prose (see F13).

**Why it breaks a real application:** The application is submitted with whatever Workday's parser
extracted, not with the user's reviewed answers — which defeats the entire purpose of the review gate.
It also silently reintroduces content the validator was supposed to gate.

**Fix direction:** Order the loop so uploads happen first, then wait for the page to settle
(`wait_for_page_text` already exists and is well-built — `page_readiness.py:40-59`), then re-detect,
then apply text values, then verify. This is the one place a targeted per-portal quirk (Workday) is
genuinely justified.

> **Status: fixed.** `runner.py:2075-2086` splits the discovered fields into uploads and
> everything else and walks `upload_fields + value_fields`, so nothing is typed until every
> file has landed. At the boundary it takes a page fingerprint from before the uploads,
> waits for the form to actually change (`wait_for_portal_page_change`, bounded by
> `RESUME_PARSE_SETTLE_S`), and breaks out of the pass. `restart_after_uploads` then
> `continue`s the outer loop (`:2295`), which re-reads the form from scratch at `:2049`
> because `upload_attempt` was incremented on the way out. So the values written are the
> ones written *after* Workday's parser has had its say, not before.
>
> `uploads_settled` makes this happen once per run rather than once per pass, and
> `uploaded_document_targets` (`:2025`) keeps a restarted pass from attaching the same file
> twice, which matters because Workday's attachment list appends rather than replaces.
> Covered by `tests/test_upload_before_typing.py`.

### F12. Step progression clicks are unverified [HIGH]

**Where:** `runner.py:1148-1244`, `runner.py:1191`, `browser/nodriver_adapter.py:185`

**What:** `attempt_safe_step_progression` clicks a progression label, sleeps a fixed 1.5 s inside the
adapter (`nodriver_adapter.py:185`; `playwright_adapter.py:202`; `seleniumbase_adapter.py:264`), then
checks blockers (`runner.py:1191`) and reports `"advanced"`. It does not confirm the URL changed, the
page text changed, the field set changed, or that no validation error appeared.

**Why it breaks a real application:** A "Next" click that the portal rejected (because of an unfilled
field it can see and we cannot — F3/F4) still reports `"advanced"`. `progression_step_index` increments
(`runner.py:1879`), the same page is re-detected, the same fields are re-filled, and the run burns
through steps until `MAX_AUTOMATED_PORTAL_STEPS` (`runner.py:49`) or breaks out to the submit gate.
The user sees plausible-looking progress events for a form that never moved.

**Fix direction:** Capture a page fingerprint (URL + visible-text hash + field-selector set) before
the click; after `wait_for_page_text`, require it to have changed before returning `"advanced"`,
otherwise return a distinct `"blocked"` state carrying any validation text found.

### F13. Per-portal plan metadata is decorative — it is never evaluated at runtime [MEDIUM]

**Where:** `browser/portal_adapters.py:103,114,124,143,152,162,181,192,202,213,230`,
`browser/portal_workflows.py:156-172`, `runner.py:49`

**What:** `PortalAdapterPlan` carries `max_automated_steps` (per-portal, e.g. `:103`, `:124`),
`evidence_signals=("review_text_detected",)` (`:114,152,192,213`), and `required_review_gates`.
Grep shows `review_text_detected` appears *only* as that literal data — nothing reads it, and there
is no review-page detection anywhere in the worker. `runner.py:49` uses a single global
`MAX_AUTOMATED_PORTAL_STEPS = 20` and never consults the per-portal value. `ATS_PORTAL_QUIRKS`
(`portal_workflows.py:156-172`) is prose emitted in an event, including an entry for `workable`
(`:164-166`) which is not a registered portal.

**Why it breaks a real application:** It creates a false impression — in the code and in the emitted
events — that the worker recognizes a review/confirmation page before submitting. It does not. The
submit gate fires wherever the loop happens to stop (F1), which is why the failure you reported looks
so confusing from the UI side.

**Fix direction:** Either wire the metadata up (implement `review_text_detected` as a real check
against `extract_visible_text` before allowing `READY_TO_SUBMIT`, and use the per-portal step cap) or
delete the fields. Shipping inert safety metadata is worse than shipping none.

### F14. The SeleniumBase Cloudflare auto-solve path is unreachable dead code [MEDIUM]

**Where:** `browser/seleniumbase_adapter.py:44,47,163`, `browser/field_detection.py:700`

**What:** The adapter branches on `_CLOUDFLARE_BLOCKER_TYPE = "CLOUDFLARE_CHALLENGE"`
(`seleniumbase_adapter.py:44`, predicate at `:47`) to call `uc_gui_click_captcha` (`:163`). But
`blockers_from_dom_snapshot` only admits types in
`{"CAPTCHA","MFA","OTP","LOGIN","AMBIGUOUS_QUESTION"}` (`field_detection.py:700`) — the Cloudflare
detection at `field_detection.py:206` reports `blocker_type="CAPTCHA"` with
`metadata.vendor="cloudflare"`. So `_is_cloudflare_blocker` is never true and the auto-solve never
runs.

**Why it breaks a real application:** Cloudflare interstitials on job boards halt the run for manual
intervention even though the capability to clear them exists and was presumably tested.

**Fix direction:** Either match on `metadata.vendor == "cloudflare"` in the adapter, or add
`CLOUDFLARE_CHALLENGE` to the allowed set at `field_detection.py:700` and emit it from `:206`. Add a
test that asserts the emitted blocker actually reaches the adapter's predicate.

### F15. The SeleniumBase readiness probe measures the wrong number [MEDIUM]

**Where:** `browser/seleniumbase_adapter.py:123-130`, `browser/field_detection.py:326-342`,
`browser/page_readiness.py:16`

**What:** `DOM_VISIBLE_TEXT_SCRIPT` returns a JSON **envelope** `{url,title,text,text_length}`
(`field_detection.py:326-342`). The SeleniumBase probe does
`len(str(raw_result or "").strip())` on the raw result (`seleniumbase_adapter.py:123-130`), i.e. it
measures the length of the serialized JSON, not of `text`. The threshold it is compared against is
`PAGE_TEXT_MIN_LENGTH = 200` (`page_readiness.py:16`).

**Why it breaks a real application:** The envelope's URL + title + braces alone routinely exceed 200
characters, so readiness is declared satisfied on a blank or still-loading page. Field detection then
runs against an empty DOM and reports zero fields. Severity is MEDIUM only because SeleniumBase is a
fallback adapter (`adapter_factory.py:29-34`), not the default.

**Fix direction:** Parse the JSON and use `text_length` (or `len(payload["text"])`), matching what
`_probe` does in the other adapters. This is directly unit-testable with a fake driver.

### F16. Fixed sleeps instead of readiness waits after every click [MEDIUM]

**Where:** `browser/nodriver_adapter.py:185,195`, `browser/playwright_adapter.py:202,212`,
`browser/seleniumbase_adapter.py:264,274`

**What:** `click_by_text` sleeps 1.5 s and `click_final_submit` sleeps 2 s, hardcoded, in all three
adapters. `wait_for_page_text` (`page_readiness.py:40-59`) — which is well-designed, injectable, and
tested (`tests/test_page_readiness.py`) — is not used after clicks.

**Why it breaks a real application:** SPA route transitions on Workday and Ashby regularly exceed
2 s on a cold cache. The subsequent `detect_fields` (`runner.py:1890`) then runs against the *old*
page or an empty shell, producing the "0 fields / partial fields" state that triggers F1.
Symmetrically, `perform_final_submit_with_control` reads confirmation text after only 2 s
(`runner.py:217-234`), which is why `SUBMISSION_CONFIRMATION_UNVERIFIED` (`runner.py:236-253`) will
fire on slow-confirming portals even when the submit succeeded.

**Fix direction:** Replace the sleeps with `wait_for_page_text`, and add a change-detection wait
(fingerprint before/after, per F12). Keep a short floor sleep for animation settling.

### F17. Answer-to-field matching is bidirectional substring and can cross-assign values [MEDIUM]

**Where:** `runner.py:874-897` (match at `:889`, fallback at `:891-896`),
`answers.py:204-404`

**What:** `approved_value_for_field` matches an approved answer to a detected field by lowercased
bidirectional substring on the label (`runner.py:889`), with a fallback that accepts any single
approved answer of the same field type when unambiguous (`:891-896`). `answers.py` proposes answers
by the same technique — lowercased-label substring against rule tables (`answers.py:182-201`).

**Why it breaks a real application:** Label collisions are routine on ATS forms: `"Email"` vs
`"Email me about similar jobs"`; `"Phone"` vs `"Phone type"`; `"City"` vs `"City of birth"`; `"Name"`
vs `"Name of referrer"` vs `"Preferred name"`. The `answers.py` code already shows awareness of one
such collision — the comment at `answers.py:241` explains EEO must be checked before address
*because* `"ethnicity"` contains `"city"` — which is evidence the technique is fragile rather than
evidence it is safe. A cross-assigned value is submitted silently (F6). Related gap: there is no
normalization for country names, phone formats, or date formats, all of which real portals validate
strictly.

**Fix direction:** Score matches (exact → token-set → substring) and require a margin; refuse to
apply on a tie and route to review. Anchor the `answers.py` rules on token boundaries rather than raw
`in` checks. Add format normalizers for phone/date/country at the write boundary.

### F18. `live_certification` PASS does not mean a form can be filled [MEDIUM]

**Where:** `browser/live_certification.py:88-176`, `:156-168`, `:46-47`

**What:** `certify_target` checks that the URL maps to the expected portal (`:107-116`), that a plan
exists (`:120-128`), that `FINAL_SUBMIT` is in `required_review_gates` (`:129-138`), and then does a
single HTTP GET, returning `PASS` for any 2xx/3xx (`:156-168`). It never launches a browser, never
detects a field, never fills anything. And `default_targets()` sets `url=None` for all 26 portals
(`:46-47`), so a default run returns `BLOCKED("missing_live_application_url")` for every portal.

**Why it breaks a real application:** It doesn't, directly — but it is why the `live_certification_status`
strings in `portal_adapters.py` should not be read as evidence of usability, and it is presumably why
these portals were believed to work. Calling a 200 OK "certification" of a filling pipeline is the
core of the "domain string in a tuple is not support" problem.

**Fix direction:** Rename the current check to something honest (`reachability_probe`), and build the
real thing on top of `html_replay` (see F19) plus an opt-in live fill-only-no-submit mode gated behind
an env flag, whose PASS criterion is "every required field on page 1 was discovered, written, and
read back correctly".

### F19. Tests validate the happy path only; no test executes the injected JS [MEDIUM]

**Where:** `tests/test_portal_replay_fixtures.py:19-124`, `tests/test_portal_registry.py:188`,
`:339`, `browser/html_replay.py:65`, `browser/html_replay.py:117-124`,
`browser/field_detection.py:117-130`

**What:** Three separate coverage gaps, all verified:

1. **No test ever runs `build_apply_field_value_script`, `build_click_by_text_script`, or
   `build_final_submit_script` in a browser.** `tests/test_portal_registry.py:188` asserts only that
   reviewed values are JSON-embedded in the generated source string;
   `tests/test_portal_registry.py:339` parses a *fabricated* result object. So the select/checkbox/
   radio/value-write logic — F5, F9 — has zero executable coverage.
2. **The replay fixtures are idealized.** Every input in the six ATS fixtures
   (`tests/test_portal_replay_fixtures.py:23-120`) has an explicit `<label for>`, sits in the top
   document, uses native controls, and has no framework. That is exactly the shape the pipeline
   handles; none of F3, F4, F5, F8, F11 can be caught by them.
3. **`html_replay.py` diverges from the live label chain.** Replay resolves labels as
   `aria-label || placeholder || name || id` (`html_replay.py:65`) plus a `label[for]` map applied in
   `finalize_fields` (`:117-124`), whereas the live script prefers `label[for]` → ancestor `label` →
   `aria-label` → `name` → `placeholder` → `id` (`field_detection.py:117-130`). Different precedence
   means a green replay test does not imply the live path produces the same labels — and labels are
   the primary key for answer matching (F17).

**Why it matters:** The suite is large (27 files, ~4.5k lines) and green, which is why these
regressions can persist. It is measuring the wrong surface.

**Can `html_replay.py` base offline fixture tests?** Partially, and it should — but only after fixing
(3). It is the right foundation for **discovery** regression tests: capture real saved HTML from
Workday/Greenhouse/Lever/Ashby/iCIMS/Taleo application pages and assert the expected field set,
including the ARIA/iframe/unlabeled cases. It is structurally **unable** to test value application,
event firing, verification, or clicking, because those live in JS strings that `html.parser` cannot
execute. For those, the right tool is a real headless browser against local fixture pages — the repo
already has Playwright available, so a `tests/browser_e2e/` suite serving static fixture HTML (a
React-controlled form, an iframe embed, an ARIA combobox, a hidden-input dropzone, a prefilled form)
and driving `PlaywrightAdapter` end to end would close the largest gap for modest effort.

### F20. Miscellaneous smaller gaps [LOW]

**Where:** as noted

- **No `<select multiple>` handling.** `field_detection.py:417-451` sets a single `element.value`; a
  multi-select (common for "languages", "locations") gets one value at most.
- **No radio-group discovery as a unit.** Radios are discovered as individual inputs
  (`field_detection.py:91`) and the group is only reconstructed at write time
  (`field_detection.py:468-473`), so the *options* are never surfaced to the review UI. The user
  approves a free-text answer against a set of choices they cannot see, and the bidirectional
  substring at `field_detection.py:479` decides which one it means.
- **`type="date"`/`"number"`/`"tel"` go through the plain typing path** (F8's routing at
  `nodriver_adapter.py:170`) with no format normalization; portal date pickers commonly reject typed
  input.
- ~~**CAPTCHA vendor coverage** is limited to recaptcha/hcaptcha/cloudflare/datadome
  (`field_detection.py:186-215`); Arkose/FunCaptcha, PerimeterX, and Akamai are not detected, so those
  interstitials read as "no fields found" rather than "blocked".~~

  > **Status: fixed**, and the finding understated it. The detector lives at
  > `field_detection.py:641-745` now, not `:186-215`. Arkose and PerimeterX are detected, but chasing
  > vendors one at a time was never going to close this: the list can only ever name the vendors we
  > have already met, and an unrecognised challenge is exactly the case that hurts, because the field
  > scan behind it comes back empty and the run reads the page as "nothing to fill here".
  >
  > So the live script gained the vendor-agnostic backstop its own offline twin already had. The twin
  > (`html_replay._blockers_from_replay_text`) matched "press and hold" -- PerimeterX's challenge --
  > while the browser matched nothing, so the two implementations disagreed about the same page,
  > which defeats the point of the parity suite. Both now read one shared list,
  > `CAPTCHA_CHALLENGE_PHRASES`, interpolated into the injected JS through the same `.replace()` the
  > field-discovery script uses. Anything a challenge tells a person to do stops the run and hands
  > over, whether or not we can name who served it.
  >
  > Vendors are matched on the origin they serve from, never on the element the integrator wrapped
  > them in: Arkose's own setup guide hands the caller a trigger element that "can exist anywhere in
  > your page" and serves its client API from a per-customer subdomain, so `arkoselabs.com` is the
  > stable half and the container id is not.
  >
  > The phrase list is kept free of vendor names on purpose. Matching the word "recaptcha" in page
  > text is the bug that once paused every run against a form whose only captcha was a passive footer
  > badge, so `TestPhrasesCannotNameAVendor` in `tests/test_captcha_detection.py` fails if a vendor
  > name is ever added to it, and re-checks that exact Greenhouse footer sentence against both the
  > twin and a real browser.
  >
  > **Deliberately not covered:** Akamai Bot Manager, whose block page is usually a plain "Access
  > Denied / Reference #" rather than a challenge -- that is a hard block, not something a person can
  > solve, so filing it under CAPTCHA would tell the user the wrong thing. AWS WAF, Imperva and
  > GeeTest are plausible but their selectors could not be confirmed against vendor documentation
  > here, and a guessed selector is worse than a known gap: it reads as coverage while detecting
  > nothing. All four are caught by the phrase backstop when their challenge asks the user to do
  > something, which is the case that matters.
  >
  > Covered by `tests/test_captcha_detection.py` (default gate) and
  > `tests/test_browser_blocker_detection.py` (real Chrome). The second exists because
  > `detect_blockers` swallows every exception and returns `[]`, so a syntax error in the injected
  > script is indistinguishable from a clean page -- the offline twin would keep passing while the
  > shipped detector reported nothing on every page in the world.
- **`field_resolution.py:51` reads `APPLYO_AUTOFILL_APPROVED_DEFAULTS`** to auto-approve defaults. I
  did not trace every path this env var opens; worth confirming it cannot bypass the EEO /
  criminal-history / previous-employer `requires_review=True` invariants (`answers.py:254,270-274,
  277-282`). ~~What would prove it: a parametrized test asserting those three categories stay
  `requires_review=True` with the env var set to `1`.~~

  > **Status: fixed.** That test is `tests/test_runner_autofill_env.py`; the three categories hold
  > `requires_review=True` with the variable set. This bullet outlived the fix.

## Prioritized fix plan

Ordered by expected reduction in real-application failures per unit of effort.

> **Status as of 2026-09-01.** 18 of the 19 rows are struck through, each naming the test
> that pins it. What is genuinely still open is one thing, deliberately so:
>
> - **Row 15, the synthetic `DataTransfer` drop.** Only needed for a dropzone with no
>   backing `<input type="file">` at all, and react-dropzone always renders one.
>
> Closed since the 2026-07-29 revision of this block:
>
> - **Row 9, same-origin iframes and open shadow roots** (`a66d223`). Discovery recurses into
>   `iframe.contentDocument` where the same-origin policy permits it, and into every open
>   `shadowRoot`. Shadow roots were previously called speculative; they were built because the
>   traversal is the same walk as the same-origin frame case, not because an ATS was found
>   using one.
> - **Row 9, `[contenteditable]`** (`a753401`). See the F3 status note above.
> - **Row 16, a fixture-page E2E suite.** It shipped as a real-Chrome suite driven by the
>   adapter that actually ships, rather than by Playwright, which was not installed
>   (`d680eaa` installs it, as Patchright, and puts it back in the fallback chain; the
>   suite still drives nodriver, which is still the adapter tried first):
>   `tests/test_browser_fixture_parity.py` stands the fixture up in real Chrome and asserts
>   that the offline twin in `browser/html_replay.py` agrees with it, field for field.
>
> Struck rows are covered by unit, replay and real-browser tests, not by a live application
> to a real employer. Nothing here moves a portal off `FILL_CAPABILITY_UNPROVEN`.

| # | Fix | Severity | Effort | Files to touch | Test to write first |
|---|---|---|---|---|---|
| 1 | ~~Clear before typing in the default adapter (stop appending to prefilled fields)~~ **(done: `tests/test_adapter_field_write_contract.py`)** | CRITICAL | XS | `browser/nodriver_adapter.py` | Cross-adapter contract test: given a field prefilled with `"old"`, applying `"new"` yields exactly `"new"` — parametrized over all three adapters |
| 2 | ~~Pass `final_submit_labels_for_workflow(workflow)` at the submit call and add a scored fallback with user confirmation~~ **(done: `tests/test_final_submit_gate.py`)** | CRITICAL | S | `runner.py`, `browser/field_detection.py` | `perform_final_submit_*` requests iCIMS's `"Submit Profile"` when the workflow is iCIMS; exact-match miss falls back to a single unique submit-verb candidate and surfaces it for confirmation |
| 3 | ~~Stop jumping to the submit gate from an unfinished wizard page; separate page-complete from form-complete~~ **(done: `tests/test_portal_step_progression.py`)** | CRITICAL | M | `runner.py` | Loop test: page with one unfillable required field + a "Next" button progresses (or pauses) but never emits `READY_TO_SUBMIT` |
| 4 | ~~Read values back and verify after every write; return `ok:false` with expected/actual~~ **(done: `tests/test_field_read_back.py`)** | HIGH | S | `browser/field_detection.py`, `runner.py` | Playwright-driven fixture test: a React-controlled input reports `ok:false` when state did not update |
| 5 | ~~Write through native prototype setters + focus/blur; set `option.selected`~~ **(done: `tests/test_field_write_verification.py`)** | CRITICAL | S | `browser/field_detection.py` | Same Playwright fixture: React controlled `<select>` and consent `<input type=checkbox>` register in component state |
| 6 | ~~Stop dropping unlabeled fields; extend the label chain (`aria-labelledby`, `legend`, `title`)~~ **(done: `tests/test_label_resolution.py`)** | CRITICAL | S | `browser/field_detection.py`, `browser/html_replay.py` (keep chains identical) | Replay test on saved real HTML: an `aria-labelledby`-only required input is discovered with a usable label |
| 7 | ~~Verify progression clicks actually advanced; surface portal validation errors~~ **(done: `tests/test_portal_step_progression.py`)** | HIGH | M | `runner.py`, `browser/field_detection.py` | Fixture test: a "Next" click that the page rejects returns `"blocked"` with the extracted error text, and does not increment the step index |
| 8 | ~~Uploads first → settle via `wait_for_page_text` → re-detect → then text fields~~ **(done: `tests/test_upload_before_typing.py`)** | HIGH | M | `runner.py` | Fixture test emulating Workday: values written after a resume-parse repopulation survive |
| 9 | ~~ARIA widget roles / cross-origin iframes / same-origin iframes / open shadow roots / `[contenteditable]`~~ **(done: `69c898f` ARIA; nodriver frame port for cross-origin; `a66d223` same-origin frames and shadow roots; `a753401` rich text)** | CRITICAL | L | `browser/field_detection.py`, all three adapters (frame-scoped writes), `browser/adapter.py` | Replay + Playwright tests: saved Greenhouse iframe embed yields its fields; a `role=combobox` renders as a selectable field with its options |

> **F9 status (2026-07-29).** The ARIA half shipped in `69c898f`: `role=combobox|listbox|radiogroup`
> and the Workday `aria-haspopup` + `data-automation-id` pickers are discovered, options are harvested
> from `aria-controls`/`aria-owns`, and the write path claims them before the `'value' in element`
> fallthrough so an `<input role="combobox">` can no longer report a false success. A picker whose
> popup was never opened refuses with `requires_human` rather than guessing.
>
> **Correction — the Playwright-only version of this shipped to nobody.** Every ATS in
> `portal_registry.py` declared `default_adapter="playwright"`, and `adapter_candidates_for_workflow`
> put it first. But playwright is not in `requirements.in`, not in the lock file, not in
> `pyproject.toml` and not in the PyInstaller hidden-import list. On a real install
> `create_browser_adapter("playwright").launch(...)` returned `ok=False | playwright is not installed`
> and the run fell through to nodriver silently. Nothing looked broken, which is exactly why it
> survived: the frame work below was never the code any user ran.
>
> The fix was not to add playwright. It ships its own Chromium (~150MB), needs an awkward
> driver-node-binary story under PyInstaller, and its patched Chromium is *worse* against the bot
> detection this app exists to survive — which is why nodriver, which drives the user's real installed
> Chrome, is in the stack at all. So: every ATS default is now `nodriver`, the frame support below was
> ported to `nodriver_adapter.py`, and `test_portal_registry.py` asserts against the **installed
> environment** that every declared default is importable. A default that only works on a developer's
> machine is the failure being pinned, so a comment would not have been enough.
>
> **Coverage difference between the two adapters.** Playwright's `page.frames` enumerates same-origin
> frames too; nodriver reaches frames through Chrome's site isolation, where a cross-origin iframe gets
> its own renderer and its own CDP target and comes back as a connectable `IFrame`. So the nodriver
> port covers out-of-process frames only. That is not a regression: the discovery JS
> (`field_detection.py:255`) is a plain `document.querySelectorAll` that never descends into any
> iframe, so same-origin embeds were already missed by every adapter. It is a separate open gap.
>
> One nodriver-specific hazard: `get_frames()` is rebuilt from `Target.getTargets` on every call and
> does not promise a stable order. The frame **URL** is therefore the key and `frame_index` is only a
> tiebreaker between same-URL frames, and only when it agrees with the URL.
>
> **Cross-origin iframes: done for the Playwright adapter, and now for nodriver.** The Greenhouse `grnhse_iframe` is served
> from `job-boards.greenhouse.io` on an employer domain, so walking `iframe.contentDocument` from the
> injected script never reaches it. `detect_fields` now sweeps the top document plus every subframe
> that could hold form content (`frame_url_is_worth_scanning` skips CAPTCHA, analytics, chat and media
> frames — the CAPTCHA exclusion matters most, since those frames really do contain inputs). Each field
> records where it came from in `metadata.frame_url` / `frame_index`, and its id is frame-qualified
> because discovery restarts its index at zero per frame. Writes, uploads and read-back verification
> all resolve back to the originating frame; when that frame is gone or several frames share its URL
> the adapter **refuses** rather than falling back to the top document, since a wrong-document write
> would look like a success while leaving the real field empty. Clicks try the top document first and
> only then the embedded frames, so a portal that hosts its own form behaves exactly as before.
>
> No protocol change was needed: `BrowserField.metadata` is already `dict[str, Any]`, so only the two
> adapters changed. SeleniumBase never sets frame metadata and keeps its top-frame behaviour.
> `tests/test_nodriver_cross_origin_frames.py` mirrors the Playwright suite against nodriver's shape
> (a fake tab whose `get_frames()` returns fakes carrying a `.target.url`), including the two failures
> that must never be silent: a vanished frame refusing instead of writing to the top document, and
> ambiguous same-URL frames refusing rather than guessing.
>
> **Known limitation:** `_probe_page_fingerprint` stays top-document-only. Making it frame-aware would
> let a transient frame-evaluate failure register as a spurious "page changed" — a false positive in
> the one direction that would wrongly claim a submit worked. Top-only reports "unchanged" on an
> embedded portal, which routes to a human check instead.
>
> **Closed (`a66d223`).** Same-origin iframes and open shadow roots are swept too. The discovery
> script descends into `iframe.contentDocument` where the same-origin policy permits it and into
> every open `shadowRoot`, and each field carries the path back through those hops so a write
> re-enters the exact root the field was found in. The refusal behaviour is unchanged and matters
> more here, not less: a root that has gone away, or a selector that answers in more than one,
> refuses rather than falling back to the top document, because a wrong-document write looks like
> a success while leaving the real field empty.

| 10 | ~~Rank option/answer matching, require a unique winner, pause on ties~~ **(done: `tests/test_select_option_matching.py`)** | HIGH | M | `browser/field_detection.py`, `runner.py`, `answers.py` | Table-driven test: `"India"` does not select `"Indiana"`; `"No, I do not require sponsorship"` does not select the first `"No"`-adjacent option; ambiguous cases return `ok:false` |
| 11 | ~~Replace fixed post-click sleeps with `wait_for_page_text` + change detection~~ **(done: `tests/test_post_click_readiness.py`)** | MEDIUM | S | all three adapters, `runner.py` | Existing `tests/test_page_readiness.py` pattern, extended to the click paths with an injected clock |
| 12 | ~~Fix the SeleniumBase readiness probe to use `text_length`~~ **(done: `tests/test_seleniumbase_readiness_and_cloudflare.py`)** | MEDIUM | XS | `browser/seleniumbase_adapter.py` | Fake-driver test: a page whose visible text is 10 chars is *not* declared ready despite a long JSON envelope |
| 13 | ~~Make the Cloudflare auto-solve path reachable~~ **(done: `tests/test_seleniumbase_readiness_and_cloudflare.py`)** | MEDIUM | XS | `browser/seleniumbase_adapter.py` or `browser/field_detection.py` | Test that a Cloudflare-vendor blocker satisfies `_is_cloudflare_blocker` |
| 14 | ~~Wire up or delete inert plan metadata (`review_text_detected`, per-portal `max_automated_steps`)~~ **(done: `tests/test_portal_plan_metadata.py, tests/test_final_submit_gate.py`)** | MEDIUM | M | `browser/portal_adapters.py`, `runner.py` | Test that `READY_TO_SUBMIT` is not emitted unless a review/confirmation signal was observed |
| 15 | ~~Relax the visibility gate for file inputs~~ **(done: gate exempts file inputs, SeleniumBase reveals before `send_keys`, tests added)**; a true drag-drop event fallback is still open | HIGH | M | `browser/field_detection.py`, `browser/seleniumbase_adapter.py` | Fixture test: an `opacity:0` file input behind a styled dropzone is discovered and receives the file |
| 16 | ~~Build a real fixture suite: saved HTML from the 6 ATSes~~ **(done: `tests/test_portal_replay_fixtures.py`; the injected JS is also executed for real against a Node DOM stub, `tests/js_bridge.py`)** + ~~a fixture-page E2E suite~~ **(done: `tests/test_browser_fixture_parity.py` — real Chrome through the shipping nodriver adapter, asserting the offline twin agrees field for field)** | MEDIUM | L | `tests/` (new `browser_e2e/`), `browser/html_replay.py` (align label chain) | The suite itself — it is what makes fixes 1-15 verifiable and non-regressing |
| 17 | ~~Rename `live_certification` to a reachability probe; define a real fill-only certification~~ **(done: `tests/test_live_certification.py`)** | MEDIUM | S | `browser/live_certification.py`, `browser/portal_adapters.py` | Test that a 200 OK alone cannot produce a "certified" status |
| 18 | ~~Prune or implement: drop `workable` quirk (unregistered) or register Workable~~ **(done: registered, test added)** | LOW | XS | `browser/portal_workflows.py`, `browser/portal_registry.py` | Registry consistency test: every key in `ATS_PORTAL_QUIRKS` and `ATS_ENTRY_ACTIONS` is a registered `portal_id` |
| 19 | ~~Confirm `APPLYO_AUTOFILL_APPROVED_DEFAULTS` cannot bypass the EEO/criminal/prior-employer review gates~~ **(done: `tests/test_runner_autofill_env.py`)** | LOW | XS | `field_resolution.py`, `answers.py` | Parametrized test asserting `requires_review=True` for all three categories with the env var set |
| 20 | ~~Refuse to write a selector that two fields in one document answer to~~ **(done: `tests/test_ambiguous_selectors.py`)** | HIGH | S | `browser/field_detection.py` | Two raw fields carrying `#email`: both must come back with `selector=None` rather than both resolving to the first match |

## What I could not verify, and what would prove it

Stated plainly, because several conclusions above are inferences from code rather than observations of
a live run:

1. **No live portal was exercised.** This audit is static. Every "would break on Workday/Greenhouse/
   Ashby" claim rests on the structure of those portals' DOMs, which I know but did not observe from
   this machine. *Proof:* run the fill flow against one real posting per ATS with
   `APPLYO_WORKER_WAIT_FOR_REVIEW=1` and no auto-submit, and diff the emitted `FIELD_VALUE_APPLIED`
   events against the actual page state at the submit gate.
2. **F5's React mechanism** is correct for React 16+ `trackValueOnNode`. I did not confirm which
   framework each of the 6 ATSes uses on its current application page. *Proof:* the Playwright
   fixture test in row 5 — plus a one-line probe on each live page checking whether the input node has
   an own `value` property descriptor.
3. **F11's field ordering** depends on the resume input preceding text inputs in the DOM, which is the
   usual Workday layout but not guaranteed. *Proof:* log the discovered field order on a live Workday
   page.
4. **`playwright_adapter.py` `apply_field_value` routing** (`:187-195`) I read as select/checkbox/radio
   → JS, text → `.fill()`. `.fill()` is React-safe, so playwright escapes F8 and the text half of F5.
   I am confident in the nodriver and seleniumbase routings (`:170-171` and `:249-250` read verbatim).
6. **Shadow DOM is unmeasured, and piercing it is not the small fix it looks like.** Every discovery
   sweep uses plain `document.querySelectorAll`, which does not cross an open shadow boundary, so a
   form built from custom elements would read as having no fields. The tempting fix, adding shadow
   traversal to discovery, is worse than the gap: discovery emits a CSS selector string and the write
   and verify scripts resolve it with `document.querySelector`, and a selector string cannot cross a
   shadow boundary either. A field found inside a shadow root would come back as `#email`, and that
   lookup would either miss it or, since shadow DOM exists precisely so ids may be reused, land on a
   different element in the light DOM and verify the wrong write as successful. Doing this properly
   means an ordered path of host selectors carried on the field and resolved by one shared walker in
   all three scripts. That is worth building only against a portal known to need it, and I could not
   establish that any registered ATS serves its form this way. *Proof:* on one live posting per ATS,
   evaluate `document.querySelectorAll('*')` filtered to nodes with a non-null `shadowRoot`, and check
   whether any of them contains an `input`, `textarea` or `select`. Registered candidates worth
   probing first are the ones built on component frameworks that own their internals: Oracle
   Recruiting Cloud and SAP SuccessFactors. Note that a closed shadow root is unreachable from page
   script at all, so it would remain a hand-off to the human regardless.

7. **Same-origin iframes fall between the two mechanisms, and the read being easy is a trap.**
   Cross-origin frames are handled: Chrome's site isolation gives each one its own renderer and its
   own CDP target, `nodriver_adapter._embedded_form_frames` collects them from `page.get_frames()`,
   and every field carries a `FrameRef` so the write re-enters the frame it came from. A same-origin
   iframe gets none of that. It shares the parent's renderer, so it is not a separate target and
   never appears in `get_frames()`, and the discovery script only ever queries `document`
   (`field_detection.py:256`), which does not descend into `contentDocument`. A form served that way
   reads as a page with no fields, which is the same silent outcome as the cross-origin case before
   it was fixed. The trap is that same-origin makes the read look free, since
   `iframe.contentDocument` is right there: adding that walk to discovery alone would produce fields
   whose selectors resolve against the wrong document. Discovery emits a CSS selector string, and
   `document.querySelector` in the verify and apply scripts cannot cross a frame boundary any more
   than it can cross a shadow boundary, so `#email` would either miss or land on a same-named input
   in the parent and verify the wrong write as successful. Native typing has the same problem one
   level down: all three adapters resolve an element handle per frame. This wants exactly what item 6
   wants, an ordered path carried on the field and resolved by one shared walker, which argues for
   doing both at once rather than either alone. *Proof:* the pattern that produces it is an employer
   reverse-proxying the ATS onto its own hostname rather than embedding the vendor's, so probe
   `careers.*` domains that serve a known ATS's markup from a first-party path, and on each evaluate
   `Array.from(document.querySelectorAll('iframe')).map(f => { try { return [f.src,
   f.contentDocument && f.contentDocument.querySelectorAll('input,textarea,select').length]; }
   catch (e) { return [f.src, 'cross-origin']; } })`. Any row with a number rather than
   `'cross-origin'` is a form this worker currently cannot see.

5. **Test coverage claims** are based on enumerating `def test_*` across `tests/` and grepping for the
   script builders. I did not run the suite. *Proof:* `pnpm test:python` plus
   `pytest --cov=applyocalypse_automation.browser --cov-report=term-missing`, which would put a number
   on how much of `field_detection.py` is actually executed (my expectation: the JS string bodies
   register as covered because they are module-level string constants, which is itself misleading).
