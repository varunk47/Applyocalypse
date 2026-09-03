import { app, BrowserWindow, globalShortcut } from "electron";
import { join } from "node:path";
import { QueueRepository, SettingsRepository, closeApplyocalypseDatabase } from "@applyocalypse/db";
import { createAppDatabase } from "./db/createAppDatabase";
import { registerIpcHandlers } from "./ipc/registerIpc";
import { LocalQueueScheduler } from "./scheduler/localQueueScheduler";
import { registerArtifactProtocolHandler, registerArtifactScheme } from "./services/artifactProtocol";
import { GeneratedFileCleanupService } from "./services/generatedFileCleanupService";
import { PythonWorkerSupervisor } from "./services/pythonWorkerSupervisor";
import { sweepStaleRunWorkDirs } from "./services/runWorkDirJanitor";
import { smokeDeadlineMs } from "./smokeDeadline";
import { ThemeController } from "./theme";
import { createMainWindow } from "./window";

let mainWindow: BrowserWindow | null = null;
let database: ReturnType<typeof createAppDatabase> | null = null;
let scheduler: LocalQueueScheduler | null = null;
let workerSupervisor: PythonWorkerSupervisor | null = null;
let cleanupTimer: NodeJS.Timeout | null = null;

const getWindows = (): BrowserWindow[] => BrowserWindow.getAllWindows();

registerArtifactScheme();

if (process.env.APPLYO_TEST_USER_DATA_DIR) {
  app.setPath("userData", process.env.APPLYO_TEST_USER_DATA_DIR);
}

