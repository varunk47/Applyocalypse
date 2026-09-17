# Applyocalypse v2: Rebuild Research

*Generated 2026-09-05 · Scope: full-stack rebuild against the owner's spec · Confidence: mixed, flagged per claim*

Supersedes nothing. Companion to `docs/deep-research-2026-09-01.md` (stealth/speed/tailoring/free-APIs) and
`docs/free-apis-research.txt`. This document answers a broader question: **given the spec, what should the
system actually be built from?**

> All eight research tracks are complete. See `## Status` at the foot.

---

## Executive Summary

You said this one doesn't work at all. After auditing the repository against your spec, the finding is
narrower and much better news than "rebuild it": **it is not broken, it is gated.** Roughly two thirds of the
spec is already built and well tested (795 Python test functions, 234 TypeScript test cases, 44 portal
definitions, a live-portal certification harness). Three silent gates sit in the middle of the main flow, and
two of the four headline stages are genuinely missing.

The killer is gate one. Most people upload a **PDF** resume. The app marks it immutable, converts it to an
*unconfirmed* DOCX candidate, and then **silently refuses to tailor anything** until you go to a screen
onboarding never mentions and click CONFIRM. So you finish onboarding, paste links, runs execute, runs report
success, and your resume is never tailored. No error, anywhere. That single behaviour reproduces "doesn't work
at all" exactly.

Two more gates compound it: DOCX to PDF needs **LibreOffice** and TEX needs **tectonic**, neither bundled nor
checked, so a correct-looking install produces no PDF at all; and tailoring only edits text inside injected
anchors matched against a fixed English heading list, so an unusual template quietly yields a near-copy.

Genuinely absent: the **outreach agent (zero lines)**, **Gmail sending**, the **PDF editor**, the **Inbox**
screen, and a real **AI assistant** (today's chat handler is 19 lines of append-and-list, an activity log with
no model behind it).

On the technology questions in your spec, the research disagrees with four of your assumptions, and I would
rather say so now than build them:

1. **Stay on Electron, do not move to Tauri.** Tauri's OS webview breaks pdf.js, and an in-house PDF surface
   is a core requirement. Separately, **Azure Trusted Signing is $9.99/month**, which looks like the answer to
   the code-signing certificate this project has been blocked on.
2. **Format-preserving tailoring should reconstruct, not edit.** True in-place PDF text editing with reflow is
   unsolved in every tool examined, commercial ones included. Parse once into structure plus a style profile,
   then render per job. That permanently removes gates 1 and 3, and drops the AGPL dependencies on the way.
3. **Do not use Camoufox as the primary driver**, and do not use **Gmail MCP**. Camoufox is a beta mid-recovery
   from a maintenance gap with acknowledged fingerprint regressions; the MCP adds a process hop and removes
   none of the OAuth burden. Real persistently-profiled Chrome driven by **Patchright**, calling Gmail's REST
   API directly, is both safer and simpler.
4. **The concurrency cap is right, and "one agent per link" is wrong.** Hardware caps you near 5-6 visible
   browsers; more importantly, velocity is exactly what triggers adaptive authentication and gets competitors'
   users banned. Keep the cap, and say so in the UI instead of hiding it.

The strategic finding is that your instinct about outreach is correct and unoccupied. Every competitor
optimises for raw volume or passive tracking, and the four complaints that dominate the category — account
bans, billing dark patterns, hallucinated resume content, and "not actually auto-apply" — are structurally
impossible in a local-first, bring-your-own-key, review-before-submit product. Only JobRight even half-attempts
contact finding. **The wedge is real, and the outreach half of it is currently zero lines of code.**

One decision is yours and I have not made it: your requested **submit-without-review toggle** contradicts this
project's first safety invariant, and it also converts the strongest differentiator into the same liability
every competitor carries. §7.1 lays out three options with a recommendation.

## 1. Platform: Electron, Tauri, or something else

**Verdict: stay on Electron.** One reason dominates and it is specific to this app: Tauri renders in the OS
webview (WKWebView on macOS, WebKitGTK on Linux), and pdf.js is documented to hang on `getDocument()` and fail
on `blob:tauri://` asset fetches there `[inference from prior research round]`. An in-house PDF surface is a
core spec requirement, so that is a direct hit. Every other axis is a wash or a survivable cost.

