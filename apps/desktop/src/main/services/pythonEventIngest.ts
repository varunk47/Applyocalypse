import { createHash, randomUUID } from "node:crypto";
import { existsSync, readFileSync, statSync } from "node:fs";
import { isAbsolute, normalize, relative, resolve } from "node:path";
import type { BrowserWindow } from "electron";
import { AuditRepository, JobAnalysisRepository, RunRepository, TailoringRunRepository, type ApplyocalypseDatabase } from "@applyocalypse/db";
import { IpcChannels } from "@applyocalypse/ipc-contracts";
import {
  BrowserArtifactPayloadSchema,
  GeneratedFilePayloadSchema,
  PythonWorkerEventSchema,
  SafeRendererRunEventSchema,
  ScreenshotPayloadSchema
} from "@applyocalypse/shared-schemas";

type PythonEventIngestInput = {
  db: ApplyocalypseDatabase;
  windows: () => BrowserWindow[];
  rawLine: string;
  safeArtifactRoots?: string[];
};

type PythonWorkerEvent = ReturnType<typeof PythonWorkerEventSchema.parse>;
type BlockerReviewType = "CAPTCHA" | "MFA" | "OTP" | "AMBIGUOUS_QUESTION" | "LOGIN" | "PORTAL_ENTRY" | "PORTAL_STEP" | "ANSWER";

const parsePayloadJson = (value: unknown): string => JSON.stringify(value ?? {});

const isGeneratedFileEvent = (eventType: string): boolean => eventType === "RESUME_RENDERED" || eventType === "COVER_LETTER_RENDERED";

const isPathInsideRoot = (localPath: string, root: string): boolean => {
  const relativePath = relative(root, localPath);
  return relativePath === "" || (!relativePath.startsWith("..") && !isAbsolute(relativePath));
};

const normalizeSafeArtifactPath = (localPath: string, safeArtifactRoots: string[] | undefined, label: string): string => {
  if (!isAbsolute(localPath)) {
    throw new Error(`${label} path must be absolute`);
  }
  const normalizedPath = normalize(resolve(localPath));
  const normalizedRoots = (safeArtifactRoots ?? []).map((root) => normalize(resolve(root)));
  if (normalizedRoots.length > 0 && !normalizedRoots.some((root) => isPathInsideRoot(normalizedPath, root))) {
    throw new Error(`${label} path is outside Applyocalypse artifact roots`);
  }
  return normalizedPath;
};

const assertArtifactFileAndHash = (localPath: string, label: string, expectedSha256?: string | null): string => {
  if (!existsSync(localPath)) {
    throw new Error(`${label} path does not exist`);
  }
  const stats = statSync(localPath);
  if (!stats.isFile()) {
    throw new Error(`${label} path must point to a file`);
  }
  const actualSha256 = createHash("sha256").update(readFileSync(localPath)).digest("hex");
  if (expectedSha256 && expectedSha256 !== actualSha256) {
    throw new Error(`${label} sha256 does not match file contents`);
  }
  return actualSha256;
};

const stepTypeForEvent = (eventType: string): string | null => {
  const map = {
    RUN_STARTED: "PREPARING",
    JD_SCRAPE_STARTED: "JD_SCRAPE",
    JD_SCRAPE_COMPLETED: "JD_SCRAPE",
    JD_ANALYSIS_COMPLETED: "JD_ANALYSIS",
    RESUME_TAILORING_STARTED: "RESUME_TAILORING",
    RESUME_MUTATION_COMPLETED: "RESUME_TAILORING",
    RESUME_RENDERED: "RESUME_TAILORING",
    COVER_LETTER_REQUIRED: "COVER_LETTER",
    COVER_LETTER_RENDERED: "COVER_LETTER",
    VALIDATION_FAILED: "DOCUMENT_VALIDATION",
    BROWSER_LAUNCHED: "BROWSER_NAVIGATION",
    PAGE_NAVIGATED: "BROWSER_NAVIGATION",
    PORTAL_WORKFLOW_SELECTED: "PORTAL_WORKFLOW",
    PORTAL_ACTION_APPLIED: "PORTAL_WORKFLOW",
    BROWSER_ARTIFACT_CAPTURED: "BROWSER_OBSERVABILITY",
    FIELD_DETECTED: "FIELD_REVIEW",
    FIELD_VALUE_PROPOSED: "FIELD_REVIEW",
    FIELD_VALUE_APPLIED: "FIELD_REVIEW",
    FILE_UPLOADED: "FILE_UPLOAD",
    SCREENSHOT_CAPTURED: "SCREENSHOT_CAPTURE",
    OTP_RETRIEVAL_STARTED: "OTP_RETRIEVAL",
    OTP_RETRIEVAL_COMPLETED: "OTP_RETRIEVAL",
    OTP_RETRIEVAL_FAILED: "OTP_RETRIEVAL",
    USER_REVIEW_REQUIRED: "USER_REVIEW",
    READY_TO_SUBMIT: "FINAL_SUBMIT_GATE",
    SUBMITTED: "FINAL_SUBMIT",
    PAUSED: "PAUSE",
    RESUMED: "RESUME",
    FAILED: "FAILURE",
    CLEANUP_COMPLETED: "CLEANUP"
  } as const;
  return map[eventType as keyof typeof map] ?? null;
};

