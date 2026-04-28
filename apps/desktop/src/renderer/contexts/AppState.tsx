import { createContext, createEffect, onCleanup, onMount, useContext, type ParentProps } from "solid-js";
import { createStore } from "solid-js/store";
import type {
  ApplicationAnswer,
  ApplicationRun,
  ApplicationStep,
  Approval,
  BrowserArtifact,
  CanonicalProfile,
  GeneratedFile,
  ParsedDocument,
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
import { parseJobIntake } from "../features/intake/parseJobIntake";

type AppState = {
  theme: ThemeState;
  settings: Record<string, unknown>;
  profile: Profile | null;
  canonicalProfile: CanonicalProfile | null;
  providerConnections: ProviderConnection[];
  uploadedFiles: UploadedFile[];
  parsedDocuments: ParsedDocument[];
  screenshots: Screenshot[];
  queueItems: QueueItem[];
  applicationRuns: ApplicationRun[];
  runDetail: {
    run: ApplicationRun;
    steps: ApplicationStep[];
    answers: ApplicationAnswer[];
    reviewRequests: ReviewRequest[];
    generatedFiles: GeneratedFile[];
    browserArtifacts: BrowserArtifact[];
    events: RunEvent[];
  } | null;
  activeRunId: string;
  events: SafeRendererRunEvent[];
  queueTotal: number;
  runsTotal: number;
  isLoading: boolean;
  error: string | null;
};

type AppStateContextValue = {
  state: AppState;
  setThemePreference: (preference: ThemePreference) => Promise<void>;
  setMaxConcurrentApplications: (value: number) => Promise<void>;
  chooseOutputDir: () => Promise<void>;
  createStarterProfile: (input: {
    legalName: string;
    email?: string | null;
    location?: string | null;
    applicationEmail: string;
    applicationPassword: string;
    gmailOtpEnabled?: boolean;
  }) => Promise<void>;
  configureApplicationCredentials: (input: {
    profileId: string;
    applicationEmail: string;
    applicationPassword: string;
    gmailOtpEnabled?: boolean;
  }) => Promise<void>;
  saveProfile: (profile: Profile) => Promise<void>;
  saveProviderApiKey: (input: {
    provider: ProviderConnection["provider"];
    displayName: string;
    apiKey: string;
    metadata?: Record<string, unknown>;
  }) => Promise<void>;
  pickAndRegisterResume: () => Promise<void>;
  pickAndRegisterSupportingDetails: () => Promise<void>;
  pickAndRegisterCoverLetter: () => Promise<void>;
  confirmEditableMaster: (uploadedFileId: string) => Promise<void>;
  repairEditableMasterAnchors: (uploadedFileId: string) => Promise<void>;
  openLocalPath: (localPath: string) => Promise<void>;
  enqueueJobText: (value: string, options?: { autoSubmitEnabled?: boolean }) => Promise<void>;
  refreshQueue: () => Promise<void>;
  refreshRuns: () => Promise<void>;
  loadRunDetail: (runId: string) => Promise<void>;
  updateAnswer: (answerId: string, userValue: string | null, status: "EDITED" | "REJECTED") => Promise<void>;
  pauseActiveRun: () => Promise<void>;
  resumeActiveRun: () => Promise<void>;
  cancelActiveRun: () => Promise<void>;
  retryCurrentStep: () => Promise<void>;
  skipCurrentStep: () => Promise<void>;
  resolveReviewRequest: (reviewRequestId: string, status: "APPROVED" | "REJECTED", reason?: string) => Promise<void>;
  approveFinalSubmit: (approvalType?: Approval["approvalType"]) => Promise<void>;
  rejectFinalSubmit: (reason: string, approvalType?: Approval["approvalType"]) => Promise<void>;
  pushEvent: (event: SafeRendererRunEvent) => void;
};

const initialTheme = window.applyocalypse.theme.getInitialState();

const AppStateContext = createContext<AppStateContextValue>();

const applyThemeToDocument = (theme: ThemeState): void => {
  document.documentElement.dataset.theme = theme.activeTheme;
  document.documentElement.classList.toggle("dark", theme.activeTheme === "dark");
};

const runControlAccepted = (result: unknown): result is { accepted: true; message?: string } =>
  typeof result === "object" && result !== null && (result as { accepted?: unknown }).accepted === true;

const runControlMessage = (result: unknown, fallback: string): string => {
  if (typeof result === "object" && result !== null && typeof (result as { message?: unknown }).message === "string") {
    return (result as { message: string }).message;
  }
  return fallback;
};

export const AppStateProvider = (props: ParentProps) => {
  let runEventUnsubscribe: (() => void) | null = null;

  const [state, setState] = createStore<AppState>({
    theme: initialTheme,
    settings: {},
    profile: null,
    canonicalProfile: null,
    providerConnections: [],
    uploadedFiles: [],
    parsedDocuments: [],
    screenshots: [],
    queueItems: [],
    applicationRuns: [],
    runDetail: null,
    activeRunId: "",
    events: [],
    queueTotal: 0,
    runsTotal: 0,
    isLoading: false,
    error: null
  });

  createEffect(() => {
    applyThemeToDocument(state.theme);
  });

  const unsubscribeTheme = window.applyocalypse.theme.subscribe((theme) => {
    setState("theme", theme);
  });

  onMount(() => {
    void (async () => {
      setState("isLoading", true);
      try {
        const [settings, profile, canonicalProfile, providers, uploads, parsedDocuments, queue, runs] = await Promise.all([
          window.applyocalypse.settings.get(),
          window.applyocalypse.profile.get(),
          window.applyocalypse.profile.getCanonical(),
          window.applyocalypse.providers.list(),
          window.applyocalypse.files.listUploads(null),
          window.applyocalypse.documents.listParsed({ profileId: null }),
          window.applyocalypse.jobs.list(50, 0),
          window.applyocalypse.runs.list(50, 0)
        ]);
        setState("settings", settings);
        setState("profile", profile);
        setState("canonicalProfile", canonicalProfile);
        setState("providerConnections", providers.items);
        setState("uploadedFiles", uploads.items);
        setState("parsedDocuments", parsedDocuments.items);
        setState("queueItems", queue.items);
        setState("queueTotal", queue.total);
        setState("applicationRuns", runs.items);
        setState("runsTotal", runs.total);
      } catch (error) {
        setState("error", error instanceof Error ? error.message : "Unable to load local state");
      } finally {
        setState("isLoading", false);
      }
    })();
  });

  onCleanup(() => {
    unsubscribeTheme();
    runEventUnsubscribe?.();
  });

  const setThemePreference = async (preference: ThemePreference): Promise<void> => {
    setState("isLoading", true);
    try {
      const theme = await window.applyocalypse.theme.setPreference(preference);
      setState("theme", theme);
      setState("error", null);
    } catch (error) {
      setState("error", error instanceof Error ? error.message : "Unable to update theme");
    } finally {
      setState("isLoading", false);
    }
  };

  const chooseOutputDir = async (): Promise<void> => {
    setState("isLoading", true);
    try {
      const selected = await window.applyocalypse.folders.chooseOutputDir();
      if (selected.canceled || !selected.localPath) {
        return;
      }
      const settings = await window.applyocalypse.settings.update({ "files.outputDir": selected.localPath });
      setState("settings", settings);
      setState("error", null);
    } catch (error) {
      setState("error", error instanceof Error ? error.message : "Unable to choose output folder");
    } finally {
      setState("isLoading", false);
    }
  };

  const setMaxConcurrentApplications = async (value: number): Promise<void> => {
    setState("isLoading", true);
    try {
      const settings = await window.applyocalypse.settings.update({ "automation.maxConcurrentApplications": value });
      setState("settings", settings);
      setState("error", null);
    } catch (error) {
      setState("error", error instanceof Error ? error.message : "Unable to update automation concurrency");
    } finally {
      setState("isLoading", false);
    }
  };

  const createStarterProfile = async (input: {
    legalName: string;
    email?: string | null;
    location?: string | null;
    applicationEmail: string;
    applicationPassword: string;
    gmailOtpEnabled?: boolean;
  }): Promise<void> => {
    setState("isLoading", true);
    try {
      const profile = await window.applyocalypse.profile.createStarter(input);
      setState("profile", profile);
      setState("canonicalProfile", await window.applyocalypse.profile.getCanonical(profile.id));
      setState("error", null);
    } catch (error) {
      setState("error", error instanceof Error ? error.message : "Unable to create profile");
    } finally {
      setState("isLoading", false);
    }
  };

  const configureApplicationCredentials = async (input: {
    profileId: string;
    applicationEmail: string;
    applicationPassword: string;
    gmailOtpEnabled?: boolean;
  }): Promise<void> => {
    setState("isLoading", true);
    try {
      const updated = await window.applyocalypse.profile.configureApplicationCredentials(input);
      setState("profile", updated);
      setState("canonicalProfile", await window.applyocalypse.profile.getCanonical(updated.id));
      setState("providerConnections", (await window.applyocalypse.providers.list()).items);
      setState("error", null);
    } catch (error) {
      setState("error", error instanceof Error ? error.message : "Unable to save application credentials");
    } finally {
      setState("isLoading", false);
    }
  };

  const saveProfile = async (profile: Profile): Promise<void> => {
    setState("isLoading", true);
    try {
      const updated = await window.applyocalypse.profile.update(profile);
      setState("profile", updated);
      setState("canonicalProfile", await window.applyocalypse.profile.getCanonical(updated.id));
      setState("error", null);
    } catch (error) {
      setState("error", error instanceof Error ? error.message : "Unable to save profile");
    } finally {
      setState("isLoading", false);
    }
  };

  const saveProviderApiKey = async (input: {
    provider: ProviderConnection["provider"];
    displayName: string;
    apiKey: string;
    metadata?: Record<string, unknown>;
  }): Promise<void> => {
    if (!input.apiKey.trim()) {
      setState("error", "Provider API key is required.");
      return;
    }
    setState("isLoading", true);
    try {
      const connection = await window.applyocalypse.providers.saveApiKey({
        provider: input.provider,
        displayName: input.displayName,
        apiKey: input.apiKey,
        metadata: { ...(input.metadata ?? {}), configuredAt: new Date().toISOString() }
      });
      setState("providerConnections", (connections) => {
        const next = connections.filter((item) => item.provider !== connection.provider);
        return [connection, ...next].sort((a, b) => a.provider.localeCompare(b.provider));
      });
      setState("error", null);
    } catch (error) {
      setState("error", error instanceof Error ? error.message : "Unable to save provider key");
    } finally {
      setState("isLoading", false);
    }
  };

  const pickAndRegisterResume = async (): Promise<void> => {
    setState("isLoading", true);
    try {
      const picked = await window.applyocalypse.files.pick("resume");
      if (picked.canceled) {
        return;
      }
      const localPath = picked.paths[0];
      if (!localPath) {
        throw new Error("No resume path returned from file picker");
      }
      const registered = await window.applyocalypse.documents.ingestResumeSource({
        profileId: state.profile?.id ?? null,
        localPath
      });
      setState("uploadedFiles", (files) =>
        [registered.sourceFile, registered.editableMasterCandidate, ...files].filter((file): file is UploadedFile => Boolean(file))
      );
      if (registered.parsing) {
        setState("parsedDocuments", (documents) => [registered.parsing!.parsedDocument, ...documents]);
        if (registered.parsing.updatedProfile) {
          setState("profile", registered.parsing.updatedProfile);
        }
      }
      setState("canonicalProfile", await window.applyocalypse.profile.getCanonical(state.profile?.id));
      setState("error", null);
    } catch (error) {
      setState("error", error instanceof Error ? error.message : "Unable to register resume");
    } finally {
      setState("isLoading", false);
    }
  };

  const pickAndRegisterUpload = async (
    purpose: "cover_letter" | "supporting_details" | "other",
    fileKind: "COVER_LETTER" | "SUPPORTING_DETAILS" | "OTHER"
  ): Promise<void> => {
    setState("isLoading", true);
    try {
      const picked = await window.applyocalypse.files.pick(purpose);
      if (picked.canceled) {
        return;
      }
      const localPath = picked.paths[0];
      if (!localPath) {
        throw new Error("No source path returned from file picker");
      }
      const registered = await window.applyocalypse.files.registerUpload({
        profileId: state.profile?.id ?? null,
        localPath,
        fileKind
      });
      setState("uploadedFiles", (files) => [registered.uploadedFile, ...files]);
      if (registered.parsing) {
        setState("parsedDocuments", (documents) => [registered.parsing!.parsedDocument, ...documents]);
        if (registered.parsing.updatedProfile) {
          setState("profile", registered.parsing.updatedProfile);
        }
      }
      setState("canonicalProfile", await window.applyocalypse.profile.getCanonical(state.profile?.id));
      setState("error", null);
    } catch (error) {
      setState("error", error instanceof Error ? error.message : "Unable to register source material");
    } finally {
      setState("isLoading", false);
    }
  };

  const pickAndRegisterSupportingDetails = async (): Promise<void> => pickAndRegisterUpload("supporting_details", "SUPPORTING_DETAILS");

  const pickAndRegisterCoverLetter = async (): Promise<void> => pickAndRegisterUpload("cover_letter", "COVER_LETTER");

  const confirmEditableMaster = async (uploadedFileId: string): Promise<void> => {
    setState("isLoading", true);
    try {
      const uploadedFile = await window.applyocalypse.documents.confirmEditableMaster(uploadedFileId);
      const [parsedDocuments, profile] = await Promise.all([
        window.applyocalypse.documents.listParsed({ uploadedFileId }),
        window.applyocalypse.profile.get()
      ]);
      setState("uploadedFiles", (files) => files.map((file) => (file.id === uploadedFile.id ? uploadedFile : file)));
      setState("parsedDocuments", (documents) => {
        const remaining = documents.filter((document) => document.uploadedFileId !== uploadedFileId);
        return [...parsedDocuments.items, ...remaining];
      });
      setState("profile", profile);
      setState("canonicalProfile", await window.applyocalypse.profile.getCanonical(profile?.id));
      setState("error", null);
    } catch (error) {
      setState("error", error instanceof Error ? error.message : "Unable to confirm editable master");
    } finally {
      setState("isLoading", false);
    }
  };

  const repairEditableMasterAnchors = async (uploadedFileId: string): Promise<void> => {
    setState("isLoading", true);
    try {
      const repaired = await window.applyocalypse.documents.repairEditableMasterAnchors(uploadedFileId);
      setState("uploadedFiles", (files) => [repaired.anchoredCandidate, ...files]);
      if (repaired.parsing) {
        setState("parsedDocuments", (documents) => [repaired.parsing!.parsedDocument, ...documents]);
      }
      setState("canonicalProfile", await window.applyocalypse.profile.getCanonical(state.profile?.id));
      setState("error", null);
    } catch (error) {
      setState("error", error instanceof Error ? error.message : "Unable to create anchor repair candidate");
    } finally {
      setState("isLoading", false);
    }
  };

  const openLocalPath = async (localPath: string): Promise<void> => {
    try {
      const result = await window.applyocalypse.files.openLocalPath(localPath);
      if (!result.opened) {
        throw new Error("Operating system did not open the path");
      }
      setState("error", null);
    } catch (error) {
      setState("error", error instanceof Error ? error.message : "Unable to open local path");
    }
  };

  const refreshQueue = async (): Promise<void> => {
    const queue = await window.applyocalypse.jobs.list(50, 0);
    setState("queueItems", queue.items);
    setState("queueTotal", queue.total);
  };

  const refreshRuns = async (): Promise<void> => {
    const runs = await window.applyocalypse.runs.list(50, 0);
    setState("applicationRuns", runs.items);
    setState("runsTotal", runs.total);
  };

  const enqueueJobText = async (value: string, options: { autoSubmitEnabled?: boolean } = {}): Promise<void> => {
    const profileId = state.profile?.id;
    if (!profileId) {
      setState("error", "Create a profile before adding job targets.");
      return;
    }

    const items = parseJobIntake(value).map((item) => ({
      ...item,
      autoSubmitEnabled: options.autoSubmitEnabled === true
    }));

    if (items.length === 0) {
      setState("error", "Paste at least one job link or description.");
      return;
    }

    setState("isLoading", true);
    try {
      await window.applyocalypse.jobs.enqueue(profileId, items);
      await Promise.all([refreshQueue(), refreshRuns()]);
      setState("error", null);
    } catch (error) {
      setState("error", error instanceof Error ? error.message : "Unable to enqueue jobs");
    } finally {
      setState("isLoading", false);
    }
  };

  const loadRunDetail = async (runId: string): Promise<void> => {
    setState("isLoading", true);
    try {
      const runDetail = await window.applyocalypse.runs.getDetail(runId);
      const screenshots = await window.applyocalypse.screenshots.list(runId);
      setState("activeRunId", runId);
      setState("runDetail", runDetail);
      setState("screenshots", screenshots.items);
      runEventUnsubscribe?.();
      runEventUnsubscribe = window.applyocalypse.logs.subscribe(runId, (event) => {
        pushEvent(event);
        void refreshActiveRunDetail(runId);
      });
      setState("error", null);
    } catch (error) {
      setState("error", error instanceof Error ? error.message : "Unable to load run detail");
    } finally {
      setState("isLoading", false);
    }
  };

  const refreshActiveRunDetail = async (runId = state.activeRunId): Promise<void> => {
    if (!runId) {
      return;
    }
    try {
      const [runDetail, screenshots] = await Promise.all([
        window.applyocalypse.runs.getDetail(runId),
        window.applyocalypse.screenshots.list(runId),
        refreshQueue(),
        refreshRuns()
      ]);
      setState("runDetail", runDetail);
      setState("screenshots", screenshots.items);
      setState("error", null);
    } catch (error) {
      setState("error", error instanceof Error ? error.message : "Unable to refresh run detail");
    }
  };

  const updateAnswer = async (answerId: string, userValue: string | null, status: "EDITED" | "REJECTED"): Promise<void> => {
    const runId = state.runDetail?.run.id;
    if (!runId) {
      setState("error", "No active run detail loaded.");
      return;
    }
    try {
      const answer = await window.applyocalypse.runs.updateAnswer(runId, answerId, userValue, status);
      setState("runDetail", "answers", (answers) => answers.map((item) => (item.id === answer.id ? answer : item)));
      setState("error", null);
    } catch (error) {
      setState("error", error instanceof Error ? error.message : "Unable to update answer");
    }
  };

  const pushEvent = (event: SafeRendererRunEvent): void => {
    setState("events", (events) => [event, ...events].slice(0, 200));
  };

  const getActiveRunId = (): string | null => (state.runDetail?.run.id ?? state.activeRunId) || null;

  const pauseActiveRun = async (): Promise<void> => {
    const runId = getActiveRunId();
    if (!runId) {
      setState("error", "Select a run before pausing.");
      return;
    }
    try {
      const result = await window.applyocalypse.runs.pause(runId);
      if (!runControlAccepted(result)) {
        setState("error", runControlMessage(result, "Unable to pause this run."));
      } else {
        setState("error", null);
      }
      await refreshActiveRunDetail(runId);
    } catch (error) {
      setState("error", error instanceof Error ? error.message : "Unable to pause this run.");
    }
  };

  const resumeActiveRun = async (): Promise<void> => {
    const runId = getActiveRunId();
    if (!runId) {
      setState("error", "Select a run before resuming.");
      return;
    }
    try {
      const result = await window.applyocalypse.runs.resume(runId);
      if (!runControlAccepted(result)) {
        setState("error", runControlMessage(result, "Unable to resume this run."));
        await refreshActiveRunDetail(runId);
        return;
      }
      await refreshActiveRunDetail(runId);
      setState("error", null);
    } catch (error) {
      setState("error", error instanceof Error ? error.message : "Unable to resume this run.");
    }
  };

  const cancelActiveRun = async (): Promise<void> => {
    const runId = getActiveRunId();
    if (!runId) {
      setState("error", "Select a run before cancelling.");
      return;
    }
    try {
      const result = await window.applyocalypse.runs.cancel(runId);
      if (!runControlAccepted(result)) {
        setState("error", runControlMessage(result, "Unable to cancel this run."));
      } else {
        setState("error", null);
      }
      await refreshActiveRunDetail(runId);
    } catch (error) {
      setState("error", error instanceof Error ? error.message : "Unable to cancel this run.");
    }
  };

  const retryCurrentStep = async (): Promise<void> => {
    const runId = getActiveRunId();
    const stepId = state.runDetail?.run.currentStepId ?? state.runDetail?.steps.find((step) => step.status === "FAILED")?.id;
    if (!runId || !stepId) {
      setState("error", "Select a run with a retryable step.");
      return;
    }
    try {
      const result = await window.applyocalypse.runs.retryStep(runId, stepId);
      if (!runControlAccepted(result)) {
        setState("error", runControlMessage(result, "Unable to retry this step."));
        await refreshActiveRunDetail(runId);
        return;
      }
      await refreshActiveRunDetail(runId);
      setState("error", null);
    } catch (error) {
      setState("error", error instanceof Error ? error.message : "Unable to retry this step.");
    }
  };

  const skipCurrentStep = async (): Promise<void> => {
    const runId = getActiveRunId();
    const stepId =
      state.runDetail?.run.currentStepId ??
      state.runDetail?.steps.find((step) => ["PENDING", "WAITING_FOR_USER", "PAUSED", "FAILED"].includes(step.status))?.id;
    if (!runId || !stepId) {
      setState("error", "Select a run with a safe step to skip.");
      return;
    }
    try {
      const result = await window.applyocalypse.runs.skipStep(runId, stepId);
      if (!runControlAccepted(result)) {
        setState("error", runControlMessage(result, "Unable to skip this step."));
        await refreshActiveRunDetail(runId);
        return;
      }
      await refreshActiveRunDetail(runId);
      setState("error", null);
    } catch (error) {
      setState("error", error instanceof Error ? error.message : "Unable to skip this step.");
    }
  };

  const resolveReviewRequest = async (reviewRequestId: string, status: "APPROVED" | "REJECTED", reason?: string): Promise<void> => {
    const runId = getActiveRunId();
    if (!runId) {
      setState("error", "Select a run before resolving review.");
      return;
    }
    try {
      const result = await window.applyocalypse.runs.resolveReview(runId, reviewRequestId, status, reason);
      if (!runControlAccepted(result)) {
        setState("error", runControlMessage(result, "Unable to resolve review"));
        await refreshActiveRunDetail(runId);
        return;
      }
      await refreshActiveRunDetail(runId);
      setState("error", null);
    } catch (error) {
      setState("error", error instanceof Error ? error.message : "Unable to resolve review");
    }
  };

  const approveFinalSubmit = async (requestedApprovalType?: Approval["approvalType"]): Promise<void> => {
    const runId = getActiveRunId();
    if (!runId) {
      setState("error", "Select a run before approving final submit.");
      return;
    }
    const openReview = state.runDetail?.reviewRequests.find((request) => request.status === "OPEN");
    const approvalType: Approval["approvalType"] =
      requestedApprovalType ??
      (openReview?.reviewType === "DOCUMENT"
        ? "DOCUMENT_APPROVAL"
        : openReview?.reviewType === "OTP"
          ? "OTP_READ"
          : openReview?.reviewType === "FINAL_SUBMIT"
            ? "FINAL_SUBMIT"
            : "ANSWER_EDIT");
    try {
      const result = await window.applyocalypse.runs.approve(runId, approvalType);
      if (!runControlAccepted(result)) {
        setState("error", runControlMessage(result, "Unable to approve this run."));
        await refreshActiveRunDetail(runId);
        return;
      }
      await refreshActiveRunDetail(runId);
      setState("error", null);
    } catch (error) {
      setState("error", error instanceof Error ? error.message : "Unable to approve this run.");
    }
  };

  const rejectFinalSubmit = async (reason: string, approvalType: Approval["approvalType"] = "FINAL_SUBMIT"): Promise<void> => {
    const runId = getActiveRunId();
    if (!runId) {
      setState("error", "Select a run before rejecting final submit.");
      return;
    }
    try {
      const result = await window.applyocalypse.runs.reject(runId, reason, approvalType);
      if (!runControlAccepted(result)) {
        setState("error", runControlMessage(result, "Unable to reject this run."));
      } else {
        setState("error", null);
      }
      await refreshActiveRunDetail(runId);
    } catch (error) {
      setState("error", error instanceof Error ? error.message : "Unable to reject this run.");
    }
  };

  return (
    <AppStateContext.Provider
      value={{
        state,
        setThemePreference,
        setMaxConcurrentApplications,
        chooseOutputDir,
        createStarterProfile,
        configureApplicationCredentials,
        saveProfile,
        saveProviderApiKey,
        pickAndRegisterResume,
        pickAndRegisterSupportingDetails,
        pickAndRegisterCoverLetter,
        confirmEditableMaster,
        repairEditableMasterAnchors,
        openLocalPath,
        enqueueJobText,
        refreshQueue,
        refreshRuns,
        loadRunDetail,
        updateAnswer,
        pauseActiveRun,
        resumeActiveRun,
        cancelActiveRun,
        retryCurrentStep,
        skipCurrentStep,
        resolveReviewRequest,
        approveFinalSubmit,
        rejectFinalSubmit,
        pushEvent
      }}
    >
      {props.children}
    </AppStateContext.Provider>
  );
};

export const useAppState = (): AppStateContextValue => {
  const context = useContext(AppStateContext);
  if (!context) {
    throw new Error("AppStateProvider is missing");
  }
  return context;
};
