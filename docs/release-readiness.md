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

Mac builds are not signed with a Developer ID and are not notarized yet. electron-builder ad-hoc signs the Apple Silicon build and leaves the Intel build unsigned, so Gatekeeper warns on first open.

Signing and notarization are wired up and switch on from secrets alone; no code or config change is needed:

1. Join the Apple Developer Program ($99 a year).
2. In Xcode or the developer portal, create a **Developer ID Application** certificate and export it with its private key as a `.p12` file.
3. Create an app-specific password at appleid.apple.com, and note your 10-character Team ID from the developer portal.
4. Add these repository secrets in GitHub (Settings, Secrets and variables, Actions):
   - `MAC_CSC_LINK`: the `.p12` file, base64 encoded (`base64 -i cert.p12 | pbcopy`).
   - `MAC_CSC_KEY_PASSWORD`: the password you set when exporting the `.p12`.
   - `APPLE_ID`, `APPLE_APP_SPECIFIC_PASSWORD`, `APPLE_TEAM_ID`: for notarization.
5. Push a `v*` tag or run the release workflow by hand.

With `MAC_CSC_LINK` set, `scripts/build/mac-signing.mjs` turns on the hardened runtime and signs the app and everything inside it, the Python worker included, with `apps/desktop/electron-builder/entitlements.mac.plist`. With the three `APPLE_*` secrets set as well, electron-builder notarizes and staples the build. To sign a local build on a Mac instead, have the certificate in your login keychain and run `CSC_NAME="Developer ID Application: Your Name (TEAMID)" pnpm desktop:package`.

## Update Channel

The local development package is unsigned and does not publish updates. Production installers must configure an update channel in release CI after signing and notarization are configured. Do not enable automatic updates for unsigned builds.

## Crash Reporting

Crash reporting must be opt-in. Reports must redact local paths, provider keys, OTPs, email credentials, generated document contents, screenshots, and browser DOM artifacts. Until that privacy filter is implemented and audited, release builds should keep crash upload disabled.

## Soak Testing

Before a public release, run a long-session soak with queued applications, renderer reloads, app restarts, blocked CAPTCHA/MFA/OTP states, generated-file cleanup, and stale lease recovery. The soak report must include run counts, blocked reasons, crash count, memory growth, and database integrity checks.
