import { existsSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { macSigningOverrides } from "./mac-signing.mjs";

describe("mac signing overrides", () => {
  it("leaves an unsigned Mac build exactly as the yml describes it", () => {
    expect(macSigningOverrides({}, "darwin")).toEqual([]);
    // GitHub hands an unset secret over as an empty string.
    expect(macSigningOverrides({ CSC_LINK: "" }, "darwin")).toEqual([]);
  });

  it("never touches a Windows build, even with a certificate configured", () => {
    expect(macSigningOverrides({ CSC_LINK: "cert.p12" }, "win32")).toEqual([]);
  });

  it.each([{ CSC_LINK: "base64-p12" }, { CSC_NAME: "Developer ID Application: Ada (TEAM123)" }])(
    "turns on hardened runtime, notarization and entitlements once a Developer ID exists (%o)",
    (env) => {
      const overrides = macSigningOverrides(env, "darwin");
      expect(overrides).toContain("-c.mac.hardenedRuntime=true");
      expect(overrides).toContain("-c.mac.notarize=true");
      const entitlementPaths = overrides
        .filter((arg) => arg.startsWith("-c.mac.entitlements"))
        .map((arg) => arg.slice(arg.indexOf("=") + 1));
      expect(entitlementPaths).toHaveLength(2);
      for (const path of entitlementPaths) {
        expect(existsSync(path)).toBe(true);
      }
    }
  );
});