const boot = async (): Promise<void> => {
  database = createAppDatabase();
  const appDatabase = database;
  const settingsRepository = new SettingsRepository(database);
  const queueRepository = new QueueRepository(database);
  const themeController = new ThemeController(settingsRepository, getWindows);
  const getSafeArtifactRoots = () => {
    const configuredOutputDir = settingsRepository.get("files.outputDir", app.getPath("downloads"));
    return Array.from(
      new Set([
        app.getPath("userData"),
        app.getPath("downloads"),
        join(app.getPath("temp"), "applyocalypse"),
        typeof configuredOutputDir === "string" ? configuredOutputDir : app.getPath("downloads")
      ])
    );
  };
  const supervisor = new PythonWorkerSupervisor(database, getWindows, getSafeArtifactRoots);
  workerSupervisor = supervisor;
  scheduler = new LocalQueueScheduler(database, queueRepository, supervisor);
  const isKnownArtifactPath = (localPath: string): boolean => {
    const row = appDatabase
      .prepare(
        `
        SELECT 1 AS ok FROM uploaded_files WHERE local_path = @localPath AND deleted_at IS NULL
        UNION SELECT 1 AS ok FROM generated_files WHERE local_path = @localPath AND deleted_at IS NULL
        UNION SELECT 1 AS ok FROM screenshots WHERE local_path = @localPath
        UNION SELECT 1 AS ok FROM browser_artifacts WHERE local_path = @localPath AND deleted_at IS NULL
        LIMIT 1
      `
      )
      .get({ localPath }) as { ok: number } | undefined;
    return Boolean(row);
  };
  const cleanupService = new GeneratedFileCleanupService(database, getSafeArtifactRoots);
  cleanupService.cleanupExpired();
  cleanupTimer = setInterval(() => cleanupService.cleanupExpired(), 60 * 60 * 1000);
  sweepStaleRunWorkDirs(join(app.getPath("userData"), "runs"));
  registerArtifactProtocolHandler({
    isAllowedPath: isKnownArtifactPath
  });

  registerIpcHandlers({
    db: database,
    settingsRepository,
    queueRepository,
    themeController,
    workerSupervisor: supervisor,
    getMainWindow: () => mainWindow,
    initialApprovedPaths: parseEnvStringArray("APPLYO_TEST_APPROVED_PATHS_JSON")
  });

  mainWindow = createMainWindow(themeController.getState());
  registerKeyboardShortcuts();
  if (process.env.APPLYO_BOOT_SMOKE === "1") {
    mainWindow.webContents.on("preload-error", (_event, preloadPath, error) => {
      console.error(`boot-smoke:preload-error ${preloadPath} ${error.message}`);
    });
    mainWindow.webContents.on("console-message", (_event, ...args: unknown[]) => {
      const details: { level?: unknown; message?: unknown; lineNumber?: unknown; sourceId?: unknown; sourceUrl?: unknown } =
        typeof args[0] === "object" && args[0] !== null
          ? (args[0] as { level?: string | number; message?: string; lineNumber?: number; sourceId?: string; sourceUrl?: string })
          : {
              level: args[0],
              message: args[1],
              lineNumber: args[2],
              sourceId: args[3]
            };
      console.error(
        `boot-smoke:renderer-console ${JSON.stringify({
          level: details.level,
          message: details.message,
          line: details.lineNumber,
          sourceId: details.sourceId ?? details.sourceUrl
        })}`
      );
    });
    mainWindow.webContents.on("render-process-gone", (_event, details) => {
      console.error(`boot-smoke:render-process-gone ${JSON.stringify(details)}`);
    });
    mainWindow.webContents.on("did-fail-load", (_event, errorCode, errorDescription, validatedURL) => {
      console.error(`boot-smoke:did-fail-load ${JSON.stringify({ errorCode, errorDescription, validatedURL })}`);
    });
    const timeout = setTimeout(() => {
      console.error("boot-smoke:timeout");
      app.exit(1);
    }, smokeDeadlineMs(15_000));
    mainWindow.webContents.once("did-finish-load", () => {
      void mainWindow?.webContents
        .executeJavaScript(
          `
            new Promise((resolve) => {
              const sample = () => {
                const bodyText = document.body?.innerText ?? "";
                const api = globalThis.applyocalypse;
                return {
                  hasShell: Boolean(document.querySelector(".app-shell")),
                  // innerText reflects text-transform, and the titlebar
                  // brand is uppercased, so compare case-insensitively.
                  hasBrand: bodyText.toLowerCase().includes("applyocalypse"),
                  navItemCount: document.querySelectorAll("[data-gsap='nav-item']").length,
                  panelCount: document.querySelectorAll("[data-gsap='panel']").length,
                  hasPreloadApi: Boolean(api?.theme?.getInitialState && api?.jobs?.enqueue && api?.runs?.approve),
                  htmlTheme: document.documentElement.dataset.theme ?? null
                };
              };
              // The routed screen is a lazy chunk mounted behind Suspense, and
              // first run waits on an async profile load before it even picks
              // a route. Sampling one frame after load races both, so poll
              // until a screen mounts and report the last sample either way.
              const deadline = Date.now() + 10_000;
              const poll = () => {
                const smoke = sample();
                if (smoke.panelCount >= 2 || Date.now() > deadline) {
                  resolve(smoke);
                  return;
                }
                setTimeout(poll, 100);
              };
              requestAnimationFrame(() => requestAnimationFrame(poll));
            });
          `,
          true
        )
        .then((result) => {
          const smoke = result as {
            hasShell?: boolean;
            hasBrand?: boolean;
            navItemCount?: number;
            panelCount?: number;
            hasPreloadApi?: boolean;
            htmlTheme?: string | null;
          };
          const passed =
            smoke.hasShell === true &&
            smoke.hasBrand === true &&
            // Dossier nav: brand mark + 5 destinations carry the nav-item marker.
            (smoke.navItemCount ?? 0) >= 5 &&
            // Routed screens mount one view panel at a time: topbar + active screen.
            (smoke.panelCount ?? 0) >= 2 &&
            smoke.hasPreloadApi === true &&
            (smoke.htmlTheme === "dark" || smoke.htmlTheme === "light");
          clearTimeout(timeout);
          if (passed) {
            console.log(`boot-smoke:alive ${JSON.stringify(smoke)}`);
            app.exit(0);
            return;
          }
          console.error(`boot-smoke:renderer-unready ${JSON.stringify(smoke)}`);
          app.exit(1);
        })
        .catch((error: unknown) => {
          clearTimeout(timeout);
          console.error(`boot-smoke:error ${error instanceof Error ? error.message : String(error)}`);
          app.exit(1);
        });
    });
  }
  if (process.env.APPLYO_USER_FLOW_SMOKE === "1") {
    const timeout = setTimeout(() => {
      console.error("user-flow-smoke:timeout");
      app.exit(1);
    }, smokeDeadlineMs(20_000));
    mainWindow.webContents.once("did-finish-load", () => {
      void mainWindow?.webContents
        .executeJavaScript(
          `
            (async () => {
              await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));
              const api = globalThis.applyocalypse;
              if (!api?.profile?.createStarter || !api?.jobs?.enqueue || !api?.theme?.setPreference) {
                return { hasPreloadApi: false };
              }
              const theme = await api.theme.setPreference("dark");
              const profile = await api.profile.createStarter({
                legalName: "Grace Hopper",
                email: "grace.hopper@example.com",
                location: "Arlington, VA",
                applicationEmail: "grace.hopper@example.com",
                applicationPassword: "Smoke#Pass123!"
              });
              const canonicalProfile = await api.profile.getCanonical(profile.id);
              const enqueue = await api.jobs.enqueue(profile.id, [
                {
                  sourceKind: "TEXT",
                  sourceValue: "Required: TypeScript, SQLite, browser automation, and user-reviewed job application controls.",
                  autoSubmitEnabled: false
                }
              ]);
              const concurrencySettings = await api.settings.update({ "automation.maxConcurrentApplications": 99 });
              const queue = await api.jobs.list(10, 0);
              const settings = await api.settings.get();
              let maliciousAnswerStatusRejected = false;
              try {
                await api.runs.updateAnswer("run-1", "answer-1", "Yes", "APPROVED");
              } catch {
                maliciousAnswerStatusRejected = true;
              }
              return {
                hasPreloadApi: true,
                activeTheme: theme.activeTheme,
                profileId: profile.id,
                canonicalProfileId: canonicalProfile?.profile?.id ?? null,
                canonicalExperienceCount: canonicalProfile?.experience?.length ?? null,
                profileEmail: profile.email,
                queueItemsCreated: enqueue.queueItems.length,
                queueTotal: queue.total,
                firstQueueStatus: queue.items[0]?.status ?? null,
                firstQueueAutoSubmit: queue.items[0]?.autoSubmitEnabled ?? null,
                settingsThemePreference: settings["theme.preference"] ?? null,
                settingsConcurrency: settings["automation.maxConcurrentApplications"] ?? null,
                concurrencyClampResult: concurrencySettings["automation.maxConcurrentApplications"] ?? null,
                rendererHasRequire: typeof globalThis.require === "function",
                rendererHasProcess: typeof globalThis.process === "object",
                exposesRawFs: Boolean(api.fs || api.sqlite || api.child_process),
                maliciousAnswerStatusRejected
              };
            })();
          `,
          true
        )
        .then((result) => {
          const smoke = result as {
            hasPreloadApi?: boolean;
            activeTheme?: string;
            profileId?: string;
            canonicalProfileId?: string | null;
            canonicalExperienceCount?: number | null;
            profileEmail?: string | null;
            queueItemsCreated?: number;
            queueTotal?: number;
            firstQueueStatus?: string | null;
            firstQueueAutoSubmit?: boolean | null;
            settingsThemePreference?: unknown;
            settingsConcurrency?: unknown;
            concurrencyClampResult?: unknown;
            rendererHasRequire?: boolean;
            rendererHasProcess?: boolean;
            exposesRawFs?: boolean;
            maliciousAnswerStatusRejected?: boolean;
          };
          const passed =
            smoke.hasPreloadApi === true &&
            smoke.activeTheme === "dark" &&
            typeof smoke.profileId === "string" &&
            smoke.canonicalProfileId === smoke.profileId &&
            smoke.canonicalExperienceCount === 0 &&
            smoke.profileEmail === "grace.hopper@example.com" &&
            smoke.queueItemsCreated === 1 &&
            (smoke.queueTotal ?? 0) >= 1 &&
            smoke.firstQueueStatus === "PENDING" &&
            smoke.firstQueueAutoSubmit === false &&
            smoke.settingsThemePreference === "dark" &&
            smoke.settingsConcurrency === 3 &&
            smoke.concurrencyClampResult === 3 &&
            smoke.rendererHasRequire === false &&
            smoke.rendererHasProcess === false &&
            smoke.exposesRawFs === false &&
            smoke.maliciousAnswerStatusRejected === true;
          clearTimeout(timeout);
          if (passed) {
            console.log(`user-flow-smoke:passed ${JSON.stringify(smoke)}`);
            app.exit(0);
            return;
          }
          console.error(`user-flow-smoke:failed ${JSON.stringify(smoke)}`);
          app.exit(1);
        })
        .catch((error: unknown) => {
          clearTimeout(timeout);
          console.error(`user-flow-smoke:error ${error instanceof Error ? error.message : String(error)}`);
          app.exit(1);
        });
    });
  }
  if (process.env.APPLYO_FULL_E2E_SMOKE === "1") {
    const phase = process.env.APPLYO_FULL_E2E_SMOKE_PHASE ?? "phase1";
    const resumePath = process.env.APPLYO_FULL_E2E_RESUME_PATH ?? "";
    const detailsPath = process.env.APPLYO_FULL_E2E_DETAILS_PATH ?? "";
    const timeout = setTimeout(() => {
      console.error(`full-e2e-smoke:${phase}:timeout`);
      app.exit(1);
    }, smokeDeadlineMs(25_000));
    mainWindow.webContents.once("did-finish-load", () => {
      void mainWindow?.webContents
        .executeJavaScript(
          buildFullE2ESmokeScript({
            phase,
            resumePath,
            detailsPath
          }),
          true
        )
        .then((result) => {
          const smoke = result as {
            phase?: string;
            passed?: boolean;
            profileId?: string;
            uploadCount?: number;
            parsedCount?: number;
            queueTotal?: number;
            rendererHasRequire?: boolean;
            rendererHasProcess?: boolean;
            error?: string;
          };
          clearTimeout(timeout);
          if (smoke.passed === true) {
            console.log(`full-e2e-smoke:${phase}:passed ${JSON.stringify(smoke)}`);
            app.exit(0);
            return;
          }
          console.error(`full-e2e-smoke:${phase}:failed ${JSON.stringify(smoke)}`);
          app.exit(1);
        })
        .catch((error: unknown) => {
          clearTimeout(timeout);
          console.error(`full-e2e-smoke:${phase}:error ${error instanceof Error ? error.message : String(error)}`);
          app.exit(1);
        });
    });
  }
  if (process.env.APPLYO_DISABLE_SCHEDULER !== "1") {
    scheduler.start();
  }
};

