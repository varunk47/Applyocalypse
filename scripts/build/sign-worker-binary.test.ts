import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { createRequire } from "node:module";
import { afterEach, describe, expect, it, vi } from "vitest";

const require = createRequire(import.meta.url);
const { signWorkerBinary } = require("./sign-worker-binary.cjs") as {
  signWorkerBinary: (workerPath: string, platform?: NodeJS.Platform | string) => Promise<{ signed: boolean; reason: string }>;
};

describe("signWorkerBinary", () => {
  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it("skips local unsigned worker binaries when signing is not configured", async () => {
    const dir = mkdtempSync(join(tmpdir(), "applyocalypse-signing-"));
    const workerPath = join(dir, "applyocalypse-worker.exe");
    writeFileSync(workerPath, "binary");

    await expect(signWorkerBinary(workerPath, "win32")).resolves.toEqual({
      signed: false,
      reason: "windows_signing_not_configured"
    });
  });

  it("fails release builds when signing is required but credentials are missing", async () => {
    const dir = mkdtempSync(join(tmpdir(), "applyocalypse-signing-"));
    const workerPath = join(dir, "applyocalypse-worker.exe");
    writeFileSync(workerPath, "binary");
    vi.stubEnv("APPLYO_REQUIRE_CODE_SIGNING", "1");

    await expect(signWorkerBinary(workerPath, "win32")).rejects.toThrow(/WINDOWS_SIGNTOOL_PATH/);
  });
});
