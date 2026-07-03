import { ipcMain } from "electron";
import { isAbsolute, normalize, resolve } from "node:path";
import type { BrowserWindow } from "electron";
import {
  ChatRepository,
  JobRepository,
  ProfileRepository,
  ProviderRepository,
  RunRepository,
  UploadRepository,
  AuditRepository,
  ParsedDocumentRepository,
  type ApplyocalypseDatabase,
  type QueueRepository,
  type SettingsRepository
} from "@applyocalypse/db";
import type { JobTarget } from "@applyocalypse/db";
import type { IpcContract } from "@applyocalypse/ipc-contracts";
import type { z } from "zod";
import type { ThemeController } from "../../theme";
import { DocumentIngestionService } from "../../services/documentIngestionService";
import type { PythonWorkerSupervisor } from "../../services/pythonWorkerSupervisor";
import { SecureSecretStore } from "../../services/secureSecretStore";

export type RegisterIpcHandlersInput = {
  db: ApplyocalypseDatabase;
  settingsRepository: SettingsRepository;
  queueRepository: QueueRepository;
  themeController: ThemeController;
  workerSupervisor: PythonWorkerSupervisor;
  getMainWindow: () => BrowserWindow | null;
  initialApprovedPaths?: string[];
};

/**
 * Typed wrapper binding an IpcContracts entry to ipcMain.handle with Zod parse.
 * Stateless — shared verbatim by every handler module.
 */
export const handleContract = <Request extends z.ZodTypeAny, Response extends z.ZodTypeAny>(
  ipcContract: IpcContract<Request, Response>,
  handler: (request: z.infer<Request>) => Promise<z.infer<Response>> | z.infer<Response>
): void => {
  ipcMain.handle(ipcContract.channel, async (_event, rawRequest) => {
    const request = ipcContract.request.parse(rawRequest ?? {});
    const response = await handler(request);
    return ipcContract.response.parse(response);
  });
};

/** Resolve job targets for list responses; hard-deleted targets are skipped. */
export const lookupJobTargets = (jobRepository: JobRepository, jobTargetIds: string[]): JobTarget[] => {
  const targets: JobTarget[] = [];
  for (const id of new Set(jobTargetIds)) {
    try {
      targets.push(jobRepository.getTargetById(id));
    } catch {
      // Renderer falls back to the run id when a target row is gone.
    }
  }
  return targets;
};

/**
 * Shared dependencies and security closures threaded into every domain handler
 * module. Built once per registerIpcHandlers call.
 */
export interface IpcHandlerContext {
  db: ApplyocalypseDatabase;
  settingsRepository: SettingsRepository;
  queueRepository: QueueRepository;
  themeController: ThemeController;
  workerSupervisor: PythonWorkerSupervisor;
  getMainWindow: () => BrowserWindow | null;
  chatRepository: ChatRepository;
  profileRepository: ProfileRepository;
  jobRepository: JobRepository;
  uploadRepository: UploadRepository;
  parsedDocumentRepository: ParsedDocumentRepository;
  providerRepository: ProviderRepository;
  runRepository: RunRepository;
  auditRepository: AuditRepository;
  secureSecretStore: SecureSecretStore;
  documentIngestionService: DocumentIngestionService;
  normalizeUserPath: (localPath: string) => string;
  requirePickedPath: (localPath: string) => string;
  requireOpenablePath: (localPath: string) => string;
  approvePickedPath: (localPath: string) => void;
}

export const createIpcHandlerContext = ({
  db,
  settingsRepository,
  queueRepository,
  themeController,
  workerSupervisor,
  getMainWindow,
  initialApprovedPaths = []
}: RegisterIpcHandlersInput): IpcHandlerContext => {
  const chatRepository = new ChatRepository(db);
  const profileRepository = new ProfileRepository(db);
  const jobRepository = new JobRepository(db);
  const uploadRepository = new UploadRepository(db);
  const parsedDocumentRepository = new ParsedDocumentRepository(db);
  const providerRepository = new ProviderRepository(db);
  const runRepository = new RunRepository(db);
  const auditRepository = new AuditRepository(db);
  const secureSecretStore = new SecureSecretStore();
  const documentIngestionService = new DocumentIngestionService(uploadRepository, parsedDocumentRepository);

  // `approvedPickedPaths` stays private to this module; approvePickedPath /
  // requirePickedPath are its only doors, preserving the security property that
  // nothing else can whitelist a path.
  const approvedPickedPaths = new Set<string>();
  const normalizeUserPath = (localPath: string): string => {
    if (localPath.includes("\0")) {
      throw new Error("Path contains invalid characters");
    }
    if (!isAbsolute(localPath)) {
      throw new Error("Path must be absolute");
    }
    return normalize(resolve(localPath));
  };
  const approvePickedPath = (localPath: string): void => {
    approvedPickedPaths.add(normalizeUserPath(localPath));
  };
  const requirePickedPath = (localPath: string): string => {
    const normalized = normalizeUserPath(localPath);
    if (!approvedPickedPaths.has(normalized)) {
      throw new Error("Path was not selected through the Applyocalypse file picker");
    }
    return normalized;
  };
  for (const localPath of initialApprovedPaths) {
    approvedPickedPaths.add(normalizeUserPath(localPath));
  }
  const isKnownArtifactPath = (localPath: string): boolean => {
    const row = db
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
  const requireOpenablePath = (localPath: string): string => {
    const normalized = normalizeUserPath(localPath);
    if (approvedPickedPaths.has(normalized) || isKnownArtifactPath(normalized)) {
      return normalized;
    }
    throw new Error("Path is not an Applyocalypse artifact or approved picked file");
  };

  return {
    db,
    settingsRepository,
    queueRepository,
    themeController,
    workerSupervisor,
    getMainWindow,
    chatRepository,
    profileRepository,
    jobRepository,
    uploadRepository,
    parsedDocumentRepository,
    providerRepository,
    runRepository,
    auditRepository,
    secureSecretStore,
    documentIngestionService,
    normalizeUserPath,
    requirePickedPath,
    requireOpenablePath,
    approvePickedPath
  };
};
