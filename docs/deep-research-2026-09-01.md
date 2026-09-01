# Applyocalypse: Deep Research Report

*Generated: 2026-09-01 · Scope: stealth, speed, tailoring quality, plus free-API sourcing · Confidence: mixed, flagged per claim*

Companion deliverable: `docs/free-apis-research.txt` (~120 APIs, 10 sections, 33 items explicitly marked unverified).

---

## Executive Summary

Five things came out of this that change what should be built next.

1. **Two AGPL-licensed dependencies ship inside the distributed worker binary, and the repo has no LICENSE file.** `nodriver` 0.50.3 is AGPL-3.0 and `PyMuPDF` 1.27.2.3 is "Dual Licensed - GNU AFFERO GPL 3.0 or Artifex". Both are pulled into the PyInstaller bundle. This is verified against installed package metadata, not inferred. It is a decision for you, not a fix I should make unilaterally (§1).

2. **The market is actively repricing application *volume* to zero.** Greenhouse's own numbers: 175k live jobs, ~254 applicants per posting, applications per recruiter up 412%. Alongside that, a Yale study shows cover-letter tailoring lost 51% of its signalling value once AI made it cheap. A human-gated, evidence-first tool is on the right side of this; a bulk auto-applier is not (§2).

3. **The browser was lying to portals in two specific, fixable ways, and both are now fixed.** nodriver dispatched CDP `char` events with no `keydown`, so every Workday/Ashby/iCIMS typeahead silently never opened its listbox: fields looked filled and the answer was never committed. And nodriver picked which Chrome to drive by *shortest file path*, which on this machine selects Chrome Beta over the user's real Chrome. Both shipped this session with 66 tests (§3).

4. **The single largest remaining stealth *and* speed win is the same change: stop creating a fresh Chrome profile per run.** Every run gets `runs/{runId}/browser-profile`, so every run is a first-time visitor with a cold cache and no session history. A leased pool of 3 persistent profiles fixes detection surface, cold-start latency, and re-login UX in one change, and bounds profile storage at 3 directories instead of one per run for 7 days (§3.1, §4.1).

5. **The tailoring pipeline's real risk is not prose quality, it is fabrication reaching a live employer.** The nearest competitor has a 1.7/5 Trustpilot with reviewers quoting shipped output like "The user does NOT require sponsorship". The fix is structural: make the model emit *edits against verbatim source spans*, not prose, and reject any edit whose anchor is not a verbatim substring (§5).

---

## 1. Licensing: an AGPL conflict inside a closed binary

**Verified this session against `importlib.metadata` in the build venv, not taken on trust.**

| Package | Version | License | How it reaches the bundle |
|---|---|---|---|
| `nodriver` | 0.50.3 | GNU Affero GPL | Declared runtime dep (`pyproject.toml`: `nodriver>=0.44`) |
| `PyMuPDF` | 1.27.2.3 | Dual: AGPL-3.0 **or** Artifex commercial | Direct `import fitz` at `validation.py:141`, **and** transitively via `pdf2docx` |
| `pdf2docx` | 0.5.13 | MIT | Declared dep (`pdf2docx>=0.5.8`); hard-depends on PyMuPDF |
| `seleniumbase` | 4.49.13 | MIT | **Already a dependency** |
| `python-docx` | 1.2.0 | MIT | Declared dep |

**The repo has no root LICENSE file.** Confirmed by glob: all 1,627 matches are under `node_modules/` or agent worktrees. With no license, the project is implicitly all-rights-reserved. Distributing a binary that bundles AGPL code while withholding Corresponding Source is the exact conflict AGPL section 13 exists to create.

Three real options:

- **Relicense Applyocalypse AGPL-3.0 and publish Corresponding Source.** Costs nothing in dependencies. Costs the ability to keep the source closed.
- **Buy an Artifex commercial licence for PyMuPDF.** Solves PyMuPDF. Does *not* solve nodriver, which has no commercial option.
- **Replace both.** `seleniumbase` (MIT) is already installed, so the nodriver half is a real choice rather than a dead end. For PDF text, `pdftext` (Apache-2.0) pitches itself explicitly as text extraction like PyMuPDF without the AGPL licence; `pypdf` (BSD) and `pdfplumber` (MIT) also work.

Effort note: the PyMuPDF *direct* coupling is ten lines, entirely inside one function (`extract_pdf_text`, `validation.py:139-151`). The hard half is `pdf2docx`, which is MIT itself but drags PyMuPDF in behind it.

I have not changed any of this. Pick a direction and I will execute it.

---

## 2. Market context: volume is being priced to zero

This reframes the product, so it belongs before the engineering.

