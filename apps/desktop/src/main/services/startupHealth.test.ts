import { resolve } from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

let connectedProvider: { provider: string } | null = null;
let workerExecutable: string | (() => never) = "";
let convertersAvailable = true;

vi.mock("@applyocalypse/db", () => ({
  ProviderRepository: class {
    getFirstConnectedSecretReference() {
      return connectedProvider;
    }
  }
}));

vi.mock("./pythonWorkerPaths", () => ({
  resolvePythonWorkerLaunch: () => {
    if (typeof workerExecutable === "function") workerExecutable();
    return { executable: workerExecutable, baseArgs: [], cwd: "." };
  }
}));

vi.mock("./converterDiagnostics", () => ({
  checkConverters: () => ({
    libreoffice: { available: convertersAvailable, version: null, path: null, installUrl: "https://libreoffice.example" },
    word: { available: false, version: null, path: null, installUrl: "" },
    tectonic: { available: false, version: null, path: null, installUrl: "" }
  })
}));

vi.mock("node:fs", () => ({ existsSync: vi.fn(() => true) }));

import { existsSync } from "node:fs";
import { checkStartupHealth } from "./startupHealth";

const db = {} as never;
const ids = () => checkStartupHealth(db).map((finding) => finding.id);

beforeEach(() => {
  // A machine with everything it needs, which each test then takes one thing from.
  connectedProvider = { provider: "openai" };
  // A full path on this OS, so the check looks on disk instead of probing PATH.
  workerExecutable = resolve("/app/worker.exe");
  convertersAvailable = true;
  vi.mocked(existsSync).mockReturnValue(true);
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("startup health", () => {
  it("says nothing when the machine has everything", () => {
    expect(checkStartupHealth(db)).toEqual([]);
  });

  it("reports a worker binary that is not on disk", () => {
    vi.mocked(existsSync).mockReturnValue(false);
    const [finding] = checkStartupHealth(db);
    expect(finding?.id).toBe("AUTOMATION_WORKER");
    expect(finding?.severity).toBe("BLOCKING");
    // The path is the whole point: it is what the user has to go and look at.
    expect(finding?.fix).toContain("worker.exe");
  });

  it("reports a worker that cannot be resolved at all", () => {
    workerExecutable = () => {
      throw new Error("Bundled Applyocalypse worker was not found at /nope");
    };
    const [finding] = checkStartupHealth(db);
    expect(finding?.id).toBe("AUTOMATION_WORKER");
    expect(finding?.fix).toContain("/nope");
  });

  it("reports a missing model provider as blocking, not as a degraded mode", () => {
    // Without a key the worker falls back to deterministic templates, which is
    // the silent success this check exists to prevent.
    connectedProvider = null;
    const [finding] = checkStartupHealth(db);
    expect(finding?.id).toBe("MODEL_PROVIDER");
    expect(finding?.severity).toBe("BLOCKING");
    expect(finding?.route).toBe("/settings");
  });

  it("reports a missing converter as degraded, because documents are still written", () => {
    convertersAvailable = false;
    const [finding] = checkStartupHealth(db);
    expect(finding?.id).toBe("PDF_CONVERTER");
    expect(finding?.severity).toBe("DEGRADED");
    expect(finding?.link).toBe("https://libreoffice.example");
  });

  it("puts what stops everything ahead of what only degrades it", () => {
    connectedProvider = null;
    convertersAvailable = false;
    vi.mocked(existsSync).mockReturnValue(false);
    expect(ids()).toEqual(["AUTOMATION_WORKER", "MODEL_PROVIDER", "PDF_CONVERTER"]);
  });
});
