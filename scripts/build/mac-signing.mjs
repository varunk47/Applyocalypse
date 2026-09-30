import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const entitlements = resolve(dirname(fileURLToPath(import.meta.url)), "../../apps/desktop/electron-builder/entitlements.mac.plist");

// electron-builder.yml keeps hardened runtime and notarization off, because both
// need a paid Apple Developer ID and an unsigned build cannot use them. Once a
// Developer ID certificate is configured (CSC_LINK in CI, CSC_NAME for one in the
// local keychain) these overrides turn both on, so buying the membership and
// setting the secrets is the whole switch. electron-builder then notarizes only
// if APPLE_ID, APPLE_APP_SPECIFIC_PASSWORD and APPLE_TEAM_ID are set too, and
// skips with a warning otherwise.
export const macSigningOverrides = (env = process.env, platform = process.platform) => {
  if (platform !== "darwin" || !(env.CSC_LINK || env.CSC_NAME)) {
    return [];
  }
  return [
    "-c.mac.hardenedRuntime=true",
    "-c.mac.notarize=true",
    `-c.mac.entitlements=${entitlements}`,
    `-c.mac.entitlementsInherit=${entitlements}`
  ];
};
