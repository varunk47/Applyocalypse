# Applyocalypse

Applyocalypse is a local-first Electron desktop application for AI-assisted job applications. It keeps the user in control, stores durable state in SQLite, generates documents on the local filesystem, and supervises Python browser automation through structured JSON events.

## Development

> **Agents: read [CLAUDE.md](CLAUDE.md) first** — it captures the architecture, safety invariants, and verification commands.

### Prerequisites

- Node >= 22 with corepack (pnpm >= 10)
- Python 3.12 on `PATH`
- Windows: Visual Studio Build Tools (C++ workload) for the `better-sqlite3` node-gyp build

### First run

```powershell
pnpm install
pnpm dev
```

`pnpm dev` auto-bootstraps the Python virtual environment (`services/automation-python/.venv-build`) and rebuilds the native modules for Electron before launching.

### Configuration

There is **no `.env` file**. LLM provider API keys, application credentials, and the Gmail OAuth client are entered in the app's Settings screen and stored encrypted via Electron `safeStorage` in SQLite. The only meaningful external environment variable for development is `APPLYO_PYTHON`, which overrides the host Python interpreter used to build the worker venv.

The Electron main process owns SQLite, filesystem access, native theme synchronization, Python process supervision, and browser automation coordination. The SolidJS renderer only talks to a typed preload API.

## Verification

```powershell
pnpm verify
```

Build the desktop app and local worker:

```powershell
pnpm --filter @applyocalypse/desktop build
pnpm python:build
pnpm desktop:package
pnpm test:worker-smoke
pnpm test:desktop-smoke
pnpm test:desktop-user-flow
pnpm test:desktop-e2e
```

For a full packaged local verification pass:

```powershell
pnpm verify:packaged
```

`pnpm desktop:package` creates an unsigned Windows `dir` package for local development, bundles the PyInstaller worker under Electron resources, and restores the local Node native `better-sqlite3` binding after Electron Builder rebuilds it.

`pnpm test:desktop-smoke` launches the packaged app with an isolated `userData` directory and exits after the renderer loads. It is intentionally separate from `pnpm verify` because it requires a packaged executable.

`pnpm test:desktop-user-flow` launches the packaged app with scheduler execution disabled and validates a real preload-mediated flow: native theme update, starter profile creation, job intake enqueue, queue persistence, absence of renderer Node primitives, and rejection of renderer attempts to mark answers approved outside the approval workflow.

`pnpm test:desktop-e2e` launches the packaged app twice against the same isolated `userData` directory and validates onboarding, local source-material ingestion, parser persistence, queue persistence after restart, and renderer isolation through the strict preload API.

`pnpm test:worker-smoke` executes the packaged PyInstaller worker from Electron resources against a local job-description fixture and verifies the expected structured event sequence.

Live portal and provider certification are opt-in because they require real external assets:

```powershell
pnpm cert:portals -- --targets certification/live-portal-targets.example.json
pnpm cert:providers
pnpm release:preflight
```

## Current Foundation