| Axis | Electron | Tauri 2.x |
|---|---|---|
| Python sidecar | `extraResources` + spawn | `externalBin` + `shell().sidecar()` — architecturally identical |
| Native SQLite | better-sqlite3 Node-vs-Electron ABI split (already a documented repo pain point) | **Genuine win** — move to `rusqlite`/`sqlx`, no ABI rebuilds |
| PDF in-app | Full Chromium, pdf.js works | **Blocker** (see above) |
| Linux consistency | Chromium everywhere | WebKitGTK fragmentation is in [Tauri's own docs](https://v2.tauri.app/reference/webview-versions/) |
| Bundle | ~150-200MB | 3-10MB `[vendor claim, not re-verified]` |
| Auto-update | electron-updater, mature | tauri-plugin-updater, younger; and an Electron→Tauri migration cannot auto-upgrade existing installs across binary formats |

The bundle-size argument barely applies here: the app is already going to spawn N full Chrome processes for
automation, which dwarf the shell.

**Signing (shell-agnostic, and cheaper than the repo currently assumes):**
[Azure Trusted / Artifact Signing](https://azure.microsoft.com/en-us/products/artifact-signing) is
**$9.99/month** for up to 5,000 signatures, versus $200-500/yr OV or $400-700/yr EV certificates
([independent walkthrough](https://www.keyq.cloud/blog/windows-code-signing-with-azure-trusted-signing/)).
This directly unblocks the "blocked on signing cert" item in the project's own readiness notes. macOS still
needs the $99/yr Apple Developer account and notarization is
[a full day of setup the first time](https://www.keyq.cloud/blog/code-signing-and-notarization-for-macos-desktop-apps/).

### 1.1 Non-desktop alternatives, and why they lose

- **Local web app + local daemon.** Same architecture as today plus a browser/native trust boundary around
  secrets and session cookies, for no benefit `[inference — no direct evidence found]`.
- **Cloud/remote browsers** (Browserbase + Stagehand). Real and production-proven, but a remote headless
  browser is not something the user watches, which contradicts the human-supervision model the repo enforces
  in code, and it hands OTP/CAPTCHA handling to a third party `[prior-round evidence, single-source]`.
- **Browser-extension-first** (the Simplify Copilot shape). Genuinely shipping —
  [Jotofiller](https://github.com/mjishnu/Jotofiller) is an MV3 extension autofilling Workday/Greenhouse/
  Lever/iCIMS with native-setter shims and MutationObserver. But it inherits **unfixable** browser-security
  gaps: closed shadow DOM is unreachable with no content-script workaround, file uploads cannot be autofilled
  by design, and cross-origin iframe autofill is blocked unless the page opts into `shared-autofill`
  ([Chromium security docs](https://chromium.googlesource.com/chromium/src/+show/4de277c7202e0f7e9a2999decffcb0344b3e883d/docs/security/autofill-across-iframes.md)).
  A driver-level worker does not hit these. Given this repo just shipped cross-origin frame and shadow-root
  support, moving to an extension would be a regression.

### 1.2 Renderer and animation

Staying on SolidJS is defensible. Tables/virtualization reached parity via official adapters
([`@tanstack/solid-table`](https://tanstack.com/table/latest/docs/framework/solid/solid-table),
`@tanstack/solid-virtual`), and there are three viable grid options in 2026
([comparison](https://www.simple-table.com/blog/best-solidjs-data-grid-2026)).

- **Animation: use [Motion](https://motion.dev) (MIT) plus [`solid-motionone`](https://github.com/solidjs-community/solid-motionone)**
  (the official solidjs-community binding). The two newer Solid motion packages are self-labelled pre-1.0;
  avoid them.
- **GSAP's license is resolved**: Webflow made it 100% free including former paid plugins, effective
  2025-04-30 ([GSAP](https://gsap.com/community/standard-license)). A competitor page claims the new terms bar
  use in Webflow-competing tools and are terminable at will — that is **`[single-source, competitor-authored]`**
  and is not corroborated by the license text. Motion is the lower-risk default regardless.
- **Components without the template look**: [Ark UI](https://ark-ui.com/) (`@ark-ui/solid`, MIT) or Kobalte for
  headless primitives; several shadcn-for-Solid ports now exist.
- **View Transitions**: same-document transitions are Baseline "newly available" since Oct 2025, and Electron
  pins its Chromium, so they are always available in-app
  ([support matrix](https://webstatus.dev/features/cross-document-view-transitions)).

### 1.3 Concurrency: the spec's "as many links as you want" has a hard ceiling

No rigorous vendor-neutral benchmark exists for concurrent headed Chrome with distinct profiles; the space is
dominated by antidetect-vendor blogs with suspiciously precise numbers. The credible convergent signal is
**roughly 5-6 concurrent *visible* Chrome instances** on a consumer laptop before CPU throttling, at 200-500MB
each `[single-source / practitioner anecdote, low confidence]`. The usual scaling fix — go headless to save
~30% RAM — **conflicts with the human-supervision requirement**.

Combined with §3.4's finding that adaptive auth punishes velocity, this settles a design question: the
scheduler should cap at a low single digit and queue, not fan out. That is what
`localQueueScheduler.ts` already does. **The honest framing for the UI is "paste 100 links, we work through
them at a safe pace," not "100 agents at once."**

---

## 2. What already exists, and why it feels broken

**Verdict: this is not a rebuild.** Roughly two thirds of the spec is already built, and the browser layer is
genuinely mature. The app almost certainly boots and runs. What is wrong is that the spec's headline
promise — paste links, get tailored format-preserved documents, then outreach — has **three silent gates in
the middle and two of its four stages missing**.

### 2.1 Spec item by spec item

| # | Spec item | Status | Where |
|---|---|---|---|
| 1 | Onboarding wizard | **PARTIAL** | `renderer/screens/OnboardingScreen.tsx:26` |
| 2 | Portal credentials at onboarding, used in fill | **WIRED** | `migrations/0008_…`, `services/secureSecretStore.ts`, `localQueueScheduler.ts:178-217` |
| 3 | Resume/doc parser | **WIRED** | `parsing/document_parser.py` (36 functions), `parsing/canonical_profile.py` |
| 4 | Six UI sections | **PARTIAL** | `renderer/router.tsx`, `components/NavRail.tsx:17-23` |
| 5 | Paste many links, agent per application | **PARTIAL** | `HomeScreen.tsx:176-187`, `localQueueScheduler.ts:66` |
| 6 | JD analysis → tailor resume → tailor CL, format preserved | **PARTIAL / trapped** | `jd_analysis.py`, `resume_tailoring.py`, `documents/export_flow.py:119-139` |
| 7 | Any LLM provider | **WIRED** | `providerRuntimeEnv.ts:3-14`, `llm/provider_matrix.py` — 10 providers, TS↔Python parity test |
| 8 | Review gate + autonomous toggle | **WIRED** | `migrations/0005_…`, `localQueueScheduler.ts:95-109`, `portal_adapters.py:31-41` (10 gate types) |
| 9 | **Outreach agent** | **ABSENT** | zero lines. Grep for outreach / hunter.io / apollo / prospeo hits only docs and plans |
| 10 | Gmail | **PARTIAL** | OAuth + OTP + verification-link reading all work (`gmailOAuthService.ts:9`, `otp/gmail_mcp.py`). **Sending is absent** — the scope is `gmail.readonly` and there is no compose path |
| 11 | **In-house PDF editor** | **ABSENT** | no pdf.js, no annotation layer. `documents/pdf_export.py` is convert-only |
| 12 | **AI assistant chatbot** | **STUB** | `chatHandlers.ts` is **19 lines** of append/list. No LLM call, no input box, no preference storage, no profile mutation. It is an activity log |
| 13 | Browser automation + portals + stealth | **WIRED** | `browser/portal_registry.py` — 44 portal definitions; 3 adapters (nodriver → Patchright → seleniumbase); cross-origin frames, shadow roots, rich text, CAPTCHA all under test. **The strongest part of the repo** |

Also absent: the **Inbox** screen, and any separate Applications view (dashboard and applications are merged
into "Missions").

### 2.2 The three silent gates — the likely reason it "doesn't work at all"

**1. The PDF-resume dead end.** This is the big one. Most people upload a PDF.
`documentIngestionService.ts:283` marks it `IMMUTABLE_SOURCE`, converts it into an
`UNVERIFIED_EDITABLE_MASTER` DOCX *candidate*, and then **refuses to tailor** until the user visits a
different screen (Documents → "NEEDS CONFIRM" → CONFIRM, `DocumentsScreen.tsx:192`) and clicks confirm. Until
that happens, merge returns `skipped: ["Editable master has not been confirmed by the user."]`
(`documentIngestionService.ts:271`). **The onboarding wizard never mentions this.** So the observed behaviour
is: finish onboarding → paste links → runs execute and appear to succeed → the resume is never tailored → no
error is shown anywhere. That reads exactly as "doesn't work at all."

**2. Two undeclared external binaries.** DOCX→PDF requires LibreOffice `soffice` on PATH; TEX requires
`tectonic` (`converterDiagnostics.ts:36-63`). Neither is bundled. Without LibreOffice there is **no PDF
artifact at all**, on a machine that otherwise looks correctly installed.

**3. Anchor dependency in tailoring.** Tailoring only mutates text inside injected `{{APPLYO_*}}` placeholders
(`documents/anchor_repair.py:10-19`), and those are injected by matching section headings against a fixed
English label set (`SUMMARY_LABELS`, `SKILLS_LABELS`, and so on). An unusual heading, a two-column layout, or
a graphic template yields few or no anchors, and tailoring silently degrades to a near-copy of the original.
This is the same failure §4.1 predicts for any edit-in-place strategy, showing up in practice.

Two more, less severe:

- **Concurrency is 2 by default, 3 hard maximum** (`packages/config/src/index.ts:1-2`, clamped in
  `settingsHandlers.ts:12`), not "an agent per link." Pasting 20 links queues 20 items processed 2 at a time.
  Per §1.3 that cap is *correct*; the UI just never says so.
- **`EQUAL_EMPLOYMENT_SEED_DEFAULTS`** (`domain.ts:68-81`) ships one person's real demographic answers
  (Male / Asian / Heterosexual / "F-1 OPT 36 months") as the default for every user. That must go before
  anyone else installs this.

Work authorization exists but only as `authorizedToWorkUS` / `requiresSponsorship` / a free-text
`sponsorshipDetailText`. The spec asks for OPT/CPT detail, so this needs a proper enum plus a
now-vs-future sponsorship split. Cover letter and extra documents are **not** in onboarding at all — they
live on the Documents screen afterwards.

### 2.3 Size and health

| Area | Files | Lines |
|---|---|---|
| Python worker | 66 | 16,109 |
| Python tests | 78 | 14,921 |
| Renderer | 54 | 8,049 |
| Main process | 47 | 6,283 |
| `packages/*` (8 libs, 14 migrations) | 54 | 6,036 |

234 TS test cases across 35 files; 795 Python test functions across 76 files; 5 smoke scripts and a
live-portal certification harness. This is a well-tested codebase, not a prototype.

Loose ends worth clearing: `packages/ui/src/index.ts` is **1 line** (empty workspace package);
`prompt-templates` and `logging` are near-stubs at 5 and 10 lines; `wd.json` at the repo root is an untracked
raw NVIDIA Workday scrape left over from debugging; two UI-design ZIPs are committed at root;
`plans/020-runner-decomposition.md` is unexecuted and `runner.py` is still monolithic. CLAUDE.md also claims
other `services/*` directories exist as placeholders — they do not.

### 2.4 Competitive position

| Product | Shape | Pricing | Dominant complaint |
|---|---|---|---|
| Simplify Copilot | Extension, 100+ boards | Free; $19.99/wk | Not auto-apply — you still click Submit; paid AI output "too generic" |
| Massive | Cloud SaaS | $49-99/mo, card-gated 4-day trial | ~23-step onboarding; still needs manual clicks despite "autopilot" |
| JobRight.ai | SaaS + extension | ~$29.99/mo | Billing/cancellation friction; **Resume AI hallucinates skills and metrics** |
| LazyApply | Bulk extension | $99-249 | **LinkedIn/Indeed account restrictions**; forms filled wrong |
| Sonara.ai | Cloud auto-apply | — | Shut down Feb 2024, acquired by BOLD |
| Teal / Huntr / Careerflow | Trackers | $29-40/mo | Do not submit for you; billing continues post-cancel |
| AIHawk (OSS) | Python CLI | Free | 30.3k stars; LinkedIn support dropped upstream over ToS. License status conflicting `[unverified]` |

**Only JobRight ships contact-finding plus draft email**, and it is send-it-yourself off your own LinkedIn
graph, not an agent. Nobody else in the category attempts outreach.

**The wedge is real and unoccupied.** Every competitor optimises for either raw volume (Massive, LazyApply) or
passive organisation (Teal, Huntr, Careerflow). The field's four dominant complaints — account bans from
over-automation, billing dark patterns on volume-priced SaaS, AI hallucinating resume content, and
"not actually auto-apply" bait-and-switch — are **structurally impossible** in a local-first, BYOK,
review-before-submit product: nothing autonomous touches an ATS unattended, so there is no ban surface and no
volume-linked billing. Pairing that with genuine recruiter outreach is the clearest open lane in the market.

Note the tension: that wedge argument is also the strongest case *against* the unreviewed-submit toggle in
§7.1 — the toggle converts the differentiator into the same liability everyone else has. And the outreach half
of the wedge is currently **zero lines of code**.

## 3. Browser automation and stealth

**Verdict.** Layered, not a single tool. Drive the user's **real, persistently-profiled Chrome over CDP**
(the `chrome://inspect` dynamic-port route, not a throwaway automation profile), with
[Patchright](https://roundproxies.com/blog/patchright/) (Apache-2.0, tracks upstream Playwright within days)
as the driver. Keep nodriver only as a fallback engine — and note it is **AGPL-3.0**
([Snyk advisor](https://snyk.io/advisor/python/nodriver)), which is the same copyleft problem flagged in the
2026-09-01 report. **Do not adopt Camoufox as primary**: it is well-engineered but spent roughly a year
dormant and re-emerged in early 2026 shipping experimental betas (v146.0.1-beta.25) with acknowledged
fingerprint regressions ([camoufox.com/stealth](https://camoufox.com/stealth/)) `[single-source]`.

### 3.1 Tool comparison

| Tool | License | Engine | Maintained 2026? | Best for | Fatal flaw |
|---|---|---|---|---|---|
| [Camoufox](https://camoufox.com/stealth/) | MPL-2.0 | Firefox/Juggler, C++ fingerprint patching | Recovering from ~1yr gap; beta | Deep fingerprint spoofing without JS injection | Firefox-only; unstable during recovery |
| [Patchright](https://roundproxies.com/blog/patchright/) | Apache-2.0 | Chromium (Playwright fork) | Yes | Drop-in Playwright replacement; fixes `Runtime.enable` leak | Chromium-only; no TLS/IP coverage |
| [rebrowser-patches](https://github.com/rebrowser/rebrowser-patches) | MIT | Chromium patches | Yes | Keeping vanilla Playwright, layering patches | Same fix as Patchright, no fingerprint coverage |
| [nodriver](https://github.com/ultrafunkamsterdam/nodriver) | **AGPL-3.0** | Direct CDP → real Chrome | Yes (v0.50.3, 2026-05-13) but narrow bus factor | No webdriver shim; 28/31 OK, 0 blocked in one 2026 benchmark ([bench](https://ianlpaterson.com/blog/anti-detect-browser-benchmark-patchright-nodriver-curl-cffi/)) `[single-source]` | AGPL; asyncio-only |
| [undetected-chromedriver](https://snyk.io/advisor/python/undetected-chromedriver) | MIT | Selenium patched | **No** — inactive 12+ months | Legacy only | Effectively dead |
| Real Chrome + persistent profile | n/a | Native Chrome | n/a | Fixes environment signals libraries cannot fake | Chrome ≥136 blocks `--remote-debugging-port` on the default profile dir ([issue](https://github.com/trycua/cua/issues/2916)); debug port has zero auth |

Real-profile driving and CDP-leak patching are **complementary, not substitutes**. A persistent profile fixes
what page JS observes about the environment; the CDP attachment itself stays observable via timing side
channels regardless of the library on top
([crawlex](https://blog.crawlex.net/blog/detecting-cdp-runtime-enable/)) `[single-source]`. Note that the
classic `Runtime.enable`/console-getter leak was killed by two V8 commits in May 2025, so a lot of published
detection guidance is now stale (same source).

### 3.2 Detection per portal

| Portal | Detection observed | Evidence | Difficulty |
|---|---|---|---|
| SmartRecruiters | **DataDome**, vendor-confirmed, via Cloudflare on registration/apply endpoints | [DataDome case study](https://datadome.co/customers-stories/smartrecruiters-crushes-spam-job-applications-without-disrupting-real-users/) | 4 |
| Workday | No vendor confirmed. EUA §4.3 contractually bars automated scripts ([Workday](https://community-content.workday.com/en-us/public/learn/get-started/workday-community-policies-and-terms-of-use.html)). A widely-quoted "22% rejection" figure traces only to one vendor blog reusing it for three different metrics — `[unverified]` | 5 (SPA typeahead, wizard state) |
| Greenhouse | No vendor confirmed; CAPTCHA added ~early May 2026, broke several auto-apply tools at once `[single-source]` ([fastapply](https://blog.fastapply.co/ai-job-application-bots-which-actually-submit-2026)) | 2-3 |
| Lever, Ashby | None found. Ashby shipped an MCP server May 2026 — API-first posture ([herohunt](https://www.herohunt.ai/blog/agentic-ats-2026-greenhouse-vs-ashby-vs-workday/)) | 2 |
| Oracle (Taleo / ORC) | No vendor confirmed; difficulty is architectural (`careersection` iframes, `hcmUI/CandidateExperience`) `[inference]` | 4 |
| iCIMS | No vendor confirmed; legacy frame-based layouts `[inference]` | 4 |
| SuccessFactors, Dayforce, BrassRing, Phenom, Eightfold | **No evidence found at all** — needs a dedicated pass | unrated |

Cross-cutting and important for design: **reading** postings is largely unprotected — Workday, Greenhouse,
Lever, Ashby and SmartRecruiters all publish public unauthenticated job-board JSON APIs
([techmap comparison](https://bebee.com/us/jobs/comparing-the-job-posting-apis-of-workday-greenhouse-lever-ashby-smartrecruiters-and-recruitee-2026---techmap_us_4440015861)).
Defenses concentrate on the **write path**: account registration and submission. Only the submit step needs
stealth budget.

### 3.3 Do not let an LLM drive every click

Benchmark numbers in this space are mostly vendor-authored and not comparable. Skyvern co-built WebBench, the
benchmark it leads (64.4%) ([Skyvern](https://www.skyvern.com/blog/web-bench-a-new-way-to-compare-ai-browser-agents/));
Browser Use's headline 97% on Online-Mind2Web is vendor-run and vendor-judged, against its own 63.3% open
baseline ([state of browser use](https://michaellivs.com/blog/state-of-browser-use-2026/)). Independently:
the COLM 2025 "Illusion of Progress?" work found frontier agents complete ~30% of real tasks, and ClawBench
(153 live-site *write* tasks) caps the best frontier model at 33.3%
([digitalapplied](https://www.digitalapplied.com/blog/open-source-browser-computer-use-agents-2026)).
Claude Opus 4.6 scores 72.7% on OSWorld, independently verified
([agentmarketcap](https://agentmarketcap.ai/blog/2026/04/11/computer-use-agent-platform-wars-2026)).

Expect a **25-40% failure rate** on unsupervised long-form ATS filling from any of them. That is the argument
for the architecture the repo already has: deterministic selectors as the backbone, LLM confined to genuinely
ambiguous free-text questions. Licensing note: Skyvern is AGPL-3.0; browser-use is MIT (same digitalapplied
source).

### 3.4 Sessions and OTP

Authenticate interactively once per portal account and persist the **full** state — cookie jar *and*
localStorage/JWT, since SPAs keep short-lived tokens client-side
([browserless](https://www.browserless.io/blog/session-management)). One profile per account per network
identity, never mixed ([anchorbrowser](https://anchorbrowser.io/blog/an-overview-of-authenticated-browser-automation)).

Magic links are documented as unsuitable for unattended agents and must be opened in the *same* browser
session that requested them — Okta hard-errors on cross-device clicks
([autonoma](https://getautonoma.com/blog/how-to-test-magic-link-passwordless-login)). Lockout escalation is
real: adaptive auth ratchets MFA after unusual velocity, and recovery needs a human completing one challenge
in headed mode to restore trusted-device status (anchorbrowser, above). **This argues for human-paced,
low-concurrency execution — not for the "as many links as possible, all at once" model in the spec.** See §7.

### 3.5 Legal position

- **hiQ v. LinkedIn** (9th Cir., 2022 remand, post-*Van Buren*): scraping public, unauthenticated pages is not
  "without authorization" under the CFAA ([opinion](https://law.justia.com/cases/federal/appellate-courts/ca9/17-16783/17-16783-2022-04-18.html)).
  But hiQ **lost on breach of contract** and settled for $500K plus a permanent injunction
  ([Privacy World](https://www.privacyworld.blog/2022/12/linkedins-data-scraping-battle-with-hiq-labs-ends-with-proposed-judgment/)).
- **Van Buren (2021)** narrowed CFAA "exceeds authorized access" to require bypassing a real technical gate
  ([CRS](https://www.congress.gov/crs-product/LSB10616)).
- The generalizable lesson: **CFAA risk is low; ToS/contract risk is the real exposure** — and it rises the
  moment a login is involved, which application submission always is.
- Specifics: [Indeed's ToS](https://www.indeed.com/legal) explicitly bans automating the Apply flow;
  [LinkedIn UA §8.2](https://www.linkedin.com/help/linkedin/answer/a1341387) bans bots and enforces by
  graduated account restriction (24-72hr → permanent), not litigation against individuals; Workday's EUA §4.3
  restricts automated scripts.
- **No ATS vendor was found prohibiting AI-*generated* application content.** Greenhouse's stated position is
  that AI help with a resume or cover letter is fine, and Oracle ships candidate-side AI cover-letter
  generation ([herohunt](https://www.herohunt.ai/blog/agentic-ats-2026-greenhouse-vs-ashby-vs-workday/)).
  The 2026 friction is technical, not a new legal prohibition.

---

## 4. Document pipeline: parsing, tailoring, and the PDF editor

**Verdict.** The spec's "tailor in the exact format of the user's PDF or Word, the format shouldn't change"
cannot be delivered by editing the original file. The only architecture that gets the *result* the spec wants,
safely, is **reconstruct-not-edit**: parse the resume once into structured data **plus a style profile**
(fonts, margins, section order, bullet glyph), tailor the structured fields, then re-render through a template
in the same visual family. True in-place PDF text editing with correct reflow is unsolved in every open-source
and commercial tool today ([pdf.js discussion #21293](https://github.com/mozilla/pdf.js/discussions/21293)).

### 4.1 Why not edit in place

**DOCX.** `python-docx` edits at run level, and Word splits one logical string across many runs whenever
spellcheck, tracked changes, or partial formatting touch it — so naive `run.text = ...` silently drops or
merges formatting ([docxtpl docs](https://docxtpl.readthedocs.io/)). `docxtpl` (LGPL-2.1-only,
[conda-forge](https://anaconda.org/conda-forge/docxtpl)) works around this but is one-way template→output and
needs disciplined single-run tag authoring. **DOCX tailoring is reliable only when the tool renders from a
known template, not when it free-edits an arbitrary user file.**

**PDF.** PyMuPDF's redact-then-insert is the closest open-source approach, but it is AGPL-3.0/Artifex
commercial ([discussion #971](https://github.com/pymupdf/PyMuPDF/discussions/971)) and still cannot reflow —
a longer replacement overflows unless the layout happens to have slack. `pikepdf` (MPL-2.0) and `pdf-lib`
(MIT) are object/content-stream level: good for stamping and merging, not reflow. Commercial SDKs do offer
real content editing, at real cost — Apryse quotes from ~$1,500 with $10k+/yr common
([Vendr](https://www.vendr.com/marketplace/apryse)); Nutrient publishes no floor
([G2](https://www.g2.com/products/nutrient-sdk/pricing)) — and none solve reflow-on-longer-text without manual
layout intervention either.

**Renderers for the reconstruct path.** Typst (small footprint, sub-second compiles, embeddable as a Rust
library), WeasyPrint (BSD, CSS paged media), or headless Chrome HTML→PDF (widest fidelity, heaviest ops cost)
([Typst blog](https://typst.app/blog/2025/automated-generation/),
[DocuPotion](https://docupotion.com/blog/generate-pdfs-puppeteer)). No first-party disclosure was found from
Rezi/Teal/Novoresume confirming their renderer `[inference]`.

### 4.2 Getting off AGPL

`pdf2docx` is MIT but **hard-depends on PyMuPDF at import**, so it inherits the obligation — confirmed against
[its own repo](https://github.com/ArtifexSoftware/pdf2docx) and a real instance of exactly this transitive
conflict ([browser-use #2610](https://github.com/browser-use/browser-use/issues/2610)).

| Library | License (verified) | Does what | Verdict |
|---|---|---|---|
| PyMuPDF *(current)* | AGPL-3.0 or Artifex commercial | Extract, render, redact/insert | **Drop** for closed distribution |
| pdf2docx *(current)* | MIT, but pulls PyMuPDF | PDF→DOCX | **Drop** — inherits AGPL |
| [pdfplumber](https://anaconda.org/conda-forge/pdfplumber) | MIT | Char-level positional text/table extraction | **Adopt** — layout-aware extraction |
| [pypdf](https://pypdf.readthedocs.io/en/latest/meta/faq.html) | BSD-3 | Merge/split/basic ops, pure Python | Adopt |
| [pypdfium2](https://pypdfium2.readthedocs.io/en/stable/readme.html) | Apache-2.0 OR BSD-3 (PDFium BSD-style) | Fast native page→bitmap rendering | **Adopt** — ship bundled `BUILD_LICENSES/` |
| [pikepdf](https://github.com/pikepdf/pikepdf/blob/main/README.md) | MPL-2.0 (+ qpdf Apache-2.0) | Low-level read/write/repair | Adopt — file-level copyleft only |
| [reportlab](https://docs.reportlab.com/developerfaqs/) | BSD (open edition) | Generate PDF from scratch | Adopt — **avoid bundled pyRXP, it is GPL** |
| [Docling](https://github.com/docling-project/docling) | MIT (LF AI & Data, 2026) | Layout parsing, TableFormer, reading order | **Adopt** for parsing |
| borb | AGPL/commercial dual `[unverified]` | Generation/manipulation | Avoid pending verification |

pdfplumber + pypdf + pypdfium2 + pikepdf + reportlab covers extraction, rendering, structural edit and
generation with **zero AGPL exposure**, losing only PyMuPDF's convenience and its redact/insert trick — which
§4.1 says should not be used anyway.

### 4.3 Parsing

**Docling (MIT)** is the strongest open self-hosted fit: TableFormer table-structure recognition plus
multi-column reading-order recovery are precisely resume parsing's two hardest problems, it runs fully offline
after first model download (right for candidate PII), and OCR is pluggable for scanned files
([repo](https://github.com/docling-project/docling),
[writeup](https://towardsdatascience.com/parse-pdfs-for-rag-locally-with-docling-rich-tables-no-cloud-upload/)).
Caution: the widely-quoted "97.9% table accuracy" is from a corporate-sustainability-report dataset, **not
resumes** `[inference — do not treat as resume-domain accuracy]`.

Practical default: Docling/pdfplumber → markdown → LLM structured extraction against a JSON schema.

Commercial APIs, all self-reported accuracy `[unverified]`: Affinda (~$800/yr for 6,000 credits, self-host
option), RChilli ($75/mo for 500 credits, ~$150/1,000 CVs), Textkernel (absorbed Sovren 2022, no public
pricing) ([Pin comparison](https://www.pin.com/blog/best-resume-parser-tools/)). Market range $40-$200 per
1,000 resumes ([EdenAI](https://www.edenai.co/post/best-resume-parser-apis)).

Benchmarks: [OmniDocBench](https://github.com/opendatalab/OmniDocBench) (CVPR 2025, v1.7 Apr 2026) is the
general standard — GLM-OCR 94.6% on v1.5, ahead of Gemini 3 Pro and GPT-5.2 — though LlamaIndex argues in Feb
2026 that it is saturating on easy cases while a long tail still fails
([critique](https://www.llamaindex.ai/blog/omnidocbench-is-saturated-what-s-next-for-ocr-benchmarks)).
**No resume-specific public benchmark exists.** Validate against your own resume corpus.

### 4.4 The in-house PDF editor: scope it honestly

Realistic DIY scope with pdf.js is **overlay editing** — highlight, free-text boxes, stamps, ink, form-fill.
pdf.js ships this today, but as HTML overlays that "may not embed properly into a PDF"
([Nutrient guide](https://www.nutrient.io/blog/complete-guide-to-pdfjs/)). True source-backed text editing
(select existing glyph runs, retype, reflow) exists only as an **unmerged community prototype** as of mid-2026,
whose own author calls it incomplete for complex layouts, font encodings, multi-column documents and reflow
([discussion #21293](https://github.com/mozilla/pdf.js/discussions/21293)).

For rendering, `@hyzyla/pdfium` (MIT wrapper over BSD-style PDFium,
[repo](https://github.com/hyzyla/pdfium)) or `pdfium-render` (Rust, MIT/Apache-2.0, WASM-compilable,
[crates.io](https://crates.io/crates/pdfium-render)) beat pdf.js's own renderer for speed.

**Recommendation:** ship it as *PDF markup* (annotate, highlight, fill form fields) and route real text changes
back through the reconstruct pipeline in §4.1. Promising "edit the PDF directly without losing formatting"
would be promising something no vendor currently delivers.

### 4.5 ATS-safe output

Converging evidence on what actually breaks parsers: multi-column layout (readers interleave or skip columns —
worst on Workday/Taleo/iCIMS; Lever silently drops sidebars), tables (skills scrambled or lost), header/footer
content (many parsers skip those zones entirely, so **contact info must be in the body**), and text-as-image
([Jobscan formatting](https://www.jobscan.co/blog/ats-formatting-mistakes/),
[Jobscan tables/columns](https://www.jobscan.co/blog/resume-tables-columns-ats/)).

PDF vs DOCX: 2026 sources disagree — one camp says DOCX is lower-variance on Taleo and older enterprise
portals, another says modern Workday/iCIMS/Greenhouse parse clean single-column text PDFs equally well
([ATSVerification](https://atsverification.com/blog/pdf-vs-word-for-ats/),
[scale.jobs](https://scale.jobs/blog/pdf-vs-word-resume-format-ats-reads-correctly)). Both agree **format
choice is second-order to layout discipline**. So: default the render templates to single-column, in-body
contact fields, no tables or graphics in section content, regardless of output format.

---

## 5. Gmail, OTP capture, and outreach

**Verdict.** **Do not use Gmail MCP.** Call the Gmail REST API directly from the Python worker, with a
**bring-your-own OAuth client** that each user creates in their own free Google Cloud project. Split the
scopes by purpose. Treat outreach as a low-volume, human-approved channel, not a sending engine.

### 5.1 Why not MCP

MCP exists so an LLM can *discover and improvise* tool calls inside a chat loop. Applyocalypse's Gmail needs
are two fixed deterministic operations invoked by application code: poll for an OTP-shaped message, and send
one pre-approved draft. Routing those through MCP adds a JSON-RPC hop and a second process to keep patched,
and **does not remove the OAuth problem** — every self-hosted Gmail MCP server still requires the user to
create their own GCP OAuth client anyway
([GongRzhe/Gmail-MCP-Server](https://github.com/GongRzhe/Gmail-MCP-Server),
[taylorwilsdon/google_workspace_mcp](https://github.com/taylorwilsdon/google_workspace_mcp)). Google's own
Gmail MCP server (`gmailmcp.googleapis.com`) is Developer Preview and remote-hosted
([Workspace Updates, May 2026](https://workspaceupdates.googleblog.com/2026/05/agent-tools-and-security-updates-for-workspace-developers.html)).

This is a direct push-back on the spec's "use Gmail MCP." Revisit only if a later feature genuinely wants the
assistant improvising inbox actions conversationally.

### 5.2 Scopes: the decision that costs money if you get it wrong

Google classifies an app by its **most** restrictive scope
([Google](https://developers.google.com/identity/protocols/oauth2/production-readiness/restricted-scope-verification)):

| Scope | Tier | Review burden |
|---|---|---|
| `gmail.send` | **Sensitive** | Brand verification only. No security assessment. |
| `gmail.readonly`, `gmail.modify`, `gmail.compose`, `mail.google.com` | **Restricted** | Verification **plus annual third-party CASA Tier 2 assessment** |

CASA Tier 2 runs roughly **$500-$4,500 in lab fees** with **4-12+ week** timelines, and must be re-done
annually or production access is revoked
([DeepStrike](https://deepstrike.io/blog/google-casa-security-assessment-2025),
[Google recertification](https://support.google.com/cloud/answer/13463816?hl=en)).

Practical consequence: OTP capture needs `gmail.readonly`, which is Restricted. **You cannot ship a
publicly-verified app with OTP reading on a shared OAuth client without paying CASA every year.** The
BYO-client model sidesteps this because the user's own project in Testing mode consents only themselves.
Cost: Testing mode caps at 100 users and **expires refresh tokens every 7 days**, forcing weekly re-consent
([Unipile](https://www.unipile.com/google-oauth-refresh-token/),
[Google](https://support.google.com/cloud/answer/15549945?hl=en)).

Recommended split: `gmail.send` on a **shared, production-verified** client the app ships (cheap, Sensitive
tier only, no weekly re-auth); `gmail.readonly` for OTP on the **user's own BYO client**, with the weekly
re-consent surfaced honestly in Settings. `[inference — no shipped desktop-app precedent for this exact split
was found; the mechanics are documented, the combination is not]`

Desktop OAuth mechanics: loopback-redirect is still supported for Desktop client types (only iOS/Android/Chrome
lost it in 2022) ([migration guide](https://developers.google.com/identity/protocols/oauth2/resources/loopback-migration?authuser=7)).
Google's docs concede the embedded client secret "is obviously not treated as a secret," yet its token endpoint
**still requires it alongside PKCE** — omitting it returns `invalid_request`
([Google](https://developers.google.com/identity/protocols/oauth2/native-app),
[dev forum, Sept 2026](https://discuss.google.dev/t/desktop-oauth-pkce-exchange-returns-invalid-request-after-successful-loopback-callback-with-no-client-secret/390526)).
This is a known divergence from [RFC 8252](https://datatracker.ietf.org/doc/html/rfc8252).

App Passwords survive as a fallback (IMAP/SMTP only, requires 2FA on, blocked by Advanced Protection); plain
"less secure app" passwords died 2025-05-01
([Mailbird](https://www.getmailbird.com/gmail-oauth-changes-app-password-phase-out/)).

### 5.3 OTP: poll, do not push

Google's own guidance for installed apps is to **poll** `messages.list`/`history.list`
([Gmail push docs](https://developers.google.com/workspace/gmail/api/guides/push)). Pub/Sub push needs a public
HTTPS endpoint; the pull alternative means you are still polling, just polling Pub/Sub, plus a `watch()`
renewal cron (7-day max TTL) and a historyId cursor gotcha — never use the notification's `historyId` as your
`startHistoryId` ([Unipile](https://www.unipile.com/gmail-api-push-notifications/)).

Design: start the poll loop **before** clicking "send code" (the mail often lands before the page redirects),
query narrowly (`is:unread newer_than:2m from:...`), poll every 2-5s for 60-120s, and dedupe on `Message-Id`
so a stale code is never reused.

### 5.4 Outreach volume: the spec's plan is above the safe ceiling

| | Free Gmail | Workspace |
|---|---|---|
| Recipients / 24h | 500 | 2,000 |
| Recipients / message via SMTP | 100 | 100 |
| New account starting cap | 100-200/day | similar |

([Overloop](https://overloop.com/blog/gmail-sending-limits),
[Google Workspace](https://knowledge.workspace.google.com/admin/gmail/gmail-sending-limits-in-google-workspace))

Formal bulk-sender rules (DMARC alignment, one-click unsubscribe, <0.3% complaint rate) trigger at ~5,000/day
to personal Gmail addresses ([Google](https://support.google.com/a/answer/14229414?hl=en)) — irrelevant here.
The binding constraint is **behavioral throttling**: accounts sustaining 100-200/day draw algorithmic review
within 2-4 weeks and get suspended; practitioner-safe ceiling on a personal inbox is **~30-50/day**
([growthhacksuite](https://growthhacksuite.com/what-is-suspended-gmail-account)) `[single-source]`.

At 3 contacts per application, that is **~10-16 applications/day** before the user's personal Gmail is at risk.
Send via the Gmail API, not SMTP — gmail.com's DMARC policy is `quarantine`, which breaks external relays
([litemail.ai](https://litemail.ai/blog/google-workspace-cold-email-safe-2026)).

Legal: a genuine 1:1 recruiting email is very likely outside CAN-SPAM's commercial-message definition
([FTC](https://www.ftc.gov/business-guidance/blog/2015/08/candid-answers-can-spam-questions)). For EU contacts,
GDPR Art. 6(1)(f) legitimate interest applies if the message is relevant to the recipient's professional role,
identifies the sender, says how the address was obtained, and offers opt-out
([ComplyDog](https://complydog.com/blog/gdpr-compliant-cold-emails)).

### 5.5 Email finding and verification: what is actually free

Verified free tiers with usable APIs and no card:

| Provider | Free tier | Type |
|---|---|---|
| [Reoon](https://emailverifier.reoon.com/) | **600 credits/mo** | Verifier |
| [Prospeo](https://prospeo.io/s/email-finder-api) | 75 verified + 100 extension credits/mo | Finder + verifier |
| [Hunter.io](https://help.hunter.io/en/articles/11060999-what-s-included-in-hunter-s-free-plan) | 25 searches + 50 verifications/mo | Both |
| [Anymail Finder](https://anymailfinder.com/) | 100 credits, one-time (card verified, not charged) | Both |

Ship those four as the default waterfall. ~20 further providers were surveyed; their free-tier numbers came
from secondary sources only and are marked `[unverified]` (Snov.io, Tomba, LeadMagic, ZeroBounce API-on-free,
Skrapp API access, Datagma, Enrow, Icypeas, BetterContact, and others) — see the agent output for the full
table, and re-check any vendor page before wiring it in. RocketReach gates its API to a $2,099/yr tier;
Findymail and MillionVerifier have no free API.

**In-house permutation + SMTP probing is a fallback, not a strategy.** On catch-all domains a `250 OK` is
meaningless (the server accepts everything), and Google/Microsoft mail servers greylist and rate-limit unknown
probers ([Prospeo](https://prospeo.io/s/guess-email-address-format)). Correct shape: guess 1-3 candidates,
verify through a real API, and mark catch-all results low-confidence regardless of the SMTP response.

**"autumn.ai" does not appear to be an email finder.** The closest match is Autumn AI (YC W26), a GTM
signal-intelligence product ([YC](https://ycombinator.com/companies/autumn-ai)). If a contact-data tool was
meant, likely candidates are Ocean.io or Autobound. **Needs one word from the owner.**

### 5.6 Finding the right person

No independently audited accuracy figure exists anywhere for "the tool found the *correct* hiring manager" —
every such number is vendor marketing `[unverified]`. What works is ordinary research: the posting's "Meet the
hiring team" link; the company LinkedIn People tab filtered to a plausible functional title; the public
leadership page. **LinkedIn scraping is a clear ToS violation** irrespective of hiQ — hiQ settled that
scraping public data is not CFAA "unauthorized access," not that it is contract-compliant, and LinkedIn
enforces by account restriction
([LinkedIn Jobs T&C](https://www.linkedin.com/legal/jobs-terms-conditions)). Build around
domain-pattern + verifier APIs and manual confirmation, not a scraper.

---

## 6. LLM routing, agent orchestration, and memory

**Verdict.** Three of the four questions here resolve toward *keep what you have*. The repo's LiteLLM setup is
already the right shape, the local queue is already the right orchestrator, and the assistant should be a rules
table rather than a memory framework. The one genuine change is in how structured output is requested and
validated — and there is a failure mode in it that is specific to this product and dangerous.

### 6.1 Where LLM calls should live

**Keep the LiteLLM SDK in-process. Never ship the proxy.** The proxy mode's production deployment needs
PostgreSQL for key management and spend tracking plus Redis for rate limiting
([TrueFoundry](https://www.truefoundry.com/blog/litellm-vs-openrouter),
[Xenoss](https://xenoss.io/blog/openrouter-vs-litellm)) — none of which belongs on an end user's laptop. The
SDK keeps the user's keys going straight from their machine to the provider, which is also the only shape
consistent with this project's local-first stance and with safety invariant #3.

That is what the repo already does: 10 providers configured in `providerRuntimeEnv.ts:3-14` with a
TypeScript-to-Python parity test against `llm/provider_matrix.py`. This is the best-covered item in the whole
spec and needs no rework.

**One trap to avoid: do not route LiteLLM through OpenRouter.** This specific combination has documented
breakage — LiteLLM does not recognise `openrouter` as a provider supporting structured outputs, and the
OpenRouter adapter strips or rewrites nested schemas, so `response_format` is silently dropped or errors with
"Unknown parameter: response_format.response_schema"
([litellm#13438](https://github.com/BerriAI/litellm/issues/13438),
[litellm discussion #11652](https://github.com/BerriAI/litellm/discussions/11652)). The workaround is passing
the schema through `extra_body`, but the cleaner answer for a user who supplies an OpenRouter key is to call
OpenRouter through the plain OpenAI-compatible path and skip the adapter. If OpenRouter is used, set
`require_parameters=true` in the provider block so routing only reaches endpoints that actually support
`json_schema`; support there is **per endpoint, not per model**, and the same model served by two providers may
support it on one and not the other ([OpenRouter docs](https://openrouter.ai/docs/guides/features/structured-outputs)).

Also switch on `litellm.enable_json_schema_validation = True`
([LiteLLM JSON mode docs](https://docs.litellm.ai/docs/completion/json_mode)). It validates the response
client-side, which is exactly the safety net needed for providers that accept a schema without enforcing it.

### 6.2 Structured output on second-tier providers

The spec wants every provider in the world to work, including NIM, GLM, Kimi, and xAI. The three strategies
available differ in *when* the schema is enforced:

| Strategy | Library | Fails how |
|---|---|---|
| Constrained decoding (token masking) | Outlines, XGrammar | Cannot produce invalid structure |
| Tolerant parsing of malformed output | BAML (Schema-Aligned Parsing) | Recovers first, retries second |
| Post-hoc validation and re-prompt | Instructor | Retries with the validation error |

**Constrained decoding is not available to this app.** Efficient constrained decoding requires runtime
transforms on the model itself, so it only works with self-hosted models, not hosted APIs
([BAML](https://boundaryml.com/blog/structured-output-from-llms)). A bring-your-own-key desktop app talking to
whatever endpoint the user pasted cannot use it. That settles the choice: **post-hoc, with tolerant parsing.**

Between the remaining two, the weak-provider evidence favours tolerant parsing. Instructor's strict JSON parser
chokes when a model wraps its answer in markdown or emits chain-of-thought before the object — precisely what
smaller and second-tier models do
([glukhov.org benchmark](https://www.glukhov.org/llm-performance/benchmarks/baml-vs-instruct-for-structured-output-llm-in-python/)).
BAML's schema-aligned parsing recovers structured data from garbled or partial responses in microseconds, so
many failures never become retries at all. Worth noting the accuracy trade runs the other way from intuition:
on function-calling tasks BAML measured unconstrained generation with post-hoc parsing at **93.63%** against
**91.37%** for constrained decoding on the same model — the always-valid output was the less accurate one
`[single-source, vendor-authored]`.

**The defensive pattern for an unknown user-supplied provider**, then, is four layers, cheapest first:
capability probe on first use (does this endpoint honour `json_schema`, or only `json_object`, or neither);
request the schema when supported; parse tolerantly rather than strictly; validate against the schema
client-side and re-prompt with the validation error on failure, with a bounded retry count. That degrades
gracefully from a frontier model down to an endpoint that returns prose with JSON somewhere inside it.

### 6.3 The failure mode that matters most here

Every one of these techniques guarantees *shape*, not *truth*, and the gap is not academic for this product:
structured output hides uncertainty, because when the schema requires a value the model fills it in — a field
gets a confident number with no basis for it, and there is no standard mechanism for a model to say it does not
know ([Towards Data Science](https://towardsdatascience.com/your-json-is-valid-but-your-data-is-wrong-five-failure-modes-llm-structured-outputs-wont-catch/)).

Applied here: a schema with a required `answer` field, pointed at a work-authorization question, an EEO
question, or a previous-employer question, **will return a fabricated answer rather than an empty one**, and it
will look exactly like a good answer. That is a wrong statement submitted under the user's real name on a real
job application.

Two consequences. First, this is independent evidence for safety invariant #2 — those categories must stay
`requires_review=True` regardless of how confident the model sounds. Second, **every extraction schema in the
app should carry an explicit unknown variant** (a nullable answer plus a `confidence` or `basis` field, or a
tagged union with a `cannot_determine` case) so that "I do not know" is a representable value rather than
something the schema forbids. A schema that cannot express uncertainty converts every gap in the user's profile
into an invention.

### 6.4 Orchestration: the local queue is enough

**Do not adopt Temporal.** It uses a client-server architecture with a central server coordinating workers
([Temporal](https://temporal.io/blog/what-is-durable-execution)); shipping that server and its datastore next to
a desktop binary is a non-starter. **DBOS is closer but Postgres-centric** — it runs as a library inside the app
and stores workflow state in Postgres ([DBOS vs Temporal](https://www.dbos.dev/compare/dbos-vs-temporal)),
which is a heavy dependency to bundle for a single user. One 2026 comparison puts the boundary plainly: these
engines earn their complexity when workflows span services or need multi-region durability
([tiarebalbi](https://tiarebalbi.com/en/blog/dbos-vs-temporal-postgres-durable-execution)), and neither
describes a single-user desktop app.

The right shape for this app is a **SQLite-backed embedded engine**, which is what the repo already has: state
in better-sqlite3, a local queue in `localQueueScheduler.ts`, and pause gates in the adapters. That is a
recognised pattern rather than a shortcut — Persistasaurus uses SQLite for the execution log and argues SQLite
is a good production choice for a self-contained agentic system
([Gunnar Morling](https://www.morling.dev/blog/building-durable-execution-engine-with-sqlite/)), and
Cloudflare Workflows V2 scaled a SQLite-backed model from 4,500 to 50,000 concurrent instances, with one
database per workflow instance avoiding write contention
([Sesame Disk](https://sesamedisk.com/sqlite-litestream-durable-ai-workflows/)).

Two design points worth taking from the durable-execution literature even without adopting an engine:

- **Human-in-the-loop resume and crash resume are different operations that look identical from outside.** A
  person's approval is *new input*; a restarting worker has none, and should resume from its last checkpoint
  without a stale message forced into an incomplete turn
  ([Temporal](https://temporal.io/blog/manetu-the-thread-is-the-workflow)). The approval itself must be recorded
  durably, so a crash after approval resumes with the approval already in hand and never asks twice.
- **A checkpointer is not durable execution.** It saves state at developer-marked points and leaves retry,
  resume, and side-effect deduplication to the developer
  ([LangChain docs](https://docs.langchain.com/oss/python/langgraph/durable-execution)). If LangGraph is ever
  considered here, note its `"exit"` durability mode cannot recover from a mid-execution process crash. For a
  run that has already typed half a form into a live ATS, side-effect deduplication is the whole problem, so
  this distinction is the one that matters.

### 6.5 The assistant's memory: a rules table, not a memory framework

The spec's worked example — "anywhere in Georgia use my Atlanta address, anywhere in Texas use Dallas" across
ten to fifteen addresses — is a **deterministic lookup**, and the evidence says to build it as one.

The frameworks disagree with each other by a wide margin on exactly the capability this needs. On LongMemEval,
the temporal-retrieval benchmark, Zep's Graphiti backend scores **63.8%** against Mem0's **49.0%** with the same
model — a 15-point spread on remembering facts that change over time
([dev.to survey](https://dev.to/agdex_ai/ai-agent-memory-in-2026-mem0-vs-zep-vs-letta-vs-cognee-a-practical-guide-cfa),
[Particula](https://particula.tech/blog/agent-memory-frameworks-tested-mem0-zep-letta-cognee-2026)). A
one-in-three miss rate is not a basis for choosing which address goes on a real application.

The failure mode compounds, too: false facts in memory are treated as given by later steps and cemented into
synthesis entries, and the problem typically surfaces only when a user contradicts something stored several
sessions earlier and the agent confidently repeats the stale version
([Atlan](https://atlan.com/know/best-ai-agent-memory-frameworks-2026/)). And vector recall gives you none of the
governance this needs — no scoped writes, no review, no audit log, no rollback
([datapace](https://datapace.ai/blog/ai-agent-memory-tools-2026)).

The published guidance points the same way: hard, stable preferences belong in an explicit, auditable table
rather than LLM-extracted memory, because a preferences row is a lookup with no inference step, while extraction
is probabilistic and compounds errors. Where memory frameworks do get used for this, the recommended shape is a
**promotion gate** — a candidate preference must be user-confirmed before it becomes a row — with the
deterministic table remaining authoritative and injected into every prompt.

**Concretely for this app.** Addresses, work-authorization details, salary expectations, and every conditional
rule live in SQLite as visible, editable, diffable rows, applied deterministically at fill time. The chat
front end does two jobs and no more: it *proposes* rows from natural language, and it edits existing ones. The
user confirms before anything is written, and every rule is inspectable in the Profile screen. No embedding
store is required for any of this — and per Mem0's own documentation, retrievable memory is the wrong place for
unredacted personal data anyway, which is most of what this app holds.

### 6.6 Token cost

No published figure covers this workload, so the following is arithmetic from the pipeline's own stages, not a
sourced measurement `[inference]`. Per application, with a fast model for JD analysis and field decisions and a
strong model for tailoring: JD analysis roughly 5-8k in / 1k out; resume tailoring 8-12k in / 2-3k out; cover
letter 5-8k in / 1k out; form filling dominates at 25-60k in / 3-5k out because DOM context is resent per
decision; outreach drafting for three contacts 3-5k in / 1.5k out. That lands near **50-90k input and 8-11k
output tokens per application**, or roughly 5-9M input tokens per hundred applications.

The actionable part of that estimate is where the mass sits: **form filling is over half the spend**, and it is
also the stage where the deterministic-selector backbone already avoids most model calls. Every field resolved
by a known selector rather than a model is the cheapest optimisation available, and the existing architecture
already takes it. Caching the JD analysis per posting and reusing tailoring across near-duplicate postings
(the SimHash dedupe already in the repo) is the next lever.

## 7. Two decisions only you can make

Both are blocking. Neither should be decided silently by me.

### 7.1 The "submit without review" toggle contradicts the repo's own safety invariant

The spec asks for a toggle so an application is "directly, without the user reviewing it." The project's
`CLAUDE.md` states as invariant #1: *"No auto-submit without passing the explicit user approval gate."*

Two findings above bear directly on this:

- §3.5 — CFAA exposure is low, but **ToS/contract exposure is real and it attaches precisely at the
  authenticated submit step**. Indeed's ToS bans automating the Apply flow outright; Workday's EUA §4.3
  restricts automated scripts. Unreviewed submission is the single highest-liability action in the product.
- §3.3 — independent benchmarks put frontier agents at ~30% task completion on real sites, and the realistic
  expectation for unsupervised long-form ATS filling is a **25-40% failure rate**. An unreviewed submit is
  therefore also the action most likely to be wrong, and it is irreversible: a bad application reaches a real
  employer under the user's real name.

Three ways to resolve it:

| Option | What it means |
|---|---|
| **(a) Keep the gate absolute** | Ship no such toggle. Safest, and directly refuses a spec line. |
| **(b) Earned autonomy** *(recommended)* | Autonomous submit unlocks **per portal**, only after N successful reviewed runs on that portal, only above a field-confidence threshold, and **never** for EEO / criminal-history / previous-employer questions, which stay `requires_review=True` per invariant #2. Any low-confidence field drops the whole run back to review. |
| **(c) Drop the invariant** | Honour the spec literally. Accept the liability and the ~1-in-3 error rate. |

Option (b) gives the spec's intent (unattended volume) without handing an unproven agent the irreversible
action on day one. **This needs your call before any of it gets built.**

### 7.2 The AGPL problem from 2026-09-01 is still open, but now has a concrete exit

The prior report flagged two AGPL-3.0 dependencies (nodriver 0.50.3, PyMuPDF 1.27.2.3) inside a closed,
distributed binary with no root LICENSE file. That decision was never made. This round supplies the
replacements:

- **PyMuPDF → pdfplumber + pypdf + pypdfium2 + pikepdf + reportlab** (§4.2). Zero AGPL exposure. The only
  capability lost is PyMuPDF's redact-and-insert, which §4.1 argues should not be used anyway.
- **nodriver → Patchright** (Apache-2.0, §3.1), with nodriver demoted to an optional fallback engine that
  ships only if you accept the copyleft.

So the choice is now narrow: **do the swap, or buy an Artifex commercial licence, or open-source the app.**
Also still missing: a root `LICENSE` file.

### 7.3 Smaller things needing one word from you

- **"autumn.ai"** in the API list does not appear to be an email finder (§5.5). Which tool did you mean?
- **Gmail scopes** (§5.2): OTP reading is a Restricted scope. Are you willing to have each user create their
  own Google Cloud OAuth client, and accept a weekly re-consent prompt, in exchange for not paying a
  ~$500-$4,500/yr CASA assessment?

## 8. Target architecture and build order

### 8.1 What changes, and what does not

| Layer | Today | Target | Why |
|---|---|---|---|
| Shell | Electron 42 | **Unchanged** | §1 — Tauri's OS webview breaks pdf.js, and the PDF surface is core |
| Renderer | SolidJS 1.9 | **Unchanged** + Motion / `solid-motionone`, Ark UI or Kobalte | §1.2 — parity reached; no reason to churn |
| Browser driver | nodriver → Patchright → seleniumbase | **Patchright primary**, nodriver optional | §3.1 licensing and maintenance; keeps the existing fallback-chain shape |
| Browser profile | pooled (`profile_pool.py`) | Unchanged, plus real-Chrome CDP attach | §3.1, §3.4 |
| Doc parse | regex sectioniser | **Docling** (MIT) with existing heuristics as fallback | §4.3 — multi-column and table recovery is the actual failure mode |
| Doc tailor | in-place anchor mutation | **reconstruct-and-render** from structure + style profile | §4.1 — kills silent gates 1 and 3 permanently |
| Doc render | LibreOffice `soffice` shell-out | **Typst or WeasyPrint** in-process | §4.1 — removes an undeclared external binary |
| PDF libs | PyMuPDF, pdf2docx (AGPL) | pdfplumber + pypdf + pypdfium2 + pikepdf + reportlab | §4.2 — zero AGPL exposure |
| PDF editor | absent | **pdf.js overlay markup**, not text editing | §4.4 — text editing with reflow does not exist in any tool |
| LLM routing | 10 providers wired, TS and Python | **unchanged**, plus capability probe and tolerant parse | §6 — already the best-covered spec item |
| Gmail | `gmail.readonly`, OTP only | add `gmail.send`; BYO OAuth client for the read scope | §5.2 — avoids roughly $500-4,500/yr CASA |
| Outreach | absent | contact waterfall, approved send, hard daily cap | §5.4-5.6 |
| Assistant | 19-line activity log | rules table + chat + profile mutation over the existing Zod IPC | §2.1 item 12 |
| Concurrency | 2 default / 3 max | **unchanged**, but surfaced in the UI | §1.3 and §3.4 agree the cap is correct |

The most important line in that table: **the concurrency cap stays.** The hardware evidence (§1.3), the
adaptive-auth evidence (§3.4), and the market evidence (§2.4) all point the same way — volume automation is
precisely what gets competitors' users banned. The fix is honesty in the UI, "paste 100 links and we work
through them safely", not a bigger number.

### 8.2 Build order

Ordered by unblocking value rather than spec order. Phase 0 is measured in days and is what makes the product
stop feeling dead.

**Phase 0 — unblock the existing pipeline.** Nothing new is built here.

1. Remove `EQUAL_EMPLOYMENT_SEED_DEFAULTS` (`domain.ts:68-81`). It ships one real person's demographics as
   every user's default. Do this first regardless of everything else.
2. Move the editable-master confirmation **into onboarding** as a blocking step, or auto-confirm it with a
   visible diff. Today the gate lives on a screen the user has no reason to open
   (`documentIngestionService.ts:271,283`).
3. Detect LibreOffice and tectonic at startup and **fail loudly** in Settings instead of silently producing no
   artifact (`converterDiagnostics.ts:36-63`).
4. Show the queue concurrency cap in the intake UI.
5. Delete `wd.json` and the two committed UI-design ZIPs from the repo root.

**Phase 1 — document pipeline.** The real fix. Replaces gates 1 and 3 rather than papering over them, and
retires the AGPL dependencies at the same time: parse once into structured data plus a style profile, tailor
the structure, re-render per job. Gate it with the parse-back regression test from the 2026-09-01 report
(§5.2 there) — a tailored artifact that no longer parses back to the same structured fields is rejected.

**Phase 2 — onboarding completeness.** Work-authorization enum (OPT / CPT / H-1B / green card / citizen) with
now-versus-future sponsorship as separate fields; cover letter and extra documents moved into the wizard;
multiple addresses as first-class records. This is also the data model the assistant edits in Phase 4.

**Phase 3 — outreach.** Zero lines today and the clearest differentiator (§2.4). Order: `gmail.send` scope and
compose path, then the contact waterfall (Reoon, Prospeo, Hunter, Anymail Finder per §5.5), then per-contact
drafting, then an **approval queue with a hard cap of roughly 30-50 sends a day** (§5.4). The cap is not
optional; above it the thing at risk is the user's own Gmail account.

**Phase 4 — the assistant.** The conditional-address behaviour you described ("anywhere in Georgia, use
Atlanta") is a **rules engine with a chat front end**, not a memory framework. Store rules as explicit,
visible, editable rows; let the chat write rows; apply them deterministically at fill time. Wrong memory here
means wrong data on a real application under the user's real name, so rules must stay inspectable and
diffable, never buried in an opaque store. §6.5 confirms this against the memory-framework benchmarks: the
best framework tested still misses a third of temporal-fact questions, which is not a basis for choosing
which address goes on a real application.

**Phase 5 — remaining surfaces.** Inbox screen; PDF *markup* editor scoped honestly per §4.4; a separate
Applications view split out from Missions.

**Phase 6 — shipping.** Resolve the AGPL decision (§7.2), add a root `LICENSE`, and set up Azure Trusted
Signing at $9.99/month (§1), which appears to unblock the signing-certificate item that has been sitting in
the release-readiness notes.

### 8.3 What I would not build

- **Camoufox as the primary driver** (§3.1) — beta, mid-recovery, acknowledged fingerprint regressions.
- **A true PDF text editor** (§4.4) — it does not exist anywhere, so promising it guarantees a broken feature.
- **Gmail MCP** (§5.1) — adds a process and removes no burden.
- **An LLM driving every click** (§3.3) — 25-40% failure rate. The existing deterministic-selector backbone is
  the right design and is already the strongest part of the repo.
- **Higher concurrency** (§1.3, §3.4) — the cap is a feature.

## Key Takeaways

1. **The app is gated, not broken.** A PDF resume enters a confirmation gate that onboarding never mentions,
   and tailoring silently no-ops until the user clicks CONFIRM on another screen. Fix that one thing and most
   of the "doesn't work at all" experience disappears (§2.2).
2. **Two required binaries are neither bundled nor checked.** No LibreOffice means no PDF artifact, on an
   install that otherwise looks correct (§2.2).
3. **Stop editing documents in place; reconstruct them.** In-place PDF text editing with reflow is unsolved
   across every library and commercial product examined. Reconstructing from parsed structure plus a style
   profile is the only approach that both preserves format and survives unusual templates — and it retires the
   AGPL dependencies as a side effect (§4.1, §4.2).
4. **Ship the PDF surface as markup, not text editing.** Source-backed text editing exists only as an unmerged
   pdf.js prototype. Scope the feature honestly (§4.4).
5. **Stay on Electron.** Tauri's OS webview breaks pdf.js, and the PDF surface is core. Azure Trusted Signing
   at $9.99/month appears to unblock the code-signing certificate this project has been waiting on (§1).
6. **Patchright over Camoufox and nodriver.** Apache-2.0, tracks upstream Playwright within days, and avoids
   both the AGPL exposure and Camoufox's acknowledged beta fingerprint regressions (§3.1).
7. **Reading postings is unprotected; writing is where defenses live.** Public job-board JSON APIs are open
   almost everywhere. Only SmartRecruiters is vendor-confirmed as bot-protected (DataDome via Cloudflare). The
   widely-quoted "22% Workday rejection" figure is unverified vendor marketing (§3.2).
8. **Expect 25-40% failure on unsupervised long-form ATS filling.** That is the benchmark reality, and it
   validates the existing deterministic-selector backbone with the LLM reserved for unknown fields (§3.3).
9. **Skip Gmail MCP; call the REST API directly.** And split the scopes: `gmail.send` is merely Sensitive,
   while `gmail.readonly` is Restricted and drags in annual CASA Tier 2 at roughly $500-4,500/yr. Bring-your-own
   OAuth client sidesteps that for the read path (§5.1, §5.2).
10. **Poll for OTPs, do not push.** Google's own guidance for installed apps. Start polling before the code is
    requested and dedupe on Message-Id (§5.3).
11. **Cap outreach at roughly 30-50 sends a day.** That is about 10-16 applications at three contacts each. The
    account at risk is the user's own (§5.4).
12. **Four email APIs have verified free tiers** — Reoon 600/mo, Prospeo 75/mo, Hunter 25+50/mo, Anymail Finder
    100 one-time. Roughly twenty others remain unverified, and "autumn.ai" does not appear to be an email
    finder at all (§5.5).
13. **Schemas that cannot say "I don't know" invent answers.** Structured output guarantees shape, not truth:
    a required field always gets filled. Pointed at a work-authorization or EEO question, that is a fabrication
    submitted under the user's real name. Every extraction schema needs an explicit unknown variant (§6.3).
14. **Build the assistant as a rules table, not a memory framework.** The best framework benchmarked still
    misses roughly a third of temporal-fact questions, and false memories compound silently. Addresses and
    conditional rules belong in visible, editable, auditable SQLite rows (§6.5).
15. **Keep the concurrency cap.** Hardware, adaptive authentication, and the competitive evidence all agree.
    "One agent per link" is the wrong goal; the UI should simply say what the queue is doing (§1.3, §3.4, §8.1).
16. **The outreach wedge is real and unoccupied — and unwritten.** Every competitor optimises for volume or
    passive tracking, and the category's four dominant complaints are structurally impossible in a local-first,
    BYOK, review-before-submit product. Only JobRight half-attempts outreach. This product's version of it is
    currently zero lines of code (§2.4).
17. **One decision is still yours:** the submit-without-review toggle against safety invariant #1. Recommended
    middle path is earned autonomy per portal after N successful reviewed runs (§7.1).

## Status

| Track | State |
|---|---|
| 1. Platform (Electron / Tauri / other) | done |
| 2. Repo audit and competitive position | done |
| 3. Browser automation and stealth | done |
| 4. Document pipeline | done |
| 5. Gmail, OTP, outreach | done |
| 6. LLM routing, agents, memory | done |
| 7. Open decisions | done |
| 8. Target architecture and build order | done |


## Sources

Citations are inline throughout. Consolidated and deduplicated:

1. [agentmarketcap](https://agentmarketcap.ai/blog/2026/04/11/computer-use-agent-platform-wars-2026)
2. [conda-forge](https://anaconda.org/conda-forge/docxtpl)
3. [pdfplumber](https://anaconda.org/conda-forge/pdfplumber)
4. [anchorbrowser](https://anchorbrowser.io/blog/an-overview-of-authenticated-browser-automation)
5. [Anymail Finder](https://anymailfinder.com/)
6. [Ark UI](https://ark-ui.com/)
7. [Atlan](https://atlan.com/know/best-ai-agent-memory-frameworks-2026/)
8. [ATSVerification](https://atsverification.com/blog/pdf-vs-word-for-ats/)
9. [Azure Trusted / Artifact Signing](https://azure.microsoft.com/en-us/products/artifact-signing)
10. [techmap comparison](https://bebee.com/us/jobs/comparing-the-job-posting-apis-of-workday-greenhouse-lever-ashby-smartrecruiters-and-recruitee-2026---techmap_us_4440015861)
11. [crawlex](https://blog.crawlex.net/blog/detecting-cdp-runtime-enable/)
12. [fastapply](https://blog.fastapply.co/ai-job-application-bots-which-actually-submit-2026)
13. [BAML](https://boundaryml.com/blog/structured-output-from-llms)
14. [camoufox.com/stealth](https://camoufox.com/stealth/)
15. [Chromium security docs](https://chromium.googlesource.com/chromium/src/+show/4de277c7202e0f7e9a2999decffcb0344b3e883d/docs/security/autofill-across-iframes.md)
16. [Workday](https://community-content.workday.com/en-us/public/learn/get-started/workday-community-policies-and-terms-of-use.html)
17. [ComplyDog](https://complydog.com/blog/gdpr-compliant-cold-emails)
18. [crates.io](https://crates.io/crates/pdfium-render)
19. [DataDome case study](https://datadome.co/customers-stories/smartrecruiters-crushes-spam-job-applications-without-disrupting-real-users/)
20. [datapace](https://datapace.ai/blog/ai-agent-memory-tools-2026)
21. [RFC 8252](https://datatracker.ietf.org/doc/html/rfc8252)
22. [DeepStrike](https://deepstrike.io/blog/google-casa-security-assessment-2025)
23. [dev.to survey](https://dev.to/agdex_ai/ai-agent-memory-in-2026-mem0-vs-zep-vs-letta-vs-cognee-a-practical-guide-cfa)
24. [Google](https://developers.google.com/identity/protocols/oauth2/native-app)
25. [Google](https://developers.google.com/identity/protocols/oauth2/production-readiness/restricted-scope-verification)
26. [migration guide](https://developers.google.com/identity/protocols/oauth2/resources/loopback-migration?authuser=7)
27. [Gmail push docs](https://developers.google.com/workspace/gmail/api/guides/push)
28. [dev forum, Sept 2026](https://discuss.google.dev/t/desktop-oauth-pkce-exchange-returns-invalid-request-after-successful-loopback-callback-with-no-client-secret/390526)
29. [LangChain docs](https://docs.langchain.com/oss/python/langgraph/durable-execution)
30. [LiteLLM JSON mode docs](https://docs.litellm.ai/docs/completion/json_mode)
31. [reportlab](https://docs.reportlab.com/developerfaqs/)
32. [DocuPotion](https://docupotion.com/blog/generate-pdfs-puppeteer)
33. [docxtpl docs](https://docxtpl.readthedocs.io/)
34. [Reoon](https://emailverifier.reoon.com/)
35. [autonoma](https://getautonoma.com/blog/how-to-test-magic-link-passwordless-login)
36. [its own repo](https://github.com/ArtifexSoftware/pdf2docx)
37. [litellm discussion #11652](https://github.com/BerriAI/litellm/discussions/11652)
38. [litellm#13438](https://github.com/BerriAI/litellm/issues/13438)
39. [GongRzhe/Gmail-MCP-Server](https://github.com/GongRzhe/Gmail-MCP-Server)
40. [browser-use #2610](https://github.com/browser-use/browser-use/issues/2610)
41. [Docling](https://github.com/docling-project/docling)
42. [repo](https://github.com/hyzyla/pdfium)
43. [Jotofiller](https://github.com/mjishnu/Jotofiller)
44. [pdf.js discussion #21293](https://github.com/mozilla/pdf.js/discussions/21293)
45. [OmniDocBench](https://github.com/opendatalab/OmniDocBench)
46. [pikepdf](https://github.com/pikepdf/pikepdf/blob/main/README.md)
47. [discussion #971](https://github.com/pymupdf/PyMuPDF/discussions/971)
48. [rebrowser-patches](https://github.com/rebrowser/rebrowser-patches)
49. [`solid-motionone`](https://github.com/solidjs-community/solid-motionone)
50. [taylorwilsdon/google_workspace_mcp](https://github.com/taylorwilsdon/google_workspace_mcp)
51. [issue](https://github.com/trycua/cua/issues/2916)
52. [nodriver](https://github.com/ultrafunkamsterdam/nodriver)
53. [growthhacksuite](https://growthhacksuite.com/what-is-suspended-gmail-account)
54. [GSAP](https://gsap.com/community/standard-license)
55. [Hunter.io](https://help.hunter.io/en/articles/11060999-what-s-included-in-hunter-s-free-plan)
56. [bench](https://ianlpaterson.com/blog/anti-detect-browser-benchmark-patchright-nodriver-curl-cffi/)
57. [Google Workspace](https://knowledge.workspace.google.com/admin/gmail/gmail-sending-limits-in-google-workspace)
58. [opinion](https://law.justia.com/cases/federal/appellate-courts/ca9/17-16783/17-16783-2022-04-18.html)
59. [litemail.ai](https://litemail.ai/blog/google-workspace-cold-email-safe-2026)
60. [state of browser use](https://michaellivs.com/blog/state-of-browser-use-2026/)
61. [Motion](https://motion.dev)
62. [OpenRouter docs](https://openrouter.ai/docs/guides/features/structured-outputs)
63. [Overloop](https://overloop.com/blog/gmail-sending-limits)
64. [Particula](https://particula.tech/blog/agent-memory-frameworks-tested-mem0-zep-letta-cognee-2026)
65. [Prospeo](https://prospeo.io/s/email-finder-api)
66. [Prospeo](https://prospeo.io/s/guess-email-address-format)
67. [pypdf](https://pypdf.readthedocs.io/en/latest/meta/faq.html)
68. [pypdfium2](https://pypdfium2.readthedocs.io/en/stable/readme.html)
69. [Patchright](https://roundproxies.com/blog/patchright/)
70. [scale.jobs](https://scale.jobs/blog/pdf-vs-word-resume-format-ats-reads-correctly)
71. [Sesame Disk](https://sesamedisk.com/sqlite-litestream-durable-ai-workflows/)
72. [Snyk advisor](https://snyk.io/advisor/python/nodriver)
73. [undetected-chromedriver](https://snyk.io/advisor/python/undetected-chromedriver)
74. [Google](https://support.google.com/a/answer/14229414?hl=en)
75. [Google recertification](https://support.google.com/cloud/answer/13463816?hl=en)
76. [Google](https://support.google.com/cloud/answer/15549945?hl=en)
77. [`@tanstack/solid-table`](https://tanstack.com/table/latest/docs/framework/solid/solid-table)
78. [Temporal](https://temporal.io/blog/manetu-the-thread-is-the-workflow)
79. [Temporal](https://temporal.io/blog/what-is-durable-execution)
80. [tiarebalbi](https://tiarebalbi.com/en/blog/dbos-vs-temporal-postgres-durable-execution)
81. [writeup](https://towardsdatascience.com/parse-pdfs-for-rag-locally-with-docling-rich-tables-no-cloud-upload/)
82. [Towards Data Science](https://towardsdatascience.com/your-json-is-valid-but-your-data-is-wrong-five-failure-modes-llm-structured-outputs-wont-catch/)
83. [Typst blog](https://typst.app/blog/2025/automated-generation/)
84. [Tauri's own docs](https://v2.tauri.app/reference/webview-versions/)
85. [support matrix](https://webstatus.dev/features/cross-document-view-transitions)
86. [Workspace Updates, May 2026](https://workspaceupdates.googleblog.com/2026/05/agent-tools-and-security-updates-for-workspace-developers.html)
87. [browserless](https://www.browserless.io/blog/session-management)
88. [CRS](https://www.congress.gov/crs-product/LSB10616)
89. [DBOS vs Temporal](https://www.dbos.dev/compare/dbos-vs-temporal)
90. [digitalapplied](https://www.digitalapplied.com/blog/open-source-browser-computer-use-agents-2026)
91. [EdenAI](https://www.edenai.co/post/best-resume-parser-apis)
92. [FTC](https://www.ftc.gov/business-guidance/blog/2015/08/candid-answers-can-spam-questions)
93. [G2](https://www.g2.com/products/nutrient-sdk/pricing)
94. [Mailbird](https://www.getmailbird.com/gmail-oauth-changes-app-password-phase-out/)
95. [glukhov.org benchmark](https://www.glukhov.org/llm-performance/benchmarks/baml-vs-instruct-for-structured-output-llm-in-python/)
96. [herohunt](https://www.herohunt.ai/blog/agentic-ats-2026-greenhouse-vs-ashby-vs-workday/)
97. [Indeed's ToS](https://www.indeed.com/legal)
98. [Jobscan formatting](https://www.jobscan.co/blog/ats-formatting-mistakes/)
99. [Jobscan tables/columns](https://www.jobscan.co/blog/resume-tables-columns-ats/)
100. [a full day of setup the first time](https://www.keyq.cloud/blog/code-signing-and-notarization-for-macos-desktop-apps/)
101. [independent walkthrough](https://www.keyq.cloud/blog/windows-code-signing-with-azure-trusted-signing/)
102. [LinkedIn UA §8.2](https://www.linkedin.com/help/linkedin/answer/a1341387)
103. [LinkedIn Jobs T&C](https://www.linkedin.com/legal/jobs-terms-conditions)
104. [critique](https://www.llamaindex.ai/blog/omnidocbench-is-saturated-what-s-next-for-ocr-benchmarks)
105. [Gunnar Morling](https://www.morling.dev/blog/building-durable-execution-engine-with-sqlite/)
106. [Nutrient guide](https://www.nutrient.io/blog/complete-guide-to-pdfjs/)
107. [Pin comparison](https://www.pin.com/blog/best-resume-parser-tools/)
108. [Privacy World](https://www.privacyworld.blog/2022/12/linkedins-data-scraping-battle-with-hiq-labs-ends-with-proposed-judgment/)
109. [comparison](https://www.simple-table.com/blog/best-solidjs-data-grid-2026)
110. [Skyvern](https://www.skyvern.com/blog/web-bench-a-new-way-to-compare-ai-browser-agents/)
111. [TrueFoundry](https://www.truefoundry.com/blog/litellm-vs-openrouter)
112. [Unipile](https://www.unipile.com/gmail-api-push-notifications/)
113. [Unipile](https://www.unipile.com/google-oauth-refresh-token/)
114. [Vendr](https://www.vendr.com/marketplace/apryse)
115. [Xenoss](https://xenoss.io/blog/openrouter-vs-litellm)
116. [YC](https://ycombinator.com/companies/autumn-ai)

## Methodology

Eight parallel research tracks: platform choice, repository audit and competitive scan, browser automation
and stealth, the document pipeline, Gmail and outreach, LLM routing and orchestration, open decisions, and
target architecture. Web research used firecrawl and exa across roughly 115 unique external sources, combined
with a direct read of this repository (files, tests, migrations, and git history) for every claim about what
already exists.

Claim labelling used throughout: unlabelled claims are supported by two or more independent sources;
`[single-source]` and `[unverified]` mark claims found in only one place or resting on vendor marketing;
`[inference]` marks my own reasoning rather than a sourced fact. Vendor-authored benchmarks are called out
where they appear, because most automation-success figures in this space are published by the vendors whose
products they measure.

**Known gaps.** No resume-specific public parsing benchmark exists, so §4.3 accuracy figures come from an unrelated document corpus. No audited figure exists
for hiring-manager identification accuracy (§5.6). Roughly twenty of the email-finding APIs named in the spec
were not individually verified, and "autumn.ai" could not be identified as an email tool at all.