const stepStatusForEvent = (eventType: string): string => {
  if (eventType === "FAILED") return "FAILED";
  if (eventType === "PAUSED") return "PAUSED";
  if (eventType === "OTP_RETRIEVAL_FAILED") return "WAITING_FOR_USER";
  if (eventType === "USER_REVIEW_REQUIRED" || eventType === "READY_TO_SUBMIT") return "WAITING_FOR_USER";
  if (
    [
      "JD_SCRAPE_COMPLETED",
      "JD_ANALYSIS_COMPLETED",
      "RESUME_MUTATION_COMPLETED",
      "RESUME_RENDERED",
      "COVER_LETTER_RENDERED",
      "PORTAL_WORKFLOW_SELECTED",
      "PORTAL_ACTION_APPLIED",
      "FIELD_VALUE_APPLIED",
      "FILE_UPLOADED",
      "SCREENSHOT_CAPTURED",
      "OTP_RETRIEVAL_COMPLETED",
      "SUBMITTED",
      "CLEANUP_COMPLETED"
    ].includes(eventType)
  ) {
    return "COMPLETED";
  }
  return "RUNNING";
};

const materializeApplicationStep = (db: ApplyocalypseDatabase, event: PythonWorkerEvent): string | null => {
  const stepType = stepTypeForEvent(event.event_type);
  if (!stepType) {
    return null;
  }

  const existing = event.step_id
    ? (db.prepare("SELECT id FROM application_steps WHERE id = ? AND application_run_id = ?").get(event.step_id, event.run_id) as
        | { id: string }
        | undefined)
    : (db
        .prepare(
          `
          SELECT id
          FROM application_steps
          WHERE application_run_id = @runId
            AND step_type = @stepType
          ORDER BY step_order ASC
          LIMIT 1
        `
        )
        .get({ runId: event.run_id, stepType }) as { id: string } | undefined);

  const status = stepStatusForEvent(event.event_type);
  const resultJson = JSON.stringify({
    eventType: event.event_type,
    severity: event.severity,
    message: event.message,
    payload: event.payload
  });
  if (existing) {
    db.prepare(
      `
      UPDATE application_steps
      SET status = @status,
          page_url = COALESCE(@pageUrl, page_url),
          selector = COALESCE(@selector, selector),
          result_json = @resultJson,
          updated_at = @updatedAt
      WHERE id = @id
    `
    ).run({
      id: existing.id,
      status,
      pageUrl: typeof event.payload["url"] === "string" ? event.payload["url"] : null,
      selector: typeof event.payload["selector"] === "string" ? event.payload["selector"] : null,
      resultJson,
      updatedAt: event.timestamp
    });
    return existing.id;
  }

  const orderRow = db.prepare("SELECT COALESCE(MAX(step_order), -1) + 1 AS step_order FROM application_steps WHERE application_run_id = ?").get(event.run_id) as {
    step_order: number;
  };
  const stepId = event.step_id ?? randomUUID();
  db.prepare(
    `
    INSERT INTO application_steps (
      id, application_run_id, step_order, step_type, status, page_url,
      selector, expected_state_json, result_json, created_at, updated_at
    )
    VALUES (
      @id, @runId, @stepOrder, @stepType, @status, @pageUrl,
      @selector, @expectedStateJson, @resultJson, @createdAt, @createdAt
    )
  `
  ).run({
    id: stepId,
    runId: event.run_id,
    stepOrder: orderRow.step_order,
    stepType,
    status,
    pageUrl: typeof event.payload["url"] === "string" ? event.payload["url"] : null,
    selector: typeof event.payload["selector"] === "string" ? event.payload["selector"] : null,
    expectedStateJson: JSON.stringify({ eventType: event.event_type, machineState: event.machine_state }),
    resultJson,
    createdAt: event.timestamp
  });
  return stepId;
};

