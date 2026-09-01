import { mkdirSync, mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { createRequire } from "node:module";
import { afterEach, describe, expect, it, vi } from "vitest";

const require = createRequire(import.meta.url);
const { batchByCommandLength, collectNativeBinaries, planSigningTargets, signWorkerTree } = require("./sign-worker-binary.cjs") as {
  batchByCommandLength: (paths: string[], maxLength?: number) => string[][];
  collectNativeBinaries: (rootDir: string, platform?: NodeJS.Platform | string) => string[];
  planSigningTargets: (workerPath: string, platform?: NodeJS.Platform | string) => string[];
  signWorkerTree: (
    workerPath: string,
    platform?: NodeJS.Platform | string
  ) => Promise<{ signed: boolean; reason: string; count: number }>;
};

// A miniature of what PyInstaller's onedir layout actually produces: a launcher
// with an _internal directory beside it holding the DLLs and extension modules
// the process maps, plus the data files that share the directory and must not be
// handed to signtool.
const makeOnedirWorker = (): { dir: string; workerPath: string } => {
  const dir = mkdtempSync(join(tmpdir(), "applyocalypse-signing-"));
  const internal = join(dir, "_internal");
  const nested = join(internal, "numpy", "core");
  mkdirSync(nested, { recursive: true });

  const workerPath = join(dir, "applyocalypse-worker.exe");
  writeFileSync(workerPath, "binary");
  writeFileSync(join(internal, "python312.dll"), "binary");
  writeFileSync(join(internal, "select.pyd"), "binary");
  writeFileSync(join(internal, "helper.EXE"), "binary");
  writeFileSync(join(internal, "base_library.zip"), "data");
  writeFileSync(join(internal, "worker-manifest.json"), "{}");
  writeFileSync(join(nested, "_multiarray_umath.pyd"), "binary");
  writeFileSync(join(nested, "LICENSE.txt"), "text");

  return { dir, workerPath };
};

describe("collectNativeBinaries", () => {
  it("finds every Windows native binary under the worker directory, at any depth", () => {
    const { dir } = makeOnedirWorker();

    const found = collectNativeBinaries(dir, "win32").map((path) => path.slice(dir.length + 1));

    expect(found).toEqual([
      join("_internal", "helper.EXE"),
      join("_internal", "numpy", "core", "_multiarray_umath.pyd"),
      join("_internal", "python312.dll"),
      join("_internal", "select.pyd"),
      "applyocalypse-worker.exe"
    ]);
  });

  it("leaves the data files that share the directory alone", () => {
    const { dir } = makeOnedirWorker();

    const found = collectNativeBinaries(dir, "win32").join("\n");

    expect(found).not.toMatch(/base_library\.zip|worker-manifest\.json|LICENSE\.txt/);
  });

  it("returns nothing for a platform with no signing extensions", () => {
    const { dir } = makeOnedirWorker();

    expect(collectNativeBinaries(dir, "linux")).toEqual([]);
  });
});

describe("planSigningTargets", () => {
  it("signs the nested binaries before the launcher, and the launcher only once", () => {
    const { workerPath } = makeOnedirWorker();

    const targets = planSigningTargets(workerPath, "win32");

    expect(targets.filter((path) => path === workerPath)).toHaveLength(1);
    expect(targets.at(-1)).toBe(workerPath);
    expect(targets).toHaveLength(5);
  });

  it("still recognises the launcher when the caller writes the path with forward slashes", () => {
    const { workerPath } = makeOnedirWorker();
    const slashed = workerPath.split("\\").join("/");

    const targets = planSigningTargets(slashed, "win32");

    // A raw string compare misses here, and the launcher lands in the list twice.
    expect(targets.filter((path) => path.endsWith("applyocalypse-worker.exe"))).toHaveLength(1);
    expect(targets).toHaveLength(5);
  });
});

describe("batchByCommandLength", () => {
  it("splits a list that would overrun the command line into several calls", () => {
    const paths = Array.from({ length: 10 }, (_, index) => `C:\\out\\_internal\\module-${index}.pyd`);

    const batches = batchByCommandLength(paths, 100);

    expect(batches.flat()).toEqual(paths);
    expect(batches.length).toBeGreaterThan(1);
    for (const batch of batches) {
      expect(batch.join(" ").length).toBeLessThanOrEqual(100);
    }
  });

  it("keeps a single path that exceeds the budget rather than dropping it", () => {
    const batches = batchByCommandLength(["C:\\a-very-long-path.dll"], 4);

    expect(batches).toEqual([["C:\\a-very-long-path.dll"]]);
  });
});

describe("signWorkerTree", () => {
  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it("skips local unsigned worker binaries when signing is not configured", async () => {
    const { workerPath } = makeOnedirWorker();

    await expect(signWorkerTree(workerPath, "win32")).resolves.toEqual({
      signed: false,
      reason: "windows_signing_not_configured",
      count: 0
    });
  });

  it("fails release builds when signing is required but credentials are missing", async () => {
    const { workerPath } = makeOnedirWorker();
    vi.stubEnv("APPLYO_REQUIRE_CODE_SIGNING", "1");

    await expect(signWorkerTree(workerPath, "win32")).rejects.toThrow(/WINDOWS_SIGNTOOL_PATH/);
  });

  it("refuses to report success for a worker that is not there", async () => {
    const dir = mkdtempSync(join(tmpdir(), "applyocalypse-signing-"));

    await expect(signWorkerTree(join(dir, "applyocalypse-worker.exe"), "win32")).rejects.toThrow(/does not exist/);
  });
});
