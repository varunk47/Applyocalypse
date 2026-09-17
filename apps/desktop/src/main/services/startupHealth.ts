import { spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import { sep } from "node:path";
import { ProviderRepository, type ApplyocalypseDatabase } from "@applyocalypse/db";
import { checkConverters } from "./converterDiagnostics";
import { resolvePythonWorkerLaunch } from "./pythonWorkerPaths";

/**
 * What the app needs from the machine, asked before a run needs it.
 *
 * Every external dependency except SQLite was resolved lazily, inside a run the
 * user had already committed to: no model key meant documents quietly built
 * from templates, a missing worker meant a run that stalled with nothing to
 * read. Each of these is fixable in a minute by someone who is told, so they
 * are checked up front and named.
 */
export type HealthSeverity = "BLOCKING" | "DEGRADED";

export interface HealthFinding {
  id: string;
  severity: HealthSeverity;
  /** What is wrong, in one line. */
  title: string;
  /** What will actually happen if it is left alone. */
  consequence: string;
  /** What to do about it. */
  fix: string;
  /** In-app destination, when the fix is in the app. */
  route: string | null;
  /** External download, when the fix is not. */
  link: string | null;
}

const PYTHON_PROBE_TIMEOUT_MS = 5_000;

/**
 * The worker launcher falls back to a bare "python" on PATH, which may not
 * exist. Anything with a path separator is checked on disk; a bare name has to
 * be asked, because that is the only way to find out.
 */
const workerExecutableExists = (executable: string): boolean => {
  if (executable.includes(sep) || executable.includes("/")) {
    return existsSync(executable);
  }
  const probe = spawnSync(executable, ["--version"], { encoding: "utf8", timeout: PYTHON_PROBE_TIMEOUT_MS });
  return probe.status === 0;
};

const checkAutomationWorker = (): HealthFinding | null => {
  let executable: string;
  try {
    executable = resolvePythonWorkerLaunch().executable;
  } catch (error) {
    return {
      id: "AUTOMATION_WORKER",
      severity: "BLOCKING",
      title: "The automation worker is missing",
      consequence: "No application can run. Every job you queue will stop before it opens a browser.",
      fix: error instanceof Error ? error.message : "Reinstall Applyocalypse.",
      route: null,
      link: null
    };
  }

  if (workerExecutableExists(executable)) {
    return null;
  }

  return {
    id: "AUTOMATION_WORKER",
    severity: "BLOCKING",
    title: "The automation worker cannot be started",
    consequence: "No application can run. Every job you queue will stop before it opens a browser.",
    fix: `Applyocalypse expected to start it with "${executable}", which is not there. In a development checkout, run pnpm dev once to build the Python environment.`,
    route: null,
    link: null
  };
};

const checkModelProvider = (db: ApplyocalypseDatabase): HealthFinding | null => {
  if (new ProviderRepository(db).getFirstConnectedSecretReference()) {
    return null;
  }
  return {
    id: "MODEL_PROVIDER",
    severity: "BLOCKING",
    title: "No model provider is connected",
    consequence:
      "Tailoring and cover letters need a model. Without a key, runs stop at the document step rather than sending something generic.",
    fix: "Add an API key for a provider in Settings.",
    route: "/settings",
    link: null
  };
};

const checkPdfConverter = (): HealthFinding | null => {
  const converters = checkConverters();
  if (converters.libreoffice.available || converters.word.available) {
    return null;
  }
  return {
    id: "PDF_CONVERTER",
    severity: "DEGRADED",
    title: "No PDF converter is installed",
    consequence:
      "Tailored resumes will still be written, but as DOCX only. Portals that accept nothing but PDF will have to be filled by hand.",
    fix: "Install LibreOffice, or Microsoft Word if you have it.",
    route: null,
    link: converters.libreoffice.installUrl
  };
};

/**
 * Ordered worst first, so a caller showing one finding shows the one that stops
 * the most from working.
 */
export const checkStartupHealth = (db: ApplyocalypseDatabase): HealthFinding[] =>
  [checkAutomationWorker(), checkModelProvider(db), checkPdfConverter()].filter(
    (finding): finding is HealthFinding => finding !== null
  );