const readValidationReport = (localPath: unknown): Record<string, unknown> | null => {
  if (typeof localPath !== "string" || !isAbsolute(localPath) || !existsSync(localPath)) {
    return null;
  }
  const parsed = JSON.parse(readFileSync(localPath, "utf8")) as unknown;
  return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? (parsed as Record<string, unknown>) : null;
};

const blockerReviewTypeForPause = (machineState: Record<string, unknown>): BlockerReviewType | null => {
  const reason = String(machineState["reason"] ?? "");
  if (reason === "CAPTCHA_DETECTED") return "CAPTCHA";
  if (reason === "MFA_DETECTED") return "MFA";
  if (reason === "OTP_DETECTED") return "OTP";
  if (reason === "LOGIN_DETECTED") return "LOGIN";
  if (reason === "PORTAL_ENTRY_ACTION_REQUIRED") return "PORTAL_ENTRY";
  if (reason === "PORTAL_REDIRECT_REVIEW_REQUIRED") return "PORTAL_ENTRY";
  if (reason === "PORTAL_STEP_ACTION_REQUIRED") return "PORTAL_STEP";
  if (reason === "MAX_PORTAL_STEPS_REACHED") return "PORTAL_STEP";
  if (reason === "AMBIGUOUS_QUESTION_DETECTED") return "AMBIGUOUS_QUESTION";
  if (reason === "FIELD_REVIEW_REQUIRED") return "ANSWER";
  return null;
};

const createBlockerReviewRequest = (input: {
  db: ApplyocalypseDatabase;
  runRepository: RunRepository;
  event: PythonWorkerEvent;
  materializedStepId: string | null;
}): void => {
  const reviewType = blockerReviewTypeForPause(input.event.machine_state);
  if (!reviewType) {
    return;
  }
  const existing = input.db
    .prepare(
      `
      SELECT id
      FROM review_requests
      WHERE application_run_id = @runId
        AND review_type = @reviewType
        AND status = 'OPEN'
      LIMIT 1
    `
    )
    .get({ runId: input.event.run_id, reviewType }) as { id: string } | undefined;
  if (existing) {
    return;
  }
  const reviewPayload: Record<string, unknown> = {
    reason: input.event.machine_state["reason"] ?? null,
    uiState: input.event.ui_state,
    payload: input.event.payload
  };
  for (const key of ["attempted_labels", "candidate_labels", "candidate_count", "ambiguity_code", "portal_id", "workflow_kind"]) {
    if (input.event.payload[key] !== undefined) {
      reviewPayload[key] = input.event.payload[key];
    }
  }

  input.runRepository.createReviewRequest({
    applicationRunId: input.event.run_id,
    stepId: input.materializedStepId ?? input.event.step_id,
    reviewType,
    prompt: input.event.message,
    payload: reviewPayload
  });
  new AuditRepository(input.db).append({
    actor: "python_worker",
    action: `automation.blocked.${reviewType.toLowerCase()}`,
    entityType: "application_run",
    entityId: input.event.run_id,
    metadata: {
      reviewType,
      stepId: input.materializedStepId ?? input.event.step_id,
      reason: input.event.machine_state["reason"] ?? null
    }
  });
};

