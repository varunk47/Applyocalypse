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

### 3.1  Still open, in priority order

1. **Persistent profile pool (highest value).** `apps/desktop/src/main/scheduler/localQueueScheduler.ts:115` sets `runWorkDir = userData/runs/{runId}`; `runner.py:1487,1766` derive `user_data_dir = work_dir / "browser-profile"`. Every run is therefore a brand-new browser with no history, no cookies, no cached fonts, and a first-visit fingerprint: the single loudest signal available to a bot detector, and the reason the user re-authenticates every time. Fix: a pool of **3 persistent profiles** (matching `HARD_MAX_CONCURRENT_APPLICATIONS`), leased per run and returned on completion. A pool rather than one shared dir because Chrome's `SingletonLock` will not tolerate two processes on one profile. It also bounds profile storage: `runWorkDirJanitor.ts` already sweeps `runs/*` older than 7 days at app start, so the current growth is capped rather than unbounded, but a week of per-run profiles is still far more disk than three pooled directories. The pool must live outside `runs/` so that janitor does not delete it.
2. **Stop injecting DOM markers.** nodriver's `flash_point` inserts a visible marker element into the live page before clicks. That is DOM residue a detector reads directly. Replace with a mouse trail into the element's own box.
3. **Isolated-world probes.** Every discovery pass currently runs through main-world `frame.evaluate`, and the adapter still passes `allow_unsafe_eval_blocked_by_csp=True`. Together those are the live brotector-class exposure: page script can observe the probe, and the CSP override is itself anomalous. Read-only probes should go through `Page.createIsolatedWorld`.
4. **Never draw highlight boxes into the live page.** Render them in the Electron renderer over a screenshot instead.
5. **Guardrail test asserting nothing calls `Network.setUserAgentOverride`.** UA spoofing without matching client hints is a self-inflicted mismatch; a test is cheaper than rediscovering that.
6. **Warm-up navigation** rather than deep-linking cold into an apply URL with no referrer.
7. **Heavy-tailed session pacing and real scrolling** instead of `scrollIntoView()`, which teleports.

> Discarded on source quality: a widely-repeated "70-85% LinkedIn ban rate" figure traces to a single competitor blog with no methodology. It is not repeated here and should not be quoted.

---

## 4. Speed

### 4.1  Ranked, cheapest first

1. **The profile pool above is also the biggest speed win.** A cold Chrome profile means zero HTTP cache, zero compiled-JS cache, and a full TLS plus asset fetch for a Workday SPA on every single run.
2. **Reuse prepared statements in `pythonEventIngest.ts`.** better-sqlite3's own benchmark floor is **62,554 single-row-single-transaction inserts/sec** ([better-sqlite3 benchmark](https://github.com/WiseLibs/better-sqlite3), WAL mode, Node 12, 2014 MacBook Pro, 2020). Statement preparation is the actual per-event cost, not the transaction.
3. **Do NOT batch the SQLite writes.** better-sqlite3 ships with `SQLITE_DEFAULT_WAL_SYNCHRONOUS=1`, so a WAL database is already at `synchronous=NORMAL`: fsync is off the commit path and only happens at checkpoint. Batching would trade the one-event-one-transaction guarantee (a documented architecture rule) for a win that has already been collected. Corruption is impossible in WAL mode regardless of the synchronous setting; the only exposure is a few milliseconds of recent commits rolling back on power loss.
4. **Do NOT set `page_size=32768`.** Set connection-level pragmas at every open instead; `page_size` only takes effect before the first write and silently does nothing afterwards.
5. **Bundle the Electron main process to a single file**, and lazy-`require` the heavy main-process deps rather than loading them at boot.
6. **`asarUnpack` the `*.node` natives.** Loading a native module out of an asar archive forces an extract-to-temp on every launch.
7. **`module.enableCompileCache()`** (or `v8-compile-cache`) in main; keep renderer filenames stable so Chromium's URL-keyed disk code cache actually hits across launches.
8. **V8 startup snapshots last, if at all.** High complexity, and the payoff only shows up after the cheaper items are done.

### 4.2  Checked and cleared

**`electron.vite.config.ts` has no `build.bytecode` setting.** Verified this session: the file has `rollupOptions` at lines 27, 40 and 59 with `external: ["electron", "better-sqlite3"]` and `external: ["electron"]`, and no bytecode key anywhere.

This matters because bytenode documents a hard `SIGTRAP` / `EXC_BREAKPOINT` abort on Electron >= 42 (V8 >= 14.8) when bytecode is compiled under `ELECTRON_RUN_AS_NODE`: the main process boots V8 from Chromium's `v8_context_snapshot`, whose read-only heap checksum differs from the Node default snapshot, and V8 14.8 aborts rather than failing gracefully. This project is on Electron 42 but does not enable bytecode, so it is not exposed. Worth knowing before anyone turns it on for source protection: bytecode is not encryption, and API keys stay readable inside it.

### 4.3  LLM call path

`litellm_client.py` currently has **no prompt caching**, sends a bare `response_format={"type": "json_object"}` with no schema enforcement (`schema_name` is used only in error strings), and has **no streaming, no retry, and no token or cost accounting**. Prompt caching is the highest-leverage of these, because the system prompt and canonical profile are identical across every application in a batch.

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

### 5.2  Parse-back regression testing

A tailored DOCX that no longer round-trips is worse than no tailoring. After every mutation, re-extract and assert the section structure survived.

This matters most for Workday, which reads **strictly top-to-bottom, left-to-right**: right-column content in a two-column layout is frequently lost entirely, and table-based layouts misassign fields, with employer names concatenating with dates from adjacent rows and roles vanishing when cells are skipped. Contact details in a header or footer rather than the body are commonly missed. DOCX parses more consistently than PDF there because Word XML exposes paragraph styles and heading levels, whereas PDFs exported from Canva, InDesign or Figma store text as vector paths and routinely come out in the wrong order. *(Vendor and practitioner blog sources only: directionally consistent across several, but no primary Workday documentation. Treat as strong prior, not fact.)*

The same class of bug is well documented in the open. OpenResume has 57 open non-PR issues, including [#174](https://github.com/xitanggg/open-resume/issues/174) (section detection breaks when a section starts on a new page), [#145](https://github.com/xitanggg/open-resume/issues/145) and [#68](https://github.com/xitanggg/open-resume/issues/68) (**cannot parse PDFs its own builder exports**, open since 2023), [#115](https://github.com/xitanggg/open-resume/issues/115) and [#108](https://github.com/xitanggg/open-resume/issues/108) (LinkedIn-exported PDFs fail), and [#106](https://github.com/xitanggg/open-resume/issues/106) (spacing dropped between words). If OpenResume's algorithm is used as a reference, these are the regression tests to write first.

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
