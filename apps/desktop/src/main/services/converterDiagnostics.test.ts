import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("node:child_process", () => ({ spawnSync: vi.fn() }));
vi.mock("node:fs", () => ({ existsSync: vi.fn() }));

import { spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import { checkConverters } from "./converterDiagnostics";

const originalPlatform = process.platform;
const setPlatform = (platform: NodeJS.Platform): void => {
  Object.defineProperty(process, "platform", { value: platform, configurable: true });
};

type SpawnResult = { status: number; stdout: string; stderr: string };
const spawnOk = (stdout: string): SpawnResult => ({ status: 0, stdout, stderr: "" });
const spawnFail = (): SpawnResult => ({ status: 1, stdout: "", stderr: "" });

beforeEach(() => {
  vi.mocked(spawnSync).mockReset();
  vi.mocked(existsSync).mockReset();
  setPlatform("win32");
});

afterEach(() => {
  setPlatform(originalPlatform);
});

describe("checkConverters", () => {
  it("reports every converter unavailable when nothing is found", () => {
    vi.mocked(existsSync).mockReturnValue(false);
    vi.mocked(spawnSync).mockReturnValue(spawnFail() as never);

    const result = checkConverters();

    for (const converter of [result.libreoffice, result.word, result.tectonic]) {
      expect(converter.available).toBe(false);
      expect(converter.version).toBeNull();
      expect(converter.path).toBeNull();
      expect(converter.installUrl.length).toBeGreaterThan(0);
    }
  });

  it("detects LibreOffice at a ProgramFiles path and reads its first version line", () => {
    vi.mocked(existsSync).mockImplementation((candidate) => String(candidate).endsWith("soffice.exe"));
    vi.mocked(spawnSync).mockImplementation((command, args) => {
      if (Array.isArray(args) && args[0] === "--version") {
        return spawnOk("LibreOffice 24.8.0.3 abc123\nsecond line should be dropped") as never;
      }
      return spawnFail() as never;
    });

    const result = checkConverters();

    expect(result.libreoffice.available).toBe(true);
    expect(result.libreoffice.version).toBe("LibreOffice 24.8.0.3 abc123");
    expect(result.libreoffice.path?.endsWith("soffice.exe")).toBe(true);
  });

  it("finds a binary on PATH and trims the discovered path", () => {
    vi.mocked(existsSync).mockReturnValue(false);
    vi.mocked(spawnSync).mockImplementation((command, args) => {
      if (Array.isArray(args) && args[0] === "tectonic") {
        return spawnOk("C:\\tools\\tectonic.exe\r\n") as never;
      }
      if (Array.isArray(args) && args[0] === "--version") {
        return spawnOk("Tectonic 0.15.0") as never;
      }
      return spawnFail() as never;
    });

    const result = checkConverters();

    expect(result.tectonic.available).toBe(true);
    expect(result.tectonic.path).toBe("C:\\tools\\tectonic.exe");
    expect(result.tectonic.version).toBe("Tectonic 0.15.0");
  });

  it("keeps a converter available even when --version yields nothing", () => {
    vi.mocked(existsSync).mockImplementation((candidate) => String(candidate).endsWith("soffice.exe"));
    vi.mocked(spawnSync).mockReturnValue(spawnFail() as never);

    const result = checkConverters();

    expect(result.libreoffice.available).toBe(true);
    expect(result.libreoffice.version).toBeNull();
  });

  it("never probes --version for Word", () => {
    vi.mocked(existsSync).mockImplementation((candidate) => String(candidate).toUpperCase().includes("WINWORD.EXE"));
    vi.mocked(spawnSync).mockReturnValue(spawnFail() as never);

    const result = checkConverters();

    expect(result.word.available).toBe(true);
    expect(result.word.version).toBeNull();
    for (const call of vi.mocked(spawnSync).mock.calls) {
      expect(String(call[0]).toUpperCase()).not.toContain("WINWORD");
    }
  });
});