const parseEnvStringArray = (key: string): string[] => {
  const raw = process.env[key];
  if (!raw) {
    return [];
  }
  try {
    const parsed = JSON.parse(raw) as unknown;
    return Array.isArray(parsed) ? parsed.filter((item): item is string => typeof item === "string" && item.length > 0) : [];
  } catch {
    return [];
  }
};

const buildFullE2ESmokeScript = (input: { phase: string; resumePath: string; detailsPath: string }): string => {
  const phase = JSON.stringify(input.phase);
  const resumePath = JSON.stringify(input.resumePath);
  const detailsPath = JSON.stringify(input.detailsPath);
  return `
    (async () => {
      await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));
      const api = globalThis.applyocalypse;
      if (!api?.profile?.createStarter || !api?.documents?.ingestResumeSource || !api?.jobs?.enqueue) {
        return { phase: ${phase}, passed: false, error: "preload_api_missing" };
      }
      if (${phase} === "phase1") {
        const profile = await api.profile.createStarter({
          legalName: "Ada Lovelace",
          email: "ada.lovelace@example.com",
          location: "Chicago, IL",
          applicationEmail: "ada.lovelace@example.com",
          applicationPassword: "Smoke#Pass123!"
        });
        const resume = await api.documents.ingestResumeSource({
          profileId: profile.id,
          localPath: ${resumePath}
        });
        const supporting = await api.files.registerUpload({
          profileId: profile.id,
          localPath: ${detailsPath},
          fileKind: "SUPPORTING_DETAILS"
        });
        const enqueue = await api.jobs.enqueue(profile.id, [
          {
            sourceKind: "TEXT",
            sourceValue: "Platform engineer role requiring TypeScript, SQLite, Python automation, browser control, and user-reviewed final submission.",
            autoSubmitEnabled: false
          }
        ]);
        const uploads = await api.files.listUploads(profile.id);
        const parsed = await api.documents.listParsed({ profileId: profile.id });
        return {
          phase: "phase1",
          passed: Boolean(
            resume.sourceFile?.id &&
            supporting.uploadedFile?.id &&
            uploads.items.length >= 2 &&
            parsed.items.length >= 1 &&
            enqueue.queueItems.length === 1
          ),
          profileId: profile.id,
          uploadCount: uploads.items.length,
          parsedCount: parsed.items.length,
          queueTotal: enqueue.queueItems.length,
          rendererHasRequire: typeof globalThis.require === "function",
          rendererHasProcess: typeof globalThis.process === "object"
        };
      }
      const profile = await api.profile.get();
      const uploads = await api.files.listUploads(profile?.id ?? null);
      const parsed = await api.documents.listParsed({ profileId: profile?.id ?? null });
      const queue = await api.jobs.list(10, 0);
      let approvedAnswerRejected = false;
      try {
        await api.runs.updateAnswer("run-1", "answer-1", "Unsafe", "APPROVED");
      } catch {
        approvedAnswerRejected = true;
      }
      return {
        phase: "phase2",
        passed:
          profile?.email === "ada.lovelace@example.com" &&
          uploads.items.length >= 2 &&
          parsed.items.length >= 1 &&
          queue.total >= 1 &&
          queue.items[0]?.autoSubmitEnabled === false &&
          approvedAnswerRejected &&
          typeof globalThis.require !== "function" &&
          typeof globalThis.process !== "object",
        profileId: profile?.id ?? null,
        uploadCount: uploads.items.length,
        parsedCount: parsed.items.length,
        queueTotal: queue.total,
        rendererHasRequire: typeof globalThis.require === "function",
        rendererHasProcess: typeof globalThis.process === "object"
      };
    })();
  `;
};

