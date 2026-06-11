import { spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import { join } from "node:path";

export interface ConverterStatus {
  available: boolean;
  version: string | null;
  path: string | null;
  installUrl: string;
}

export interface ConverterDiagnostics {
  libreoffice: ConverterStatus;
  word: ConverterStatus;
  tectonic: ConverterStatus;
}

const LIBRE_OFFICE_INSTALL_URL = "https://www.libreoffice.org/download/download/";
const WORD_INSTALL_URL = "https://www.microsoft.com/en-us/microsoft-365";
const TECTONIC_INSTALL_URL = "https://tectonic-typesetting.github.io/";

const WIN_PROGRAM_BASES = (): string[] => [
  process.env["PROGRAMFILES"] ?? "C:\\Program Files",
  process.env["ProgramFiles(x86)"] ?? "C:\\Program Files (x86)"
];

const findOnPath = (binaryName: string): string | null => {
  const finder = process.platform === "win32" ? "where" : "which";
  const result = spawnSync(finder, [binaryName], { encoding: "utf8", timeout: 4000 });
  if (result.status === 0) {
    return result.stdout.trim().split("\n")[0]?.trim() ?? null;
  }
  return null;
};

const findLibreOffice = (): string | null => {
  if (process.platform === "win32") {
    for (const base of WIN_PROGRAM_BASES()) {
      const candidate = join(base, "LibreOffice", "program", "soffice.exe");
      if (existsSync(candidate)) return candidate;
    }
  }
  return findOnPath("soffice");
};

const findWord = (): string | null => {
  if (process.platform !== "win32") return null;
  const relPaths = [
    "Microsoft Office\\root\\Office16\\WINWORD.EXE",
    "Microsoft Office\\Office16\\WINWORD.EXE",
    "Microsoft Office\\root\\Office15\\WINWORD.EXE",
    "Microsoft Office\\Office15\\WINWORD.EXE"
  ];
  for (const base of WIN_PROGRAM_BASES()) {
    for (const rel of relPaths) {
      const candidate = join(base, rel);
      if (existsSync(candidate)) return candidate;
    }
  }
  return null;
};

const findTectonic = (): string | null => findOnPath("tectonic");

const readVersion = (execPath: string): string | null => {
  try {
    const result = spawnSync(execPath, ["--version"], { encoding: "utf8", timeout: 8000 });
    const raw = (result.stdout || result.stderr || "").trim();
    return raw.split("\n")[0]?.trim() || null;
  } catch {
    return null;
  }
};

export const checkConverters = (): ConverterDiagnostics => {
  const libreOfficePath = findLibreOffice();
  const wordPath = findWord();
  const tectonicPath = findTectonic();
  return {
    libreoffice: {
      available: libreOfficePath !== null,
      version: libreOfficePath ? readVersion(libreOfficePath) : null,
      path: libreOfficePath,
      installUrl: LIBRE_OFFICE_INSTALL_URL
    },
    word: {
      available: wordPath !== null,
      version: null,
      path: wordPath,
      installUrl: WORD_INSTALL_URL
    },
    tectonic: {
      available: tectonicPath !== null,
      version: tectonicPath ? readVersion(tectonicPath) : null,
      path: tectonicPath,
      installUrl: TECTONIC_INSTALL_URL
    }
  };
};