- Electron plus SolidJS desktop scaffold with GSAP motion and native theme sync.
- SQLite migration for settings, providers, profile, queue, run, document, screenshot, OTP, and audit metadata.
- Shared TypeScript domain schemas with Zod validation and a narrow preload IPC surface.
- Canonical profile facts are exposed to the renderer through typed `profile.getCanonical` IPC only; SQLite remains owned by Electron Main.
- The local parser extracts high-confidence structured profile facts from common sections and now reads DOCX table-cell paragraphs so column/table resumes are visible to section detection.
- Python worker event protocol, BYOK `litellm` adapter, Nodriver/Playwright browser abstraction, portal registry, document ingestion, validation, and tailoring pipeline primitives.
- Portal workflows use deterministic browser adapter candidates: high-stealth boards remain Nodriver-only, while ATS and government portals can fall back from Playwright to Nodriver when Playwright is not installed.
- Workday, Greenhouse, Lever, iCIMS, and Taleo now have explicit multi-step adapter plans with portal-specific progression labels, material hints, review gates, step caps, and final-submit labels.
- Portal workflow events include expected runner steps and mandatory review checkpoints so the Run Console can show what the browser worker is allowed to do before it does it.
- Provider settings now capture model, API base, Azure API version, and AWS Bedrock region/access-key metadata while keeping the secret value encrypted in Electron Main; Python receives only runtime environment variables.
- PDF ingestion converts with `pdf2docx` into an unverified DOCX candidate that requires explicit user confirmation.
- Source parsing detects common resume sections before any LLM is involved, persists confidence, warnings, style maps, and anchors in `parsed_documents`, and conservatively merges high-confidence identity, education, experience, project, certification, and skill facts without overwriting existing structured profile entries.
- Picked source files are copied into Applyocalypse-managed local custody before registration, so later parsing, PDF conversion, and automation do not depend on the user's original picked path remaining in place.
- DOCX and TEX mutation utilities use explicit Applyocalypse anchors/placeholders and preserve source structure as much as parser confidence allows.
- TEX output attempts a Tectonic PDF compile and emits a reviewable validation failure when the compiler is unavailable or the source fails.
- DOCX output now attempts local PDF export through LibreOffice or Word/docx2pdf when available and emits a reviewable validation warning when no local exporter exists.
- Post-review browser automation applies only explicitly approved field answers and upload-eligible documents. Required unanswered fields create `ANSWER` review requests and pause the live worker before any fill or final-submit attempt.
- Runtime control polling now peeks at future `RESUME` controls instead of consuming them outside the intended gate, preventing answer, document, and final-submit approvals from being lost between steps.
- Final submission now has a distinct approval path: portal entry actions refuse submit-like controls, while approved final submit clicks only exact final-submit labels and only records `SUBMITTED` when confirmation text is detected.
- Multi-page application forms can advance through reviewed non-final Next/Continue/Review controls, with a hard cap of six steps and a separate `PORTAL_STEP` review gate on ambiguity or excessive progression.
- Login or account-creation pages are detected as review blockers and create explicit `LOGIN` review requests so the user can sign in manually and resume from the same run state.
- Known portal Apply/Start actions now have an explicit `PORTAL_ENTRY` review gate when the worker cannot click them safely, preventing field filling on the wrong page.
- Portal entry clicks pause instead of choosing arbitrarily when multiple safe Apply/Start controls match, and the run event carries only sanitized candidate labels for user review.
- Browser automation emits portal page-state observations after entry actions, including redirect evidence, detected portal, field count, and application-surface confidence for the run console.
- Apply-phase browser automation captures optional run-scoped screenshots after the application is reopened, after reviewed fields/uploads are applied, and after each safe non-final portal step. Screenshot metadata is path-validated, hash-verified, idempotent by run and screenshot id, and records actual PNG dimensions when available.
- Replayable portal fixtures now cover representative Workday, Greenhouse, Lever, iCIMS, and Taleo application pages plus representative US and India job-board listing surfaces. They validate portal classification, application-surface confidence, field detection, blocker detection, and the shared safe-click policy without touching live sites.
- Requested US and India job-board targets now have conservative Apply/Start entry-action hints where the portal is registered; the click layer still blocks submit-like labels and pauses if a trusted application surface is not detected.
- Cover-letter need is detected from both JD analysis and actual application-form fields. If a portal exposes a required cover-letter upload and no reviewed artifact exists, the worker pauses before the final-submit gate.
- Reviewed local cover-letter uploads are passed to the worker as upload-eligible artifacts during document approval, without storing document bytes in SQLite.
- Required upload fixes now resume in the same live worker: Python waits for document approval, refreshes upload-eligible files, redetects form fields, and recognizes manual browser-side file uploads by file-count metadata only.
- The Playwright fallback adapter has real optional launch, navigation, field, upload, screenshot, and DOM methods. It fails safely when the Playwright runtime or browser binaries are not bundled.
- Electron packaging now verifies the bundled PyInstaller worker and includes an environment-gated `afterSign` hook for signing the worker binary in release CI. Local development builds remain unsigned unless `APPLYO_REQUIRE_CODE_SIGNING=1`.
- Packaged desktop smoke now verifies that the command center renders, the theme is applied before paint, and the strict preload API is available; the preload bundle is emitted as CommonJS because Electron sandbox preload scripts cannot load ESM imports.
- Packaged user-flow smoke verifies profile creation, job enqueue, queue metadata, theme IPC, and renderer isolation through the strict preload API.
- Packaged full-flow smoke verifies onboarding, local upload ingestion, parser persistence, queue persistence across restart, and renderer isolation through the strict preload API.
- Run console foundations: run selection, event stream, screenshot timeline, portal workflow plan, DOM diagnostics, field answer edits, pause/resume/cancel/retry/skip, review requests, and approval actions.
- Run controls now reject resume, retry, skip, and approval commands when the supervised worker is no longer alive, preserving audit history instead of pretending a crashed or recovered run resumed. Unsupported retry/skip commands at manual gates now emit a structured review event instead of being silently consumed.
- Unexpected Python worker exits immediately pause the run, clear queue leases, log a structured event, and broadcast the diagnostic to the console.
- Browser automation pauses on sensitive or ambiguous form questions such as work authorization, sponsorship, clearance, compensation, relocation, and voluntary EEO fields before filling values.
- Deterministic validation can run over TXT, MD, DOCX, TEX, and rendered PDF text when local extraction dependencies are available.
- Tailoring now builds an evidence-ranked one-page plan from verified profile material, separates truthful matches from missing keywords, and feeds that plan into deterministic review artifact ordering and bullet selection.
- Editable-master diagnostics expose structural anchor counts, explicit Applyocalypse placeholder counts, parser warnings, and anchor-repair status in the Documents panel. DOCX/TEX resume sources can now create a reviewable anchored candidate file without modifying the original source, and DOCX placeholder mutation plus anchor repair traverses table cells as well as top-level paragraphs.
- The Documents panel now includes a compact visual anchor-repair map that ranks ready, repairable, and review-only regions before creating an anchored candidate.
- Local security controls: Main-owned SQLite, OS-backed secret encryption, picked-path allowlist, DB-known artifact-only local file opening/rendering, screenshot metadata-only IPC, and audit logging for sensitive actions.
- Restart recovery pauses stale active application runs and their linked queue items together, clearing stale worker leases so interrupted jobs are visible for user inspection instead of remaining stuck in active queue states.
- Automation concurrency is persisted in SQLite as `automation.maxConcurrentApplications`, defaults to `2`, is user-adjustable from `1` to the hard cap of `3`, and is enforced globally across live claimed queue items.
- Scheduler preparation and worker-launch failures are isolated per queue item. The app records a failed run event and audit log instead of letting one bad item crash Electron Main.
- Packaged Electron windows deny arbitrary popups, block renderer navigation outside the expected app origin, deny renderer permission prompts, and disable DevTools in packaged builds unless explicitly enabled.

## Known Production Gaps

- Portal-specific multi-page workflows have adapter plans and fixture coverage for the first ATS set and representative job-board listing states, but not yet certified against live Workday, Greenhouse, Lever, iCIMS, Taleo, LinkedIn, Naukri, and similar targets. Current behavior is safer than blind automation: unknown, missed, or untrusted portal transitions pause for user review instead of proceeding.
- BYOK provider certification requires real keys. The matrix harness validates provider coverage offline and only performs live calls when explicitly enabled with `APPLYO_BYOK_LIVE_TESTS=1`.
- DOCX/TEX anchor repair is intentionally conservative. The app can create a reviewable anchored candidate for common summary and skills regions, including DOCX table-cell layouts, but a richer visual placement editor is still needed for arbitrary layouts.
- DOCX-to-PDF export depends on a local converter being available. TEX-to-PDF uses Tectonic when available.
- Generated Markdown review artifacts are a fallback, not a replacement for format-preserving DOCX/TEX masters.
- Desktop E2E coverage now includes packaged boot and local-first preload user-flow smoke, but not full multi-screen Playwright-style user-flow automation.
- macOS notarization, Windows EV certificate acquisition, and store-specific installer distribution are still external release-operations work.