void app.whenReady().then(boot);

app.on("activate", () => {
  if (BrowserWindow.getAllWindows().length === 0 && database) {
    const settingsRepository = new SettingsRepository(database);
    const themeController = new ThemeController(settingsRepository, getWindows);
    mainWindow = createMainWindow(themeController.getState());
  }
});

const SCREEN_ROUTES = ['/', '/run', '/documents', '/profile', '/history', '/settings'];

const registerKeyboardShortcuts = (): void => {
  SCREEN_ROUTES.forEach((route, index) => {
    const key = `CmdOrCtrl+${index + 1}`;
    globalShortcut.register(key, () => {
      mainWindow?.webContents.send('navigate', route);
    });
  });
  globalShortcut.register('CmdOrCtrl+P', () => {
    mainWindow?.webContents.send('navigate', '/');
    mainWindow?.webContents.send('focus-intake');
  });
  globalShortcut.register('Escape', () => {
    mainWindow?.webContents.send('close-modal');
  });
};

app.on("will-quit", () => {
  globalShortcut.unregisterAll();
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") {
    app.quit();
  }
});

app.on("before-quit", () => {
  scheduler?.stop();
  scheduler = null;
  workerSupervisor?.stopAll();
  workerSupervisor = null;
  if (cleanupTimer) {
    clearInterval(cleanupTimer);
    cleanupTimer = null;
  }
  if (database) {
    closeApplyocalypseDatabase(database);
    database = null;
  }
});
