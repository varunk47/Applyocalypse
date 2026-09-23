# Applyocalypse Release Readiness

Applyocalypse release readiness is an explicit gate, not a claim inferred from local unit tests.

## Required Gates

- `pnpm verify`
- `pnpm desktop:package`
- `pnpm test:worker-smoke`
- `pnpm test:desktop-smoke`
- `pnpm test:desktop-user-flow`
- `pnpm test:desktop-e2e`
- `pnpm cert:portals -- --targets certification/live-portal-targets.json --network` with `APPLYO_LIVE_CERTIFICATION=1`
- `pnpm release:preflight` with `APPLYO_REQUIRE_RELEASE_READY=1`

## External Inputs

Live portal certification requires current test application URLs, permitted test accounts where needed, and manual confirmation that final submit remains gated. BYOK provider certification requires real provider keys stored through the app provider settings. Release signing requires platform identities:

- Windows: `WINDOWS_SIGNTOOL_PATH`, `WINDOWS_CERT_SHA1`, optional `WINDOWS_TIMESTAMP_URL`
- macOS: `APPLE_CODESIGN_IDENTITY`

## Platforms

The release workflow builds Windows (x64 NSIS installer) on `windows-latest` and macOS (DMG and zip) on two runners, `macos-latest` for Apple Silicon and `macos-15-intel` for Intel. Each Mac arch needs its own runner because PyInstaller only builds the worker for the machine it runs on.

Mac builds are not signed with a Developer ID and are not notarized. electron-builder ad-hoc signs the Apple Silicon build and leaves the Intel build unsigned, so Gatekeeper warns on first open. To ship to other people, add a Developer ID Application certificate (`CSC_LINK` and `CSC_KEY_PASSWORD` for the app, `APPLE_CODESIGN_IDENTITY` for the worker) and notarization credentials, then turn `hardenedRuntime` and `notarize` back on in `apps/desktop/electron-builder/electron-builder.yml`.

## Update Channel

The local development package is unsigned and does not publish updates. Production installers must configure an update channel in release CI after signing and notarization are configured. Do not enable automatic updates for unsigned builds.

## Crash Reporting

Crash reporting must be opt-in. Reports must redact local paths, provider keys, OTPs, email credentials, generated document contents, screenshots, and browser DOM artifacts. Until that privacy filter is implemented and audited, release builds should keep crash upload disabled.

## Soak Testing

Before a public release, run a long-session soak with queued applications, renderer reloads, app restarts, blocked CAPTCHA/MFA/OTP states, generated-file cleanup, and stale lease recovery. The soak report must include run counts, blocked reasons, crash count, memory growth, and database integrity checks.
