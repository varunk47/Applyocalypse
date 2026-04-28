import { contextBridge, ipcRenderer } from "electron";
import { IpcChannels, IpcContracts, RendererEventSchemas } from "@applyocalypse/ipc-contracts";
import type {
  ApplicationAnswer,
  ApplicationRun,
  ApplicationStep,
  Approval,
  BrowserArtifact,
  CanonicalProfile,
  GeneratedFile,
  JobTarget,
  ParsedDocument,
  ParsedDocumentMergeSummary,
  Profile,
  ProviderConnection,
  QueueItem,
  ReviewRequest,
  RunEvent,
  SafeRendererRunEvent,
  Screenshot,
  ThemePreference,
  ThemeState,
  UploadedFile
} from "@applyocalypse/shared-types";

const invoke = async <Request, Response>(channel: string, request: Request): Promise<Response> =>
  ipcRenderer.invoke(channel, request) as Promise<Response>;

const api = {
  app: {
    getVersion: () => invoke<Record<string, never>, { version: string }>(IpcContracts.appGetVersion.channel, {})
  },
  theme: {
    getInitialState: (): ThemeState => IpcContracts.themeGetInitialState.response.parse(ipcRenderer.sendSync(IpcChannels.themeGetInitialState)),
    setPreference: (preference: ThemePreference) =>
      invoke<{ preference: ThemePreference }, ThemeState>(IpcContracts.themeSetPreference.channel, { preference }),
    subscribe: (listener: (state: ThemeState) => void) => {
      const wrapped = (_event: Electron.IpcRendererEvent, value: unknown) => {
        listener(RendererEventSchemas.themeUpdated.parse(value));
      };
      ipcRenderer.on(IpcChannels.themeUpdated, wrapped);
      return () => ipcRenderer.off(IpcChannels.themeUpdated, wrapped);
    }
  },
  settings: {
    get: () => invoke<Record<string, never>, Record<string, unknown>>(IpcContracts.settingsGet.channel, {}),
    update: (patch: Record<string, unknown>) => invoke<{ patch: Record<string, unknown> }, Record<string, unknown>>(IpcContracts.settingsUpdate.channel, { patch })
  },
  providers: {
    list: () => invoke<Record<string, never>, { items: ProviderConnection[] }>(IpcContracts.providersList.channel, {}),
    saveApiKey: (input: {
      provider: ProviderConnection["provider"];
      displayName: string;
      apiKey: string;
      metadata?: Record<string, unknown>;
    }) => invoke<typeof input, ProviderConnection>(IpcContracts.providersSaveApiKey.channel, input)
  },
  documents: {
    ingestResumeSource: (input: { profileId: string | null; localPath: string }) =>
      invoke<typeof input, {
        sourceFile: UploadedFile;
        editableMasterCandidate: UploadedFile | null;
        parsing: ParsedDocumentMergeSummary | null;
        requiresUserVerification: boolean;
        userMessage: string;
      }>(IpcContracts.documentsIngestResumeSource.channel, input),
    confirmEditableMaster: (uploadedFileId: string) =>
      invoke<{ uploadedFileId: string }, UploadedFile>(IpcContracts.documentsConfirmEditableMaster.channel, { uploadedFileId }),
    repairEditableMasterAnchors: (uploadedFileId: string) =>
      invoke<{ uploadedFileId: string }, {
        anchoredCandidate: UploadedFile;
        parsing: ParsedDocumentMergeSummary | null;
        addedPlaceholders: string[];
        alreadyPresentPlaceholders: string[];
        warnings: string[];
        userMessage: string;
      }>(IpcContracts.documentsRepairEditableMasterAnchors.channel, { uploadedFileId }),
    listParsed: (input: { uploadedFileId?: string; profileId?: string | null }) =>
      invoke<typeof input, { items: ParsedDocument[] }>(IpcContracts.documentsListParsed.channel, input)
  },
  profile: {
    get: () => invoke<Record<string, never>, Profile | null>(IpcContracts.profileGet.channel, {}),
    getCanonical: (profileId?: string) =>
      invoke<{ profileId?: string }, CanonicalProfile | null>(
        IpcContracts.profileGetCanonical.channel,
        profileId ? { profileId } : {}
      ),
    createStarter: (input: {
      legalName: string;
      email?: string | null;
      location?: string | null;
      applicationEmail: string;
      applicationPassword: string;
      gmailOtpEnabled?: boolean;
    }) =>
      invoke<typeof input, Profile>(IpcContracts.profileCreateStarter.channel, input),
    configureApplicationCredentials: (input: {
      profileId: string;
      applicationEmail: string;
      applicationPassword: string;
      gmailOtpEnabled?: boolean;
    }) => invoke<typeof input, Profile>(IpcContracts.profileConfigureApplicationCredentials.channel, input),
    update: (profile: Profile) => invoke<{ profile: Profile }, Profile>(IpcContracts.profileUpdate.channel, { profile })
  },
  files: {
    pick: (purpose: "resume" | "cover_letter" | "supporting_details" | "other") =>
      invoke<{ purpose: typeof purpose }, { canceled: boolean; paths: string[] }>(IpcContracts.filesPick.channel, { purpose }),
    listUploads: (profileId?: string | null) =>
      invoke<{ profileId?: string | null }, { items: UploadedFile[] }>(
        IpcContracts.filesListUploads.channel,
        profileId === undefined ? {} : { profileId }
      ),
    registerUpload: (input: { profileId: string | null; localPath: string; fileKind: "RESUME" | "COVER_LETTER" | "SUPPORTING_DETAILS" | "OTHER" }) =>
      invoke<typeof input, { uploadedFile: UploadedFile; parsing: ParsedDocumentMergeSummary | null }>(IpcContracts.filesRegisterUpload.channel, input),
    openLocalPath: (localPath: string) => invoke<{ localPath: string }, { opened: boolean }>(IpcContracts.filesOpenLocalPath.channel, { localPath })
  },
  jobs: {
    enqueue: (profileId: string, items: Array<{ sourceKind: "URL" | "TEXT"; sourceValue: string; autoSubmitEnabled?: boolean }>) =>
      invoke<
        { profileId: string; items: Array<{ sourceKind: "URL" | "TEXT"; sourceValue: string; autoSubmitEnabled?: boolean }> },
        { jobTargets: JobTarget[]; queueItems: QueueItem[] }
      >(IpcContracts.jobsEnqueue.channel, { profileId, items }),
    list: (limit = 50, offset = 0) => invoke<{ limit: number; offset: number }, { items: QueueItem[]; total: number }>(IpcContracts.jobsList.channel, { limit, offset }),
    get: (runId: string) => invoke(IpcContracts.jobsGet.channel, { runId })
  },
  runs: {
    pause: (runId: string) => invoke(IpcContracts.runsPause.channel, { runId }),
    resume: (runId: string) => invoke(IpcContracts.runsResume.channel, { runId }),
    cancel: (runId: string) => invoke(IpcContracts.runsCancel.channel, { runId }),
    list: (limit = 50, offset = 0) =>
      invoke<{ limit: number; offset: number }, { items: ApplicationRun[]; total: number }>(IpcContracts.runsList.channel, { limit, offset }),
    getDetail: (runId: string) =>
      invoke<{ runId: string }, {
        run: ApplicationRun;
        steps: ApplicationStep[];
        answers: ApplicationAnswer[];
        reviewRequests: ReviewRequest[];
        generatedFiles: GeneratedFile[];
        browserArtifacts: BrowserArtifact[];
        events: RunEvent[];
      }>(IpcContracts.runsGetDetail.channel, { runId }),
    listAnswers: (runId: string) =>
      invoke<{ runId: string }, { items: ApplicationAnswer[] }>(IpcContracts.runsListAnswers.channel, { runId }),
    updateAnswer: (runId: string, answerId: string, userValue: string | null, status: "EDITED" | "REJECTED") =>
      invoke<{ runId: string; answerId: string; userValue: string | null; status: "EDITED" | "REJECTED" }, ApplicationAnswer>(
        IpcContracts.runsUpdateAnswer.channel,
        { runId, answerId, userValue, status }
      ),
    listReviewRequests: (runId: string) =>
      invoke<{ runId: string }, { items: ReviewRequest[] }>(IpcContracts.runsListReviewRequests.channel, { runId }),
    resolveReview: (runId: string, reviewRequestId: string, status: "APPROVED" | "REJECTED", reason?: string) =>
      invoke<{ runId: string; reviewRequestId: string; status: "APPROVED" | "REJECTED"; reason?: string }, { accepted: boolean }>(
        IpcContracts.runsResolveReview.channel,
        { runId, reviewRequestId, status, ...(reason ? { reason } : {}) }
      ),
    retryStep: (runId: string, stepId: string) => invoke(IpcContracts.runsRetryStep.channel, { runId, stepId }),
    skipStep: (runId: string, stepId: string) => invoke(IpcContracts.runsSkipStep.channel, { runId, stepId }),
    approve: (runId: string, approvalType: Approval["approvalType"]) => invoke(IpcContracts.runsApprove.channel, { runId, approvalType }),
    reject: (runId: string, reason: string, approvalType?: Approval["approvalType"]) =>
      invoke(IpcContracts.runsReject.channel, { runId, reason, ...(approvalType ? { approvalType } : {}) })
  },
  logs: {
    subscribe: (runId: string, listener: (event: SafeRendererRunEvent) => void) => {
      const wrapped = (_event: Electron.IpcRendererEvent, value: unknown) => {
        const parsed = RendererEventSchemas.logsEvent.parse(value);
        if (parsed.runId === runId) {
          listener(parsed);
        }
      };
      ipcRenderer.on(IpcChannels.logsEvent, wrapped);
      void ipcRenderer.invoke(IpcContracts.logsSubscribe.channel, { runId });
      return () => ipcRenderer.off(IpcChannels.logsEvent, wrapped);
    }
  },
  screenshots: {
    list: (runId: string) => invoke<{ runId: string }, { items: Screenshot[] }>(IpcContracts.screenshotsList.channel, { runId })
  },
  folders: {
    openDownloads: () => invoke(IpcContracts.foldersOpenDownloads.channel, {}),
    chooseOutputDir: () =>
      invoke<Record<string, never>, { canceled: boolean; localPath: string | null }>(IpcContracts.foldersChooseOutputDir.channel, {})
  }
};

contextBridge.exposeInMainWorld("applyocalypse", api);

export type ApplyocalypsePreloadApi = typeof api;