- Greenhouse reports **175,000 live jobs** and **~254 applicants per posting**, with **applications per recruiter up 412%** ([Fortune, 27 Jul 2026](https://fortune.com/)). Their response is a "My Dream Job" signal, one role per month a candidate can flag as a priority, which they report converts at roughly **5x the hire rate** of an ordinary application. *(Single-source; Greenhouse is an interested party quoting its own funnel.)*
- Cui, Dias and Ye (Yale, [arXiv:2509.25054](https://arxiv.org/abs/2509.25054), CC BY 4.0) studied an online labour marketplace that shipped an AI cover-letter tool. Difference-in-differences: after launch, the correlation between a cover letter's textual alignment with the job post and getting a callback **fell 51%**. Individual applicants with tool access still got *more* callbacks, but employers adapted by shifting weight onto prior work history, a signal AI cannot manufacture.
- Critically, in the same study **time spent editing the AI draft correlates positively with hiring success.** Unedited model output is a weak signal. That is direct empirical support for the human-in-the-loop gate already in the app, rather than an argument against it.
- The strongest causal evidence on resume improvement is [NBER WP #30886](https://www.nber.org/papers/w30886) (Van Inwegen et al., ~500k job seekers): algorithmic resume refinement produced **8% more hiring, 7.8% more offers, 8.4% higher wages.** Single-digit percentages. Any product claiming 2-3x is not describing this literature.
- The nearest competitor, [usemassive.com](https://www.trustpilot.com/review/usemassive.com), sits at **1.7/5 on Trustpilot across 43 reviews, 77% one-star.** Reviewers document fabricated experience claims, the same job applied to 100+ times, and refund eligibility secretly capped at 50-85 applications. One review quotes shipped output verbatim: *"The user does NOT require sponsorship"*, a template variable leaking to a live employer.

**Read:** the differentiator is not applications per hour. It is that every claim in every artifact is traceable to something the user actually wrote, and that the user saw it before it left the machine.

**Do not ship an "ATS score."** No real ATS (Greenhouse, Workday, Lever, iCIMS) publishes a match score to recruiters. Third-party tools invent a keyword-overlap percentage no recruiter ever sees, and real systems rank *relative to the live applicant pool*, which makes an absolute percentage meaningless. A resume can score 90% on keywords while having its work history parsed scrambled. The defensible feature is **parse verification** ("does your work history survive extraction?") and **keyword gap analysis**, never a number claiming to predict callbacks.

---

## 3. Stealth

### Fixed this session

**3.a  Keystrokes now produce the events widgets listen for.** `commit e59faa5`

nodriver's `Element.send_keys` (0.50.3, `core/element.py:708-720`) calls `focus()` then dispatches exactly one `Input.dispatchKeyEvent(type="char")` per character, with zero delay between them. Chrome converts a `char` event into the text insertion and the following `input` event, but **it never synthesises `keydown` or `keyup`.**

Every typeahead on Workday, Ashby, iCIMS, and every react-select / downshift combobox opens its listbox from an `onKeyDown` handler. So the old path typed into a control whose dropdown never opened, whose option was never selected, and whose answer was therefore never committed. The field looked filled. The application was missing it. This is a correctness bug wearing a stealth bug's clothes.

`clear_input()` was worse: `element.value = ""` executed in the main world, raising no event at all, so a React value tracker never observes the reset and silently restores the old value.

New `human_typing.py` emits `keyDown` (carrying `text`) then `keyUp` per character, which is the Puppeteer/Playwright sequence and produces the full `keydown -> beforeinput -> input -> keyup` chain with `isTrusted: true`, because CDP injects below the JS layer. Clearing uses `dispatchKeyEvent` with `commands: ["selectAll"]` then Delete, which is how both major drivers reach select-all without caring whether the platform modifier is Ctrl or Meta. Prose over 120 chars goes through a single `Input.insertText`: still trusted, still fires `beforeinput`/`input`, and avoids spending a minute on one cover-letter textarea.

Inter-key gaps are drawn from a clamped log-normal, which matters functionally as well as behaviourally: portals debounce typeahead queries at 150-300ms, and a zero-delay burst collapses into one query fired against a half-written prefix.

Keystrokes are sent to `element.tab`, not the top document, so a field inside a cross-origin apply frame receives them in the frame that owns it. 50 tests.

**3.b  The user's real Chrome is now driven.** `commit 972188c`

`find_chrome_executable(return_all=True)` enumerates Chrome stable, Beta and Canary across `PROGRAMFILES`, `PROGRAMFILES(X86)`, `LOCALAPPDATA` and `PROGRAMW6432`, then picks between them with `min(rv, key=lambda x: len(x))`. The comment in nodriver's source is literally *"assuming the shortest path wins"*.

On this machine that is not hypothetical. `C:\Program Files\Google\Chrome Beta\Application\chrome.exe` is 58 characters; `C:\Users\varun\AppData\Local\Google\Chrome\Application\chrome.exe` is 65. A user with a per-user stable install plus a machine-wide Beta gets **Beta driven on their behalf**: wrong profile, wrong cookies, wrong logged-in sessions, and a beta user-agent string that describes a very small population.

New `chrome_discovery.py` ranks candidates by release channel (stable, beta, dev, canary, for-testing, chromium) and breaks ties on discovery order rather than string length. `browser_executable_path=None` is verified to be exactly today's autodetect behaviour (`Config.__init__`: `AUTO = None`, `if not browser_executable_path: ...`), so a future nodriver that moves the helper degrades to the old behaviour instead of failing to launch. 16 tests, including one that asserts the bug's own premise (`assert len(STABLE_PER_USER) > len(BETA)`).

**3.c  Runs no longer arrive as a browser that has never been anywhere.** `commit 23176c2`

`apps/desktop/src/main/scheduler/localQueueScheduler.ts:115` set `runWorkDir = userData/runs/{runId}` and `runner.py:1487,1766` derived `user_data_dir = work_dir / "browser-profile"`, so every run opened a profile directory that had never existed: no history, no cookies, no cached fonts, a first-visit fingerprint, and a person signing in to the same job board again on every application.

New `profile_pool.py` leases one of **3 persistent profiles** (matching `HARD_MAX_CONCURRENT_APPLICATIONS`) for as long as a run holds a browser. A pool rather than one shared directory because Chrome takes an exclusive `SingletonLock` on a user data dir, and a second browser pointed at the same one refuses to start. The lease is an OS file lock rather than a state file because Electron kills a stopped run's process tree with `taskkill /T /F` and nothing gets to run cleanup on the way out: the kernel releases the lock when the process dies, so there is no stale-lock table to reap. The pool root is a sibling of `runs/`, not a child, because `runWorkDirJanitor.ts` sweeps `runs/*` after 7 days. No configured root, or a full pool, falls back to the old run-scoped directory, so a run always gets a browser. 11 tests, including one that kills a child process holding a slot and asserts the slot comes back.

### 3.1  Worked through, in the order they were taken

1. **Our clicks are not trusted clicks.** Correcting an earlier draft of this report: nodriver's `flash_point` DOM marker is **not** in our code path, because `nodriver_adapter.py` never calls `Element.click()`. Every click is injected JavaScript ending in `exact.element.click()` (`field_detection.py:1112-1183`), which is cleaner in one respect and worse in another. It leaves no DOM residue, but the resulting event carries `isTrusted: false`, which is the cheapest check a detector can run. The fix is real CDP `Input.dispatchMouseEvent`, and it is not a small change: `getBoundingClientRect()` inside a cross-origin iframe is frame-local while CDP input is dispatched in the top-level target's coordinate space, so a naive port breaks the OOPIF clicks that commit `6cef0df` exists to make work. It wants a coordinate translation through `DOM.getBoxModel` on the frame owner, and a fixture page to test against. **Shipped in `2db0a58`:** the page measures and reports a target instead of pressing, `_frame_viewport_origin` translates it through the frame owner's box model, `_point_reaches_frame` refuses to press where the top document is not showing the frame, and anything that cannot be aimed falls back to the injected click.
2. **Isolated-world probes.** Every discovery pass runs through main-world `frame.evaluate`, so page script can observe the probe. Read-only probes should go through `Page.createIsolatedWorld`. Also correcting an earlier draft: `allow_unsafe_eval_blocked_by_csp=True` is **not** set by our code. It is hard-coded inside nodriver (`tab.py:895,1065,1076`), and `cdp/runtime.py:1010` documents that it bypasses the page's CSP. That is a reason to prefer an explicitly created isolated world over nodriver's evaluate helper, but it is not a flag we can simply stop passing. The six discovery scripts are pure DOM with no page-global dependencies, so they run unchanged in an isolated world. **Shipped in `b2414f6`:** `isolated_world.py` creates and caches one world per frame, every read-only probe goes through it, and a world that cannot be created loses the stealth and keeps the answer. Writes stay in the main world, because React's value tracker is an own-property override installed there.
3. **Never draw highlight boxes into the live page.** Render them in the Electron renderer over a screenshot instead. **Shipped in `b2414f6`:** a guardrail test scans every browser source for the DOM writes that would paint one, so the first debugging idea anyone has fails in CI rather than in front of a detector.
4. **Guardrail test asserting nothing calls `Network.setUserAgentOverride`.** UA spoofing without matching client hints is a self-inflicted mismatch; a test is cheaper than rediscovering that. **Shipped in `b2414f6`.**
5. **Warm-up navigation** rather than deep-linking cold into an apply URL with no referrer. **Shipped in `15538c5`:** the first navigation to a site the run has not been on lands on that origin's front door, dwells for a log-normal moment and then follows the link. Once per origin per run, and a front door that will not load costs nothing.
6. **Heavy-tailed session pacing and real scrolling** instead of `scrollIntoView()`, which teleports. **Shipped in `3cca7fb`:** the locate script measures and reports how far the page has to move, and the adapter wheels it there with `Input.dispatchMouseEvent` in notches of about one wheel step spaced log-normally, then measures again. Cross-origin frames are aimed through the same box-model translation the click uses, and every way it can fail lands on the injected click that worked before.

> Discarded on source quality: a widely-repeated "70-85% LinkedIn ban rate" figure traces to a single competitor blog with no methodology. It is not repeated here and should not be quoted.

---

## 4. Speed

### 4.1  Ranked, cheapest first

1. **The profile pool above is also the biggest speed win.** A cold Chrome profile means zero HTTP cache, zero compiled-JS cache, and a full TLS plus asset fetch for a Workday SPA on every single run.

   **Shipped in `23176c2`**, as the same change that closes 3.2. A run leases one of three pooled profile directories, sized to the concurrency cap, and the lease is an exclusive OS file lock rather than an entry in a state file, because Electron kills a stopped run's process tree with `taskkill /T /F` and nothing gets to run cleanup on the way out. The kernel drops the lock when the holder dies, so there is no stale-lock table to reap. No pool configured, or every slot busy, falls back to the old run-scoped directory.
2. **Reuse prepared statements in `pythonEventIngest.ts`.** better-sqlite3's own benchmark floor is **62,554 single-row-single-transaction inserts/sec** ([better-sqlite3 benchmark](https://github.com/WiseLibs/better-sqlite3), WAL mode, Node 12, 2014 MacBook Pro, 2020). Statement preparation is the actual per-event cost, not the transaction.

   **Shipped in `f9af045`.** The file called `db.prepare` at 22 sites and every one of them sits inside a per-event handler, so a worker sending a few hundred events for one application recompiled the same handful of queries a few hundred times. They are now cached in a `WeakMap` keyed by connection, so a closed database releases its own statements, and the helper is only ever called with literal SQL, so each connection's map is bounded by the number of queries in the file rather than by how long the app has been running. That is safe here specifically because the file has no `iterate(` call, since a cached statement cannot be reused while one of its iterators is still open, and no template-literal SQL. A guardrail test drives five events that each take the insert branch and asserts the insert and the `MAX(step_order)` lookup are compiled exactly once each. Items 3 and 4 below remain deliberate do-nots.
3. **Do NOT batch the SQLite writes.** better-sqlite3 ships with `SQLITE_DEFAULT_WAL_SYNCHRONOUS=1`, so a WAL database is already at `synchronous=NORMAL`: fsync is off the commit path and only happens at checkpoint. Batching would trade the one-event-one-transaction guarantee (a documented architecture rule) for a win that has already been collected. Corruption is impossible in WAL mode regardless of the synchronous setting; the only exposure is a few milliseconds of recent commits rolling back on power loss.
4. **Do NOT set `page_size=32768`.** Set connection-level pragmas at every open instead; `page_size` only takes effect before the first write and silently does nothing afterwards.
5. **Bundle the Electron main process to a single file**, and lazy-`require` the heavy main-process deps rather than loading them at boot.

   **Already true, verified this session.** electron-vite emits `out/main/index.js` as one 330 KB file. The only dependency left outside it is `better-sqlite3`, which is `external` because it is native, and it is needed on the first line of boot to open the database, so there is nothing to defer. Nothing to do here.
6. **`asarUnpack` the `*.node` natives.** Loading a native module out of an asar archive forces an extract-to-temp on every launch.

   **electron-builder already does this by itself**, and the shipped build proves it: both `better_sqlite3.node` files sit in `app.asar.unpacked`, not in the archive. Adding an `asarUnpack` key would have been a no-op.

   Looking at that directory is what turned up the real defect, which was not speed but size. better-sqlite3 publishes its whole build tree, and electron-builder packages production dependencies whatever `files` says, so each copy shipped `better_sqlite3.iobj` (12.7 MB, an incremental-link object), `better_sqlite3.ipdb` (3.2 MB of incremental debug info), `sqlite3.lib` (6.5 MB), the whole `build/Release/obj` tree, the 9.8 MB sqlite3 amalgamation in `deps/`, and the C++ in `src/`. About 43 MB, of which the app opens exactly one file, the 1.7 MB `.node`. And it shipped **twice**: `packages/db` pins better-sqlite3 at `^11` so vitest can load a Node-ABI build, and that nested copy went into the installer too, despite being compiled against an ABI Electron cannot load. It was unreachable by construction, since the bundled main process resolves its `better-sqlite3` require to the top-level Electron-ABI copy, which is also why the app has always worked. Excluding the build intermediates from the copy that is used, and the whole of the copy that is not, is the change in `439b223`: 257 MB to 240 MB.
7. **`module.enableCompileCache()`** (or `v8-compile-cache`) in main; keep renderer filenames stable so Chromium's URL-keyed disk code cache actually hits across launches.

   **Not worth doing here, for a reason specific to item 5.** The API does exist: Electron 42.3.0 ships Node 24.15.0 and `enableCompileCache` on `node:module` is a function. But the call only caches modules compiled *after* it runs, and calling it from inside main means main has already been compiled. Because main is one bundled file, everything worth caching is in the file doing the calling; what is left to cache is better-sqlite3's 46 KB of JavaScript. Getting the bundle itself cached needs `NODE_COMPILE_CACHE` set before the process starts, which the process cannot do for itself. The renderer half is already satisfied: Vite emits content-hashed asset names, so they are stable across every launch of a given build.
8. **V8 startup snapshots last, if at all.** High complexity, and the payoff only shows up after the cheaper items are done.

### 4.2  Checked and cleared

**`electron.vite.config.ts` has no `build.bytecode` setting.** Verified this session: the file has `rollupOptions` at lines 27, 40 and 59 with `external: ["electron", "better-sqlite3"]` and `external: ["electron"]`, and no bytecode key anywhere.

This matters because bytenode documents a hard `SIGTRAP` / `EXC_BREAKPOINT` abort on Electron >= 42 (V8 >= 14.8) when bytecode is compiled under `ELECTRON_RUN_AS_NODE`: the main process boots V8 from Chromium's `v8_context_snapshot`, whose read-only heap checksum differs from the Node default snapshot, and V8 14.8 aborts rather than failing gracefully. This project is on Electron 42 but does not enable bytecode, so it is not exposed. Worth knowing before anyone turns it on for source protection: bytecode is not encryption, and API keys stay readable inside it.

### 4.3  LLM call path

`litellm_client.py` currently has **no prompt caching**, sends a bare `response_format={"type": "json_object"}` with no schema enforcement (`schema_name` is used only in error strings), and has **no streaming, no retry, and no token or cost accounting**. Prompt caching is the highest-leverage of these, because the system prompt and canonical profile are identical across every application in a batch.

**Shipped in `198a49c`, and the diagnosis above was half wrong.** Measuring the four system prompts first: JD analysis is about 394 tokens, cover letter 438, bullet rewrite 304, tailor 400. Every provider's cache minimum is 1024 tokens or more, so marking the *system* message would have been a silent no-op, no error and no saving. The cacheable bulk is in the user turn.

The real defect was message ordering. Both `resume_tailoring.py` call sites put the job description *before* the resume and before the bullets, so twenty applications in a batch shared no common opening at all and even the providers that cache automatically (OpenAI, Deepseek, recent Gemini) had nothing to reuse. That is a missing-cache bug with no flag to turn on. `complete_json` now takes an optional `cached_prefix`, the stable half goes first, and the breakpoint is added only where litellm's own tables say the provider needs telling (anthropic, bedrock, vertex_ai) and the prefix clears roughly a thousand tokens. Empty prefix reproduces the previous request byte for byte, a custom OpenAI-compatible base never gets `cache_control`, and an unrecognised model id stops being decorated rather than stopping being sent. The cover letter was already ordered correctly and only needed to say where the seam is.

Still open from this section: schema enforcement beyond `json_object`, streaming, a retry policy at the client rather than per caller, and token/cost accounting.

---

## 5. Tailoring

### 5.1  The structural fix: edits, not prose

The failure mode that sank the competitor is not bad writing, it is **fabrication reaching an employer**. Prompt instructions do not prevent this; a schema can.

Make the model return edits against the *existing* document:

```json
{
  "action": "replace",
  "edits": [{
    "replace":      "<verbatim substring of the current resume>",
    "with":         "<new text>",
    "supported_by": ["<verbatim span from the user's own source material>"]
  }]
}
```

Then reject in code, before anything touches a file:

- `replace` is not a verbatim substring of the current document, so reject the edit.
- `supported_by` is not a verbatim span of user-supplied material, so reject.
- An **entity whitelist gate**: any company, product, certification or tool name in `with` that does not appear in the user's own material is rejected.
- **Number monotonicity**: a metric may be rephrased, never inflated.
- **Scope-word gate**: "led", "owned", "architected" cannot be introduced where the source says "contributed to".
- **Template-variable leak guard**: a blocking regex on `the user`, `the candidate`, `{{`, `[insert`, `as an AI`. This is not theoretical; it is the literal string a competitor shipped to a live employer.

This slots alongside the existing banned-word and em-dash gates, which are already blocking and already kept in sync across `packages/validator` and `validation.py`.

**Shipped: the rejection half.** `commit 643b6b1`

The four content gates above now run in code as `tailoring/fabrication.py`, over the original/rewrite pair: a number the original never claimed, a tool that appears neither in the bullet nor anywhere on the master resume, an ownership verb where the original claimed none, and template or prompt scaffolding left in the text. Before this, the only check at the call site (`document_stage.py:614-620`) was banned words and em dashes, so the anti-fabrication rules written into `_BULLET_REWRITE_SYSTEM` were enforced by nothing but the model's compliance with them.

Two design notes. Rejection is per bullet rather than per batch, because `tailor_bullets_1to1` was all-or-nothing and one invented metric threw away the tailoring of every other bullet. And the document stage passes the master resume's own tool names as `known_terms`, because moving a tool the candidate genuinely lists into the bullet a job cares about is the rewrite we want, and only the rest of the resume can tell that apart from an invention. Tool-of-trade conflation is deliberately left to the prompt: separating "Built dashboards using Tableau" from "Built Tableau dashboards" needs to parse the sentence, and a false rejection silently costs the tailoring its point. 37 tests.

**Not shipping the other half, and this is the argument against it.** The proposal was that the model return each edit with a `supported_by` span quoting the user's own material, which we then verify verbatim. Two problems. The citation is supplied by the same model that would be doing the inventing, and the user's material is already in this process, so anything the citation could prove can be checked directly against the source without the model's cooperation; the schema buys nothing the gate cannot already reach.

The deeper problem is that the check it implies is the wrong check. Verifying that new wording traces to a span of the resume means rejecting wording that does not, and adopting the job description's vocabulary for work the candidate genuinely did is not a side effect of tailoring, it is the entire mechanism. A gate at that granularity rejects the product. The case is already in the test suite: `Wrote automated checks that ran on every merge` becomes `Wrote automated regression checks that ran on every merge`, which passes today and is exactly right, and which a span-grounding rule throws out the moment the resume never used the word regression.

What is actually worth stopping is narrower than fabrication in general: a claim the candidate cannot defend in an interview. Those are proper nouns, numbers, and scope, and all three are gated already. Widening from there costs tailoring quality to buy very little safety, so the honest answer is that 5.1 is finished at the rejection half and the schema should not be built.

### 5.2  Parse-back regression testing

A tailored DOCX that no longer round-trips is worse than no tailoring. After every mutation, re-extract and assert the section structure survived.

This matters most for Workday, which reads **strictly top-to-bottom, left-to-right**: right-column content in a two-column layout is frequently lost entirely, and table-based layouts misassign fields, with employer names concatenating with dates from adjacent rows and roles vanishing when cells are skipped. Contact details in a header or footer rather than the body are commonly missed. DOCX parses more consistently than PDF there because Word XML exposes paragraph styles and heading levels, whereas PDFs exported from Canva, InDesign or Figma store text as vector paths and routinely come out in the wrong order. *(Vendor and practitioner blog sources only: directionally consistent across several, but no primary Workday documentation. Treat as strong prior, not fact.)*

The same class of bug is well documented in the open. OpenResume has 57 open non-PR issues, including [#174](https://github.com/xitanggg/open-resume/issues/174) (section detection breaks when a section starts on a new page), [#145](https://github.com/xitanggg/open-resume/issues/145) and [#68](https://github.com/xitanggg/open-resume/issues/68) (**cannot parse PDFs its own builder exports**, open since 2023), [#115](https://github.com/xitanggg/open-resume/issues/115) and [#108](https://github.com/xitanggg/open-resume/issues/108) (LinkedIn-exported PDFs fail), and [#106](https://github.com/xitanggg/open-resume/issues/106) (spacing dropped between words). If OpenResume's algorithm is used as a reference, these are the regression tests to write first.

**Shipped, and it found a live defect on the way in.** `commit ede22bf`

The bug was upstream of the round-trip. `collect_tailorable_bullets` and `mutate_docx_paragraphs` both indexed `document.paragraphs`, which is the body only, while `iter_document_paragraphs` in the same file walks table cells too and is what text extraction and anchor repair already used. So the two-column layouts this section is about did not merely parse badly downstream: they collected zero bullets, fell through the `nothing to change` branch, copied the master through and reported success as *Kept your original resume formatting (no bullets needed changes)*. A green checkmark and an untailored resume, on a class of template that is everywhere. Both sides now address one order, body first and then table cells, deduplicated because a merged cell is returned once per grid column it spans.

The round-trip check itself is cheaper than section-structure re-extraction and catches the failure that actually exists here. Rewriting a bullet redistributes its text across the paragraph's existing runs, which is how the font and the bullet glyph survive, and it is also where a character is lost at a run boundary or a space disappears from a `w:t` that lost its `xml:space`. The written file is read back and compared against what was asked for, paragraph by paragraph; any mismatch copies the master through untouched and reports zero tailored. Fail-closed is the right default because the damage is asymmetric: an untailored resume the user recognises costs them one application's edge, and a mangled one costs them the application.

### 5.3  Ask the ATS for the form instead of guessing

Greenhouse exposes the full application schema **unauthenticated**:

```
GET https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs/{job_id}?questions=true
```

Live-tested against the GitLab board: 13 questions returned with no auth, covering `first_name`, `last_name`, `email`, `phone`, `resume` (both `input_file` *and* `textarea`), `cover_letter`, LinkedIn URL, preferred name, employment-agreements yes/no, accessibility adjustments, visa sponsorship yes/no, and prior-employment yes/no. Field types observed: `input_text`, `input_file`, `textarea`, `multi_value_single_select`.

Two consequences:

- The form is knowable **before a browser launches**: faster, quieter, and far more reliable than DOM discovery.
- The EEOC-adjacent blocks arrive pre-labelled, which lets safety invariant #2 (EEO, criminal-history and previous-employer answers are always `requires_review=True`) be enforced *structurally* rather than by string matching.

Two caveats to write into the adapter: Greenhouse does **not** reject applications missing required fields on API submit, so client-side validation is mandatory; and Harvest API v1/v2 were retired **31 Aug 2026**, so the Job Board API is the supported path.

Also worth building: **template lint** against Greenhouse's documented parse-failure list, and a **per-application submission receipt** so a user can prove what was sent.

### 5.4  Libraries worth adopting

- **[JSv4/Docxodus](https://github.com/JSv4/Docxodus)** (MIT, C# core, actively maintained, last push 2026-09-01) with its Python client `docx-scalpel`. Stateful DOCX editing sessions, regex search and replace across the whole document, tables, headers and footers, and native tracked-changes redlines via `python-redlines`. The .NET binary is prebuilt into the wheel, so end users install no SDK. Beta wheels for win-x64, linux-x64, osx-arm64.
- **[dolanmiu/docx](https://github.com/dolanmiu/docx)** patcher, for the technique if not the dependency: a START/MIDDLE/END state machine replaces tokens that span multiple `w:r` runs, deep-cloning `w:rPr` so both halves of a split run keep their formatting, and patching `xml:space="preserve"` onto the tail. This is the correct way to edit a resume in place without destroying its typography.
- **Local embeddings**, if semantic matching is wanted without an API call: `FastEmbed` (BGE-small-en-v1.5, 384-dim, quantised ONNX, fully offline after first fetch) on the Python side; `@huggingface/transformers` at `dtype:'q8'` on the Node side, **not** `int8`, whose `ConvInteger` op fails under `onnxruntime-node`. Both produce compatible 384-dim vectors. Smallest meaningful model is Snowflake Arctic Embed S int8 at **34MB**; note BGE-small is 133MB, 47% *larger* than all-MiniLM-L6-v2's 90MB despite the name.

> **Licensing traps in this space.** Every TechWolf HuggingFace model (JobBERT-v3 at ~49.5k downloads/month, JobBERT-v2, ConTeXT-Skill-Extraction) and all 14 TechWolf datasets publish **license: None**, meaning copyright retained and no commercial use without permission. Same for the `jjzha` skill datasets. The only permissively licensed option found is [kris927b/SkillSpan](https://github.com/kris927b/SkillSpan) (MIT). Separately, `nestauk/ojd_daps_skills` is MIT but pins `torch<2.0.0`, which supports only Python 3.7-3.10 and is unusable in this 3.12 worker without an isolated venv.

---

## 6. Free APIs

Full deliverable in **`docs/free-apis-research.txt`**. Headlines relevant to this app:

| Source | Terms | Verdict |
|---|---|---|
| **Greenhouse Job Board API** | No auth for reads; live-verified | **Use it.** Best available (§5.3) |
| **Jobicy** `/api/v2/remote-jobs` | No auth, no key, CORS-enabled, up to 200 jobs, no documented rate limit | Use it. Fetch taxonomy slugs dynamically, they change |
| **O\*NET Web Services** | Free with a prominent attribution link; throttles above **5 req/s or 50,000 req/day**; paid apps need written permission unless a free tier exists | Fine for on-demand lookups, not bulk |
| **Adzuna** | ~1,000 calls/month; commercial use is a **14-day evaluation trial only**, ongoing use needs written consent | **Avoid** for a commercial product |
| **Groq** | `gpt-oss-120b`/`20b` at 30 RPM / 1,000 RPD, no card | Strong free LLM tier |
| **Google Gemini** | 2.5 Flash 15 RPM / 1,500 RPD; Flash-Lite 30 RPM / 1,500 RPD; Pro 5 RPM / 50 RPD | Strong, but free-tier prompts may be used to improve Google products |
| **Mistral free mode** | ~1 RPS / 500K TPM | Prompts may train Mistral unless opted out |
| **Cloudflare Workers AI** | 10,000 Neurons/day, 75+ models | Good fallback |
| **Cohere trial** | 1,000 calls/month, labelled non-commercial | Not viable here |

**Privacy footnote that matters for a job-application tool:** Groq's privacy policy (effective 12 Nov 2025) *explicitly excludes* API prompts and responses, stating the policy does not apply to information processed as a data processor on behalf of customers. Prompt handling is governed by the Groq Services Agreement and DPA instead. Cite the right document when telling users where their resume goes.

**Local inference**, for users who want nothing to leave the machine: Ollama supports true JSON-schema structured outputs via `format`, **local only, since hosted Ollama Cloud does not support it**. Microsoft Foundry Local (`winget install Microsoft.FoundryLocal`, `pip install foundry-local-sdk`, Python 3.11+) is the Windows alternative worth knowing, because it auto-selects NPU, then DirectML GPU, then CUDA, then CPU, and therefore covers AMD and Intel integrated GPUs that Ollama's CUDA path misses. Public preview; API may change.

---

## 7. Key Takeaways

1. **Decide the licence.** AGPL exposure is verified and it blocks a clean public release. Relicense, buy Artifex and drop nodriver, or replace both. Nothing else in this report is blocked on it, but a release is.
2. **Build the profile pool next.** One change, four wins: stealth, cold-start latency, re-login UX, and bounded profile storage.
3. **Make tailoring emit verbatim-anchored edits.** Reject in code, not in the prompt. This is the difference between the app and a 1.7-star competitor.
4. **Query Greenhouse's schema API before launching a browser**, and use its labelled EEOC blocks to enforce the review gate structurally.
5. **Never ship an ATS score.** Ship parse verification instead.
6. **Add a packaged smoke test that exercises a browser adapter.** `scripts/test/packaged-worker-smoke.mjs` currently asserts only `RUN_STARTED`, `JD_ANALYSIS_COMPLETED`, `RESUME_RENDERED`, `PAUSED`. No packaged test touches any browser adapter, which is structurally why a Playwright import bug survived into a shipped build. This gap is the meta-finding of the whole audit.

---

## 8. Gaps and source-quality caveats

Stated plainly rather than buried:

- **Workday parser behaviour (§5.2) is vendor-blog sourced only.** Several independent practitioner accounts agree, but there is no primary Workday documentation. Strong prior, not fact.
- **The "70-85% LinkedIn ban rate" figure is excluded.** One competitor blog, no methodology.
- **Tsenta AI has no independent evidence**: no third-party reviews, no technical writeups. The documented benchmark for resume-first onboarding is **Simplify**: upload, parse, *explicit review-and-edit*, then a Profile Strength checklist. Note the parse step should be replace-with-diff, not append-only.
- **Greenhouse's funnel statistics come from Greenhouse**, an interested party.
- **electron-vite's exposure to the bytenode SIGTRAP bug is inference**, not confirmed; the two use the same compilation strategy. Moot here, because bytecode is off.
- **Agent output files were empty on disk.** These findings were recovered from the durable observation store, and every load-bearing claim about this repository was re-verified directly against source this session.
- Several arXiv identifiers cited by upstream agents were not individually spot-checked; arXiv:2509.25054 was.

---

## 9. Methodology

Five parallel research agents (stealth; desktop and Electron speed; tailoring plus competitor teardown plus ports-to-adopt; free-API sourcing; resume-parser reality check) across web search, GitHub code search, package registries, vendor documentation and live API probes. Roughly 30 distinct sources reached the report.

Sub-questions investigated:

1. How does a modern bot detector distinguish this browser from a person's?
2. Where does a run's wall-clock actually go?
3. What makes tailored output trustworthy rather than merely fluent?
4. Which job-data and LLM APIs are genuinely free for a commercial desktop product?
5. What do the best-known open resume parsers still get wrong?

Every claim about *this repository*, including file paths, line numbers, dependency versions, licences and config settings, was verified directly against the working tree or installed package metadata during this session rather than accepted from an agent report.