const persistValidationReport = (input: {
  db: ApplyocalypseDatabase;
  applicationRunId: string;
  generatedFileId?: string | null;
  sourceKind: "TXT" | "MD" | "DOCX" | "TEX" | "PDF_RENDERED";
  report: Record<string, unknown>;
  createdAt: string;
}): void => {
  const runRow = input.db.prepare("SELECT tailoring_run_id FROM application_runs WHERE id = ?").get(input.applicationRunId) as
    | { tailoring_run_id: string | null }
    | undefined;
  const blockingIssues = Array.isArray(input.report["blocking_issues"]) ? input.report["blocking_issues"] : [];
  const warnings = Array.isArray(input.report["warnings"]) ? input.report["warnings"] : [];
  input.db
    .prepare(
      `
      INSERT INTO validation_reports (
        id, tailoring_run_id, generated_file_id, source_kind, passed,
        blocking_issues_json, warnings_json, report_json, created_at, updated_at
      )
      VALUES (
        @id, @tailoringRunId, @generatedFileId, @sourceKind, @passed,
        @blockingIssuesJson, @warningsJson, @reportJson, @createdAt, @createdAt
      )
    `
    )
    .run({
      id: randomUUID(),
      tailoringRunId: runRow?.tailoring_run_id ?? null,
      generatedFileId: input.generatedFileId ?? null,
      sourceKind: input.sourceKind,
      passed: input.report["passed"] === true ? 1 : 0,
      blockingIssuesJson: JSON.stringify(blockingIssues),
      warningsJson: JSON.stringify(warnings),
      reportJson: JSON.stringify(input.report),
      createdAt: input.createdAt
    });
};

const persistOtpSessionEvent = (db: ApplyocalypseDatabase, event: PythonWorkerEvent): void => {
  if (!["OTP_RETRIEVAL_STARTED", "OTP_RETRIEVAL_COMPLETED", "OTP_RETRIEVAL_FAILED"].includes(event.event_type)) {
    return;
  }
  const now = event.timestamp;
  const providerConnection = db
    .prepare(
      `
      SELECT id
      FROM provider_connections
      WHERE provider = 'gmail'
        AND status = 'CONNECTED'
        AND deleted_at IS NULL
      ORDER BY updated_at DESC
      LIMIT 1
    `
    )
    .get() as { id: string } | undefined;
  const openSession = db
    .prepare(
      `
      SELECT id
      FROM otp_sessions
      WHERE application_run_id = @runId
        AND status IN ('REQUESTED', 'WAITING')
      ORDER BY requested_at DESC
      LIMIT 1
    `
    )
    .get({ runId: event.run_id }) as { id: string } | undefined;

  if (event.event_type === "OTP_RETRIEVAL_STARTED") {
    db.prepare(
      `
      INSERT INTO otp_sessions (
        id, application_run_id, provider_connection_id, status, purpose,
        requested_at, metadata_json, created_at, updated_at
      )
      VALUES (
        @id, @runId, @providerConnectionId, 'REQUESTED', 'job_portal_otp',
        @requestedAt, @metadataJson, @requestedAt, @requestedAt
      )
    `
    ).run({
      id: randomUUID(),
      runId: event.run_id,
      providerConnectionId: providerConnection?.id ?? null,
      requestedAt: now,
      metadataJson: parsePayloadJson({ provider: "gmail", eventId: event.step_id, payload: event.payload })
    });
    return;
  }

  const status =
    event.event_type === "OTP_RETRIEVAL_COMPLETED"
      ? "COMPLETED"
      : event.payload["metadata"] && typeof event.payload["metadata"] === "object" && (event.payload["metadata"] as Record<string, unknown>)["status"] === "timeout"
        ? "TIMEOUT"
        : "FAILED";
  if (openSession) {
    db.prepare(
      `
      UPDATE otp_sessions
      SET status = @status,
          completed_at = CASE WHEN @status = 'COMPLETED' THEN @now ELSE completed_at END,
          metadata_json = @metadataJson,
          updated_at = @now
      WHERE id = @id
    `
    ).run({
      id: openSession.id,
      status,
      now,
      metadataJson: parsePayloadJson({ provider: "gmail", payload: event.payload })
    });
    return;
  }

  db.prepare(
    `
    INSERT INTO otp_sessions (
      id, application_run_id, provider_connection_id, status, purpose,
      requested_at, completed_at, metadata_json, created_at, updated_at
    )
    VALUES (
      @id, @runId, @providerConnectionId, @status, 'job_portal_otp',
      @now, CASE WHEN @status = 'COMPLETED' THEN @now ELSE NULL END,
      @metadataJson, @now, @now
    )
  `
  ).run({
    id: randomUUID(),
    runId: event.run_id,
    providerConnectionId: providerConnection?.id ?? null,
    status,
    now,
    metadataJson: parsePayloadJson({ provider: "gmail", payload: event.payload })
  });
};

