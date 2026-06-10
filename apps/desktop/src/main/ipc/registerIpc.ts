import { BrowserWindow, app, dialog, ipcMain, shell } from "electron";
import { statSync } from "node:fs";
import { isAbsolute, normalize, resolve } from "node:path";
import {
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
import { IpcChannels, IpcContracts, type IpcContract } from "@applyocalypse/ipc-contracts";
import { RunEventSchema, ScreenshotSchema } from "@applyocalypse/shared-schemas";
import { HARD_MAX_CONCURRENT_APPLICATIONS } from "@applyocalypse/config";
import type { ThemeController } from "../theme";
import type { z } from "zod";
import { DocumentIngestionService } from "../services/documentIngestionService";
import type { PythonWorkerSupervisor } from "../services/pythonWorkerSupervisor";
import { SecureSecretStore } from "../services/secureSecretStore";
import { buildControlDocumentFiles } from "../services/runApprovalPayload";
import { writeWorkerControlFile } from "../services/workerControlFile";

type RegisterIpcHandlersInput = {
  db: ApplyocalypseDatabase;
  settingsRepository: SettingsRepository;
  queueRepository: QueueRepository;
  themeController: ThemeController;
  workerSupervisor: PythonWorkerSupervisor;
  getMainWindow: () => BrowserWindow | null;
  initialApprovedPaths?: string[];
};

const handleContract = <Request extends z.ZodTypeAny, Response extends z.ZodTypeAny>(
  ipcContract: IpcContract<Request, Response>,
  handler: (request: z.infer<Request>) => Promise<z.infer<Response>> | z.infer<Response>
): void => {
  ipcMain.handle(ipcContract.channel, async (_event, rawRequest) => {
    const request = ipcContract.request.parse(rawRequest ?? {});
    const response = await handler(request);
    return ipcContract.response.parse(response);
  });
};

const parseJson = <T>(value: string, fallback: T): T => {
  try {
    return JSON.parse(value) as T;
  } catch {
    return fallback;
  }
};

export const registerIpcHandlers = ({
  db,
  settingsRepository,
  queueRepository,
  themeController,
  workerSupervisor,
  getMainWindow,
  initialApprovedPaths = []
}: RegisterIpcHandlersInput): void => {
  const profileRepository = new ProfileRepository(db);
  const jobRepository = new JobRepository(db);
  const uploadRepository = new UploadRepository(db);
  const parsedDocumentRepository = new ParsedDocumentRepository(db);
  const providerRepository = new ProviderRepository(db);
  const runRepository = new RunRepository(db);
  const auditRepository = new AuditRepository(db);
  const secureSecretStore = new SecureSecretStore();
  const documentIngestionService = new DocumentIngestionService(uploadRepository, parsedDocumentRepository);
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
  const configureApplicationCredentials = (input: {
    profileId: string;
    applicationEmail: string;
    applicationPassword: string;
    gmailOtpEnabled: boolean;
  }) => {
    const applicationEmail = input.applicationEmail.trim().toLowerCase();
    if (!profileRepository.getById(input.profileId)) {
      throw new Error("Profile was not found for application credential setup");
    }
    const encryptedReference = secureSecretStore.encryptSecret(input.applicationPassword);
    const secretRefId = providerRepository.createEncryptedSecretReference({
      provider: input.gmailOtpEnabled ? "gmail" : "local",
      keyName: input.gmailOtpEnabled ? "gmail_otp_password" : "application_password",
      encryptedReference,
      redactedHint: secureSecretStore.redactedHint(input.applicationPassword)
    });
    const gmailConnection = input.gmailOtpEnabled
      ? providerRepository.upsertConnection({
          provider: "gmail",
          displayName: `Gmail OTP (${applicationEmail})`,
          status: "CONNECTED",
          secretRefId,
          metadata: {
            email: applicationEmail,
            purpose: "otp",
            authMode: "password_or_app_password",
            scope: "gmail_imap_otp_search",
            configuredAt: new Date().toISOString()
          }
        })
      : null;
    if (!input.gmailOtpEnabled) {
      providerRepository.disconnectProvider("gmail", {
        email: applicationEmail,
        purpose: "otp",
        disabledAt: new Date().toISOString()
      });
    }
    const profile = profileRepository.configureApplicationCredentials({
      profileId: input.profileId,
      applicationEmail,
      passwordSecretRefId: secretRefId,
      otpProviderConnectionId: gmailConnection?.id ?? null,
      otpHandlingEnabled: input.gmailOtpEnabled
    });
    auditRepository.append({
      action: "profile.application_credentials_saved",
      entityType: "profile",
      entityId: profile.id,
      metadata: {
        applicationEmail,
        gmailOtpEnabled: input.gmailOtpEnabled,
        passwordSecretRefId: secretRefId,
        gmailProviderConnectionId: gmailConnection?.id ?? null
      }
    });
    return profile;
  };

  ipcMain.on(IpcChannels.themeGetInitialState, (event) => {
    event.returnValue = themeController.getState();
  });

  handleContract(IpcContracts.appGetVersion, () => ({ version: process.env.npm_package_version ?? "0.1.0" }));
  handleContract(IpcContracts.themeSetPreference, ({ preference }) => themeController.setPreference(preference));
  handleContract(IpcContracts.settingsGet, () => settingsRepository.getAll());
  handleContract(IpcContracts.settingsUpdate, ({ patch }) => {
    for (const [key, value] of Object.entries(patch)) {
      if (key === "automation.maxConcurrentApplications") {
        if (typeof value !== "number" || !Number.isInteger(value)) {
          throw new Error("Maximum concurrent applications must be an integer");
        }
        const clamped = Math.max(1, Math.min(HARD_MAX_CONCURRENT_APPLICATIONS, value));
        settingsRepository.set(key, clamped);
        continue;
      }
      if (key !== "files.outputDir") {
        throw new Error(`Unsupported setting key: ${key}`);
      }
      if (typeof value !== "string") {
        throw new Error("Output directory must be a string path");
      }
      const outputDir = normalizeUserPath(value);
      if (!statSync(outputDir).isDirectory()) {
        throw new Error("Output directory must exist and be a directory");
      }
      settingsRepository.set(key, outputDir);
    }
    return settingsRepository.getAll();
  });
  handleContract(IpcContracts.providersList, () => ({ items: providerRepository.list() }));
  handleContract(IpcContracts.providersSaveApiKey, ({ provider, displayName, apiKey, metadata }) => {
    const encryptedReference = secureSecretStore.encryptSecret(apiKey);
    const secretRefId = providerRepository.createEncryptedSecretReference({
      provider,
      keyName: "api_key",
      encryptedReference,
      redactedHint: secureSecretStore.redactedHint(apiKey)
    });
    const connection = providerRepository.upsertConnection({
      provider,
      displayName,
      status: "CONNECTED",
      secretRefId,
      metadata: metadata ?? {}
    });
    auditRepository.append({
      action: "provider.api_key_saved",
      entityType: "provider_connection",
      entityId: connection.id,
      metadata: { provider, secretRefId }
    });
    return connection;
  });
  handleContract(IpcContracts.documentsIngestResumeSource, ({ profileId, localPath }) =>
    documentIngestionService.ingestResumeSource({ profileId, localPath: requirePickedPath(localPath) })
  );
  handleContract(IpcContracts.documentsConfirmEditableMaster, async ({ uploadedFileId }) => {
    const uploadedFile = uploadRepository.getById(uploadedFileId);
    if (uploadedFile.fileKind !== "RESUME" || uploadedFile.sourceFormat !== "DOCX") {
      throw new Error("Only DOCX resume candidates can be confirmed as editable masters");
    }
    const confirmed = uploadRepository.updateStatus(uploadedFileId, "VERIFIED_EDITABLE_MASTER");
    for (const parsedDocument of parsedDocumentRepository.list({ uploadedFileId: confirmed.id })) {
      parsedDocumentRepository.mergeIntoProfile(parsedDocument);
    }
    auditRepository.append({
      action: "document.editable_master_confirmed",
      entityType: "uploaded_file",
      entityId: confirmed.id,
      metadata: { sourceFormat: confirmed.sourceFormat }
    });
    try {
      await documentIngestionService.repairEditableMasterAnchors({ uploadedFileId: confirmed.id });
    } catch {
      // Non-fatal: repair may fail if the file is already anchored or cannot be processed
    }
    return confirmed;
  });
  handleContract(IpcContracts.documentsRepairEditableMasterAnchors, async ({ uploadedFileId }) => {
    const result = await documentIngestionService.repairEditableMasterAnchors({ uploadedFileId });
    auditRepository.append({
      action: "document.editable_master_anchor_repair_created",
      entityType: "uploaded_file",
      entityId: result.anchoredCandidate.id,
      metadata: {
        sourceUploadedFileId: uploadedFileId,
        addedPlaceholders: result.addedPlaceholders,
        warningCount: result.warnings.length
      }
    });
    return result;
  });
  handleContract(IpcContracts.documentsListParsed, ({ uploadedFileId, profileId }) => ({
    items: parsedDocumentRepository.list({
      ...(uploadedFileId ? { uploadedFileId } : {}),
      ...(profileId !== undefined ? { profileId } : {})
    })
  }));

  handleContract(IpcContracts.profileGet, () => profileRepository.getDefaultProfile());
  handleContract(IpcContracts.profileGetCanonical, ({ profileId }) => {
    const resolvedProfileId = profileId ?? profileRepository.getDefaultProfile()?.id ?? null;
    return resolvedProfileId ? profileRepository.getCanonicalProfile(resolvedProfileId) : null;
  });
  handleContract(IpcContracts.profileCreateStarter, (input) => {
    let profile = profileRepository.createStarterProfile({
      legalName: input.legalName,
      email: input.email ?? null,
      location: input.location ?? null
    });
    if (input.workAuthorization) {
      profile = profileRepository.upsert({ ...profile, workAuthorization: input.workAuthorization });
    }
    return configureApplicationCredentials({
      profileId: profile.id,
      applicationEmail: input.applicationEmail,
      applicationPassword: input.applicationPassword,
      gmailOtpEnabled: input.gmailOtpEnabled
    });
  });
  handleContract(IpcContracts.profileConfigureApplicationCredentials, (input) =>
    configureApplicationCredentials({
      profileId: input.profileId,
      applicationEmail: input.applicationEmail,
      applicationPassword: input.applicationPassword,
      gmailOtpEnabled: input.gmailOtpEnabled
    })
  );
  handleContract(IpcContracts.profileUpdate, ({ profile }) => profileRepository.upsert(profile));
  handleContract(IpcContracts.profileUpdateStructured, ({ profileId, education, experience, projects, skillGroups }) => {
    const result = profileRepository.replaceStructuredSections(profileId, { education, experience, projects, skillGroups });
    auditRepository.append({
      action: "profile.structured_sections_replaced",
      entityType: "profile",
      entityId: profileId,
      metadata: { educationCount: education.length, experienceCount: experience.length, projectCount: projects.length, skillGroupCount: skillGroups.length }
    });
    return result;
  });

  handleContract(IpcContracts.filesPick, async ({ purpose }) => {
    const filters =
      purpose === "resume"
        ? [{ name: "Resume Sources", extensions: ["pdf", "docx", "tex"] }]
        : [{ name: "Documents", extensions: ["pdf", "docx", "tex", "txt", "md"] }];

    const dialogOptions = {
      properties: ["openFile"] as Array<"openFile">,
      filters
    };
    const owner = getMainWindow();
    const result = owner ? await dialog.showOpenDialog(owner, dialogOptions) : await dialog.showOpenDialog(dialogOptions);

    if (result.canceled) {
      return { canceled: true, paths: [] };
    }
    const paths = result.filePaths.map(normalizeUserPath);
    for (const path of paths) {
      approvedPickedPaths.add(path);
    }
    return { canceled: false, paths };
  });

  handleContract(IpcContracts.filesOpenLocalPath, async ({ localPath }) => {
    const normalized = requireOpenablePath(localPath);
    const error = await shell.openPath(normalized);
    return { opened: error.length === 0 };
  });

  handleContract(IpcContracts.filesListUploads, ({ profileId }) => ({
    items: uploadRepository.list(profileId ?? null)
  }));

  handleContract(IpcContracts.filesRegisterUpload, ({ profileId, localPath, fileKind }) => {
    if (fileKind === "RESUME") {
      throw new Error("Resume uploads must use the editable-master ingestion flow");
    }
    return documentIngestionService.ingestSourceMaterial({
      profileId,
      localPath: requirePickedPath(localPath),
      fileKind
    });
  });

  handleContract(IpcContracts.jobsEnqueue, ({ profileId, items }) => jobRepository.enqueueTargets({ profileId, items }));

  handleContract(IpcContracts.jobsList, ({ limit, offset }) => ({
    items: queueRepository.list(limit, offset),
    total: queueRepository.count()
  }));

  handleContract(IpcContracts.jobsGet, ({ runId }) => {
    const row = db.prepare("SELECT * FROM run_events WHERE application_run_id = ? ORDER BY created_at DESC LIMIT 1").get(runId) as
      | {
          id: string;
          event_type: string;
          application_run_id: string;
          step_id: string | null;
          severity: string;
          message: string;
          machine_state_json: string;
          ui_state_json: string;
          payload_json: string;
          created_at: string;
        }
      | undefined;

    return {
      run: row
        ? RunEventSchema.parse({
            id: row.id,
            eventType: row.event_type,
            runId: row.application_run_id,
            stepId: row.step_id,
            timestamp: row.created_at,
            severity: row.severity,
            message: row.message,
            machineState: parseJson(row.machine_state_json, {}),
            uiState: parseJson(row.ui_state_json, {}),
            payload: parseJson(row.payload_json, {})
          })
        : null
    };
  });

  const updateRunAndQueueStatus = (runId: string, status: "PAUSED" | "RUNNING_AUTOMATION" | "CANCELLED") => {
    const now = new Date().toISOString();
    runRepository.updateRunStatus({ runId, status });
    db.prepare(
      `
      UPDATE queue_items
      SET status = @status,
          updated_at = @now
      WHERE id = (SELECT queue_item_id FROM application_runs WHERE id = @runId)
    `
    ).run({ runId, status, now });
    auditRepository.append({
      action: `run.status.${status.toLowerCase()}`,
      entityType: "application_run",
      entityId: runId
    });
    return { accepted: true };
  };
  const rejectIfWorkerInactive = (runId: string, action: string): { accepted: false; message: string } | null => {
    if (workerSupervisor.isActive(runId)) {
      return null;
    }
    const message = "Automation worker is not active for this run. Review diagnostics, then retry from a safe step or cancel the run.";
    const timestamp = new Date().toISOString();
    runRepository.addRunEvent({
      eventType: "USER_REVIEW_REQUIRED",
      runId,
      stepId: null,
      timestamp,
      severity: "WARN",
      message,
      machineState: { reason: "WORKER_NOT_ACTIVE", attemptedAction: action },
      uiState: { requires_user_review: true, current_step: "worker_recovery" },
      payload: { action }
    });
    auditRepository.append({
      action: "run.control.rejected_worker_inactive",
      entityType: "application_run",
      entityId: runId,
      metadata: { attemptedAction: action }
    });
    return { accepted: false, message };
  };

  handleContract(IpcContracts.runsPause, ({ runId }) => {
    writeWorkerControlFile({ runId, command: "PAUSE", reason: "local_user_pause" });
    return updateRunAndQueueStatus(runId, "PAUSED");
  });
  handleContract(IpcContracts.runsResume, ({ runId }) => {
    const inactive = rejectIfWorkerInactive(runId, "RESUME");
    if (inactive) {
      return inactive;
    }
    writeWorkerControlFile({ runId, command: "RESUME", reason: "local_user_resume" });
    return updateRunAndQueueStatus(runId, "RUNNING_AUTOMATION");
  });
  handleContract(IpcContracts.runsCancel, ({ runId }) => {
    writeWorkerControlFile({ runId, command: "CANCEL", reason: "local_user_cancel" });
    workerSupervisor.stop(runId);
    return updateRunAndQueueStatus(runId, "CANCELLED");
  });
  handleContract(IpcContracts.runsList, ({ limit, offset }) => ({
    items: runRepository.listApplicationRuns(limit, offset),
    total: runRepository.countApplicationRuns()
  }));
  handleContract(IpcContracts.runsGetDetail, ({ runId }) => ({
    run: runRepository.getApplicationRun(runId),
    steps: runRepository.listSteps(runId),
    answers: runRepository.listAnswers(runId),
    reviewRequests: runRepository.listReviewRequests(runId),
    generatedFiles: runRepository.listGeneratedFiles(runId),
    browserArtifacts: runRepository.listBrowserArtifacts(runId),
    events: runRepository.listRunEvents(runId)
  }));
  handleContract(IpcContracts.runsListAnswers, ({ runId }) => ({ items: runRepository.listAnswers(runId) }));
  handleContract(IpcContracts.runsUpdateAnswer, ({ runId, answerId, userValue, status }) =>
    runRepository.updateAnswerValue({ applicationRunId: runId, answerId, userValue, status })
  );
  handleContract(IpcContracts.runsListReviewRequests, ({ runId }) => ({ items: runRepository.listReviewRequests(runId) }));
  handleContract(IpcContracts.runsResolveReview, ({ runId, reviewRequestId, status, reason }) => {
    const reviewRequest = runRepository.listReviewRequests(runId).find((request) => request.id === reviewRequestId);
    if (!reviewRequest) {
      throw new Error("Review request was not found for this run");
    }
    if (!["CAPTCHA", "MFA", "OTP", "AMBIGUOUS_QUESTION", "LOGIN", "PORTAL_ENTRY", "PORTAL_STEP"].includes(reviewRequest.reviewType)) {
      throw new Error("This review type requires the explicit approval workflow");
    }
    if (reviewRequest.status !== "OPEN") {
      return { accepted: true };
    }

    if (status === "APPROVED") {
      const inactive = rejectIfWorkerInactive(runId, `RESOLVE_${reviewRequest.reviewType}`);
      if (inactive) {
        return inactive;
      }
    }

    runRepository.decideReview({
      reviewRequestId,
      status,
      notes: reason ?? null
    });
    auditRepository.append({
      action: status === "APPROVED" ? "review.manual_blocker_resolved" : "review.manual_blocker_rejected",
      entityType: "review_request",
      entityId: reviewRequestId,
      metadata: {
        runId,
        reviewType: reviewRequest.reviewType,
        reasonLength: reason?.length ?? 0
      }
    });

    if (status === "APPROVED") {
      writeWorkerControlFile({ runId, command: "RESUME", reason: `local_user_resolved_${reviewRequest.reviewType.toLowerCase()}` });
      return updateRunAndQueueStatus(runId, "RUNNING_AUTOMATION");
    }

    writeWorkerControlFile({ runId, command: "CANCEL", reason: reason ?? `local_user_rejected_${reviewRequest.reviewType.toLowerCase()}` });
    workerSupervisor.stop(runId);
    return updateRunAndQueueStatus(runId, "CANCELLED");
  });
  handleContract(IpcContracts.runsRetryStep, ({ runId, stepId }) => {
    const inactive = rejectIfWorkerInactive(runId, "RETRY_STEP");
    if (inactive) {
      return inactive;
    }
    writeWorkerControlFile({ runId, command: "RETRY_STEP", reason: "local_user_retry", stepId });
    runRepository.updateStepStatus({ applicationRunId: runId, stepId, status: "RETRYING" });
    return { accepted: true };
  });
  handleContract(IpcContracts.runsSkipStep, ({ runId, stepId }) => {
    const inactive = rejectIfWorkerInactive(runId, "SKIP_STEP");
    if (inactive) {
      return inactive;
    }
    writeWorkerControlFile({ runId, command: "SKIP_STEP", reason: "local_user_skip", stepId });
    runRepository.updateStepStatus({ applicationRunId: runId, stepId, status: "SKIPPED" });
    auditRepository.append({
      action: "run.step.skipped",
      entityType: "application_step",
      entityId: stepId,
      metadata: { runId }
    });
    return { accepted: true };
  });
  handleContract(IpcContracts.runsApprove, ({ runId, approvalType }) => {
    const inactive = rejectIfWorkerInactive(runId, approvalType);
    if (inactive) {
      return inactive;
    }
    if (approvalType === "ANSWER_EDIT") {
      runRepository.approvePendingAnswers(runId);
    }
    const applicationRun = runRepository.getApplicationRun(runId);
    const approvedAnswers = runRepository
      .listAnswers(runId)
      .filter((answer) => answer.status === "APPROVED")
      .map((answer) => ({
        answerId: answer.id,
        fieldLabel: answer.fieldLabel,
        fieldType: answer.fieldType,
        value: answer.userValue ?? answer.proposedValue,
        source: answer.source,
        confidence: answer.confidence,
        status: answer.status
      }))
      .filter((answer) => typeof answer.value === "string" && answer.value.length > 0);
    const generatedFiles = buildControlDocumentFiles({
      generatedFiles: runRepository.listGeneratedFiles(runId),
      uploadedFiles: uploadRepository.list(applicationRun.profileId)
    });
    writeWorkerControlFile({
      runId,
      command: "RESUME",
      reason: `local_user_approved_${approvalType.toLowerCase()}`,
      payload: {
        approvalType,
        autoSubmitEnabled: applicationRun.autoSubmitEnabled,
        approvedAnswers,
        generatedFiles
      }
    });
    runRepository.recordApprovalDecision({
      applicationRunId: runId,
      approvalType,
      status: "APPROVED"
    });
    auditRepository.append({
      action: "run.approved",
      entityType: "application_run",
      entityId: runId,
      metadata: { approvalType }
    });
    return { accepted: true };
  });
  handleContract(IpcContracts.runsReject, ({ runId, reason, approvalType }) => {
    const resolvedApprovalType = approvalType ?? "FINAL_SUBMIT";
    writeWorkerControlFile({ runId, command: "CANCEL", reason });
    if (resolvedApprovalType === "ANSWER_EDIT") {
      runRepository.rejectPendingAnswers(runId);
    }
    runRepository.recordApprovalDecision({
      applicationRunId: runId,
      approvalType: resolvedApprovalType,
      status: "REJECTED",
      notes: reason
    });
    workerSupervisor.stop(runId);
    auditRepository.append({
      action: "run.rejected",
      entityType: "application_run",
      entityId: runId,
      metadata: { reasonLength: reason.length, approvalType: resolvedApprovalType }
    });
    return updateRunAndQueueStatus(runId, "CANCELLED");
  });
  handleContract(IpcContracts.logsSubscribe, () => ({ subscribed: true }));

  handleContract(IpcContracts.screenshotsList, ({ runId }) => {
    const rows = db.prepare("SELECT * FROM screenshots WHERE application_run_id = ? ORDER BY captured_at ASC").all(runId) as Array<{
      id: string;
      application_run_id: string;
      step_id: string | null;
      screenshot_id: string;
      local_path: string;
      mime_type: string;
      width: number;
      height: number;
      sha256: string | null;
      captured_at: string;
    }>;

    return {
      items: rows.map((row) =>
        ScreenshotSchema.parse({
          id: row.id,
          applicationRunId: row.application_run_id,
          stepId: row.step_id,
          screenshotId: row.screenshot_id,
          localPath: row.local_path,
          mimeType: row.mime_type,
          width: row.width,
          height: row.height,
          sha256: row.sha256,
          capturedAt: row.captured_at
        })
      )
    };
  });

  handleContract(IpcContracts.foldersOpenDownloads, async () => {
    const error = await shell.openPath(app.getPath("downloads"));
    return { opened: error.length === 0 };
  });

  handleContract(IpcContracts.foldersChooseOutputDir, async () => {
    const owner = getMainWindow();
    const result = owner
      ? await dialog.showOpenDialog(owner, { properties: ["openDirectory"] })
      : await dialog.showOpenDialog({ properties: ["openDirectory"] });
    return {
      canceled: result.canceled,
      localPath: result.canceled ? null : result.filePaths[0] ?? null
    };
  });
};