export const ingestPythonEventLine = ({ db, windows, rawLine, safeArtifactRoots }: PythonEventIngestInput): void => {
  const event = PythonWorkerEventSchema.parse(JSON.parse(rawLine));
  const runRepository = new RunRepository(db);
  const eventId = randomUUID();
  const createdAt = event.timestamp;

  db.prepare(
    `
    INSERT INTO run_events (
      id, application_run_id, step_id, event_type, severity, message,
      machine_state_json, ui_state_json, payload_json, created_at
    )
    VALUES (
      @id, @runId, @stepId, @eventType, @severity, @message,
      @machineStateJson, @uiStateJson, @payloadJson, @createdAt
    )
  `
  ).run({
    id: eventId,
    runId: event.run_id,
    stepId: event.step_id,
    eventType: event.event_type,
    severity: event.severity,
    message: event.message,
    machineStateJson: parsePayloadJson(event.machine_state),
    uiStateJson: parsePayloadJson(event.ui_state),
    payloadJson: parsePayloadJson(event.payload),
    createdAt
  });

  const materializedStepId = materializeApplicationStep(db, event);
  persistOtpSessionEvent(db, event);

  if (event.event_type === "SCREENSHOT_CAPTURED") {
    const screenshot = ScreenshotPayloadSchema.parse(event.payload);
    const localPath = normalizeSafeArtifactPath(screenshot.local_path, safeArtifactRoots, "Screenshot");
    const sha256 = assertArtifactFileAndHash(localPath, "Screenshot", screenshot.sha256);
    db.prepare(
      `
      INSERT INTO screenshots (
        id, application_run_id, step_id, screenshot_id, local_path,
        mime_type, width, height, sha256, captured_at
      )
      VALUES (
        @id, @runId, @stepId, @screenshotId, @localPath,
        @mimeType, @width, @height, @sha256, @capturedAt
      )
      ON CONFLICT(application_run_id, screenshot_id) DO UPDATE SET
        step_id = excluded.step_id,
        local_path = excluded.local_path,
        mime_type = excluded.mime_type,
        width = excluded.width,
        height = excluded.height,
        sha256 = excluded.sha256,
        captured_at = excluded.captured_at
    `
    ).run({
      id: randomUUID(),
      runId: event.run_id,
      stepId: event.step_id,
      screenshotId: screenshot.screenshot_id,
      localPath,
      mimeType: screenshot.mime_type,
      width: screenshot.width,
      height: screenshot.height,
      sha256,
      capturedAt: screenshot.captured_at
    });
  }

  if (event.event_type === "BROWSER_ARTIFACT_CAPTURED") {
    const artifact = BrowserArtifactPayloadSchema.parse(event.payload);
    const localPath = normalizeSafeArtifactPath(artifact.local_path, safeArtifactRoots, "Browser artifact");
    if (!existsSync(localPath)) {
      throw new Error("Browser artifact path does not exist");
    }
    const stats = statSync(localPath);
    if (!stats.isFile()) {
      throw new Error("Browser artifact path must point to a file");
    }
    db.prepare(
      `
      INSERT INTO browser_artifacts (
        id, application_run_id, artifact_type, local_path, metadata_json, created_at
      )
      VALUES (
        @id, @runId, @artifactType, @localPath, @metadataJson, @createdAt
      )
    `
    ).run({
      id: artifact.artifact_id,
      runId: event.run_id,
      artifactType: artifact.artifact_type,
      localPath,
      metadataJson: JSON.stringify({ ...artifact.metadata, mimeType: artifact.mime_type ?? null }),
      createdAt: artifact.captured_at
    });
  }

  if (isGeneratedFileEvent(event.event_type)) {
    const generatedFile = GeneratedFilePayloadSchema.parse(event.payload);
    const localPath = normalizeSafeArtifactPath(generatedFile.local_path, safeArtifactRoots, "Generated file");
    if (!existsSync(localPath)) {
      throw new Error("Generated file path does not exist");
    }
    const stats = statSync(localPath);
    if (!stats.isFile()) {
      throw new Error("Generated file path must point to a file");
    }
    const runRow = db.prepare("SELECT profile_id, job_target_id, tailoring_run_id FROM application_runs WHERE id = ?").get(event.run_id) as
      | { profile_id: string; job_target_id: string; tailoring_run_id: string | null }
      | undefined;
    if (!runRow) {
      throw new Error(`Application run not found: ${event.run_id}`);
    }
    const persistedFile = runRepository.addGeneratedFile({
      tailoringRunId: runRow.tailoring_run_id,
      profileId: runRow.profile_id,
      jobTargetId: runRow.job_target_id,
      fileKind: generatedFile.file_kind,
      format: generatedFile.format,
      filename: generatedFile.filename,
      localPath,
      sha256: generatedFile.sha256,
      sizeBytes: generatedFile.size_bytes ?? stats.size,
      uploadStatus: "NOT_UPLOADED",
      uploadedAt: null,
      retentionPolicy: generatedFile.retention_policy,
      deleteAfter: generatedFile.delete_after ?? null,
      deletedAt: null
    });
    const validationReport = readValidationReport(generatedFile.validation_report_path);
    if (validationReport) {
      persistValidationReport({
        db,
        applicationRunId: event.run_id,
        generatedFileId: persistedFile.id,
        sourceKind: generatedFile.format === "PDF" ? "PDF_RENDERED" : generatedFile.format,
        report: validationReport,
        createdAt: event.timestamp
      });
    }
  }

  if (event.event_type === "VALIDATION_FAILED") {
    const report = readValidationReport(event.payload["validation_report_path"]) ?? event.payload;
    const sourceFormat = typeof event.payload["format"] === "string" ? event.payload["format"] : "MD";
    const sourceKind =
      sourceFormat === "PDF" ? "PDF_RENDERED" : ["TXT", "MD", "DOCX", "TEX"].includes(sourceFormat) ? (sourceFormat as "TXT" | "MD" | "DOCX" | "TEX") : "MD";
    persistValidationReport({
      db,
      applicationRunId: event.run_id,
      generatedFileId: null,
      sourceKind,
      report,
      createdAt: event.timestamp
    });
  }

  if (event.event_type === "JD_ANALYSIS_COMPLETED") {
    const sourceTextPath = event.payload["source_text_path"];
    if (typeof sourceTextPath === "string" && isAbsolute(sourceTextPath) && existsSync(sourceTextPath)) {
      const jdSource = event.payload["jd_source"] === "SCRAPED" ? "SCRAPED" : "USER_TEXT";
      new JobAnalysisRepository(db).persistFromWorkerEvent({
        applicationRunId: event.run_id,
        rawText: readFileSync(sourceTextPath, "utf8"),
        scrapedUrl: typeof event.payload["url"] === "string" ? event.payload["url"] : null,
        source: jdSource,
        analysis: event.payload,
        extractedAt: event.timestamp
      });
    }
  }

  const nextStatus = statusForEvent(event.event_type, event.machine_state);
  if (nextStatus) {
    runRepository.updateRunStatus({
      runId: event.run_id,
      status: nextStatus,
      currentStepId: materializedStepId ?? event.step_id,
      failureCode: event.event_type === "FAILED" ? String(event.payload["code"] ?? "WORKER_FAILED") : null,
      failureMessage: event.event_type === "FAILED" ? event.message : null
    });
    db.prepare(
      `
      UPDATE queue_items
      SET status = @status,
          updated_at = @updatedAt
      WHERE id = (SELECT queue_item_id FROM application_runs WHERE id = @runId)
    `
    ).run({
      runId: event.run_id,
      status: nextStatus,
      updatedAt: event.timestamp
    });
  }

  if (event.event_type === "PAUSED") {
    createBlockerReviewRequest({
      db,
      runRepository,
      event,
      materializedStepId
    });
  }

  if (event.event_type === "USER_REVIEW_REQUIRED" || event.event_type === "READY_TO_SUBMIT") {
    if (event.event_type === "USER_REVIEW_REQUIRED") {
      const tailoringPlanPath = event.payload["tailoring_plan_path"];
      if (typeof tailoringPlanPath === "string" && isAbsolute(tailoringPlanPath) && existsSync(tailoringPlanPath)) {
        const plan = JSON.parse(readFileSync(tailoringPlanPath, "utf8")) as Record<string, unknown>;
        new TailoringRunRepository(db).createFromPlan({
          applicationRunId: event.run_id,
          resumePlan: plan,
          coverLetterPlan: { coverLetterRequired: event.payload["cover_letter_required"] === true },
          status: "READY_FOR_REVIEW"
        });
      }
    }
    if (event.event_type === "READY_TO_SUBMIT" && event.payload["auto_submit_enabled"] === true) {
      runRepository.createApproval({
        applicationRunId: event.run_id,
        approvalType: "AUTO_SUBMIT",
        status: "APPROVED",
        notes: "Auto-submit was explicitly enabled before the run reached final submit."
      });
      new AuditRepository(db).append({
        actor: "python_worker",
        action: "run.auto_submit_preapproved",
        entityType: "application_run",
        entityId: event.run_id,
        metadata: { stepId: event.step_id }
      });
    } else {
      const reviewType = event.event_type === "READY_TO_SUBMIT" ? "FINAL_SUBMIT" : "DOCUMENT";
      const existingReview = db
        .prepare(
          `
          SELECT id
          FROM review_requests
          WHERE application_run_id = @runId
            AND review_type = @reviewType
            AND status = 'OPEN'
          LIMIT 1
        `
        )
        .get({ runId: event.run_id, reviewType }) as { id: string } | undefined;
      if (!existingReview) {
        runRepository.createReviewRequest({
          applicationRunId: event.run_id,
          stepId: event.step_id,
          reviewType,
          prompt: event.message,
          payload: event.payload
        });
      }
    }
  }

  if (event.event_type === "FIELD_VALUE_PROPOSED") {
    const fieldLabel = String(event.payload["field_label"] ?? "Detected field");
    const fieldType = String(event.payload["field_type"] ?? "text");
    const proposedSource = String(event.payload["source"] ?? "LLM_PROPOSAL");
    const source = ["PROFILE", "JD_ANALYSIS", "USER_EDIT", "LLM_PROPOSAL", "UNKNOWN"].includes(proposedSource)
      ? (proposedSource as "PROFILE" | "JD_ANALYSIS" | "USER_EDIT" | "LLM_PROPOSAL" | "UNKNOWN")
      : "LLM_PROPOSAL";
    const existing = db
      .prepare(
        `
        SELECT id
        FROM application_answers
        WHERE application_run_id = @runId
          AND field_label = @fieldLabel
          AND field_type = @fieldType
        ORDER BY created_at ASC
        LIMIT 1
      `
      )
      .get({ runId: event.run_id, fieldLabel, fieldType }) as { id: string } | undefined;
    runRepository.upsertAnswer({
      ...(existing ? { id: existing.id } : {}),
      applicationRunId: event.run_id,
      stepId: event.step_id,
      fieldLabel,
      fieldType,
      proposedValue: event.payload["proposed_value"] == null ? null : String(event.payload["proposed_value"]),
      source,
      confidence: typeof event.payload["confidence"] === "number" ? event.payload["confidence"] : 0.5,
      status: "PROPOSED"
    });
  }

  if (event.event_type === "FIELD_VALUE_APPLIED") {
    const fieldLabel = String(event.payload["field_label"] ?? "Detected field");
    const fieldType = String(event.payload["field_type"] ?? "text");
    const applyMetadata = {
      appliedAction: typeof event.payload["applied_action"] === "string" ? event.payload["applied_action"] : null,
      selector: typeof event.payload["selector"] === "string" ? event.payload["selector"] : null,
      valueLength: typeof event.payload["value_length"] === "number" ? event.payload["value_length"] : null,
      checked: typeof event.payload["checked"] === "boolean" ? event.payload["checked"] : null,
      selectedLabel: typeof event.payload["selected_label"] === "string" ? event.payload["selected_label"] : null,
      selectedValueLength: typeof event.payload["selected_value_length"] === "number" ? event.payload["selected_value_length"] : null,
      source: typeof event.payload["source"] === "string" ? event.payload["source"] : null
    };
    db.prepare(
      `
      UPDATE application_answers
      SET status = 'APPLIED',
          apply_metadata_json = @applyMetadataJson,
          updated_at = @updatedAt
      WHERE application_run_id = @runId
        AND field_label = @fieldLabel
        AND field_type = @fieldType
    `
    ).run({
      runId: event.run_id,
      fieldLabel,
      fieldType,
      applyMetadataJson: parsePayloadJson(applyMetadata),
      updatedAt: event.timestamp
    });
  }

  if (event.event_type === "FILE_UPLOADED") {
    const generatedFileId = typeof event.payload["generated_file_id"] === "string" ? event.payload["generated_file_id"] : null;
    const localPath =
      typeof event.payload["local_path"] === "string" ? normalizeSafeArtifactPath(event.payload["local_path"], safeArtifactRoots, "Uploaded file") : null;
    if (localPath !== null && !existsSync(localPath)) {
      throw new Error("Uploaded file path does not exist");
    }
    if (generatedFileId !== null || localPath !== null) {
      db.prepare(
        `
        UPDATE generated_files
        SET upload_status = 'UPLOADED',
            uploaded_at = @uploadedAt,
            updated_at = @uploadedAt
        WHERE deleted_at IS NULL
          AND (
            (@generatedFileId IS NOT NULL AND id = @generatedFileId)
            OR (@localPath IS NOT NULL AND local_path = @localPath)
          )
          AND EXISTS (
            SELECT 1
            FROM application_runs
            WHERE application_runs.id = @runId
              AND (
                generated_files.tailoring_run_id = application_runs.tailoring_run_id
                OR (
                  generated_files.tailoring_run_id IS NULL
                  AND generated_files.profile_id = application_runs.profile_id
                  AND generated_files.job_target_id = application_runs.job_target_id
                )
              )
          )
      `
      ).run({
        runId: event.run_id,
        generatedFileId,
        localPath,
        uploadedAt: event.timestamp
      });
    }
  }

  const safeEvent = SafeRendererRunEventSchema.parse({
    eventType: event.event_type,
    runId: event.run_id,
    stepId: event.step_id,
    timestamp: event.timestamp,
    severity: event.severity,
    message: event.message,
    uiState: event.ui_state,
    payload: event.payload
  });

  for (const window of windows()) {
    if (!window.isDestroyed()) {
      window.webContents.send(IpcChannels.logsEvent, safeEvent);
    }
  }
};

const statusForEvent = (eventType: string, machineState: Record<string, unknown> = {}) => {
  if (eventType === "PAUSED") {
    const reason = String(machineState["reason"] ?? "");
    if (reason === "CAPTCHA_DETECTED") return "BLOCKED_CAPTCHA";
    if (reason === "MFA_DETECTED") return "BLOCKED_MFA";
    if (reason === "OTP_DETECTED") return "BLOCKED_OTP";
    if (reason === "AMBIGUOUS_QUESTION_DETECTED") return "BLOCKED_AMBIGUOUS_QUESTION";
    return "PAUSED";
  }
  const map = {
    RUN_STARTED: "PREPARING",
    JD_SCRAPE_STARTED: "PARSING_JD",
    JD_SCRAPE_COMPLETED: "ANALYZING",
    JD_ANALYSIS_COMPLETED: "ANALYZING",
    RESUME_TAILORING_STARTED: "TAILORING_RESUME",
    RESUME_MUTATION_COMPLETED: "TAILORING_RESUME",
    RESUME_RENDERED: "READY_FOR_REVIEW",
    COVER_LETTER_REQUIRED: "GENERATING_COVER_LETTER",
    COVER_LETTER_RENDERED: "READY_FOR_REVIEW",
    VALIDATION_FAILED: "WAITING_FOR_USER_EDIT",
    BROWSER_LAUNCHED: "RUNNING_AUTOMATION",
    PAGE_NAVIGATED: "RUNNING_AUTOMATION",
    PORTAL_WORKFLOW_SELECTED: "RUNNING_AUTOMATION",
    PORTAL_ACTION_APPLIED: "RUNNING_AUTOMATION",
    BROWSER_ARTIFACT_CAPTURED: "RUNNING_AUTOMATION",
    FIELD_VALUE_APPLIED: "RUNNING_AUTOMATION",
    FILE_UPLOADED: "RUNNING_AUTOMATION",
    OTP_RETRIEVAL_STARTED: "RUNNING_AUTOMATION",
    OTP_RETRIEVAL_COMPLETED: "RUNNING_AUTOMATION",
    OTP_RETRIEVAL_FAILED: "BLOCKED_OTP",
    USER_REVIEW_REQUIRED: "READY_FOR_REVIEW",
    RESUMED: "RUNNING_AUTOMATION",
    READY_TO_SUBMIT: "READY_TO_SUBMIT",
    SUBMITTED: "SUBMITTED",
    FAILED: "FAILED",
    CLEANUP_COMPLETED: "COMPLETED"
  } as const;
  return map[eventType as keyof typeof map] ?? null;
};
