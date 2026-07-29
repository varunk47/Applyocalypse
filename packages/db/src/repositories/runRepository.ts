import type { Database } from "better-sqlite3";
import { randomUUID } from "node:crypto";
import {
  ApplicationAnswerSchema,
  ApplicationRunSchema,
  ApplicationStepSchema,
  ApprovalSchema,
  BrowserArtifactSchema,
  GeneratedFileSchema,
  QueueStatusSchema,
  ReviewRequestSchema,
  RunEventSchema,
  ScreenshotSchema
} from "@applyocalypse/shared-schemas";
import type { z } from "zod";
import { parseJsonColumn, stringifyJsonColumn } from "../json";

export type ApplicationRun = z.infer<typeof ApplicationRunSchema>;
export type ApplicationStep = z.infer<typeof ApplicationStepSchema>;
export type ApplicationAnswer = z.infer<typeof ApplicationAnswerSchema>;
export type ReviewRequest = z.infer<typeof ReviewRequestSchema>;
export type Approval = z.infer<typeof ApprovalSchema>;
export type BrowserArtifact = z.infer<typeof BrowserArtifactSchema>;
export type GeneratedFile = z.infer<typeof GeneratedFileSchema>;
export type RunEvent = z.infer<typeof RunEventSchema>;
export type Screenshot = z.infer<typeof ScreenshotSchema>;

const nowIso = (): string => new Date().toISOString();

const recoverableActiveRunStatuses = [
  "CLAIMED",
  "PREPARING",
  "PARSING_JD",
  "ANALYZING",
  "TAILORING_RESUME",
  "GENERATING_COVER_LETTER",
  "READY_FOR_REVIEW",
  "RUNNING_AUTOMATION",
  "PAUSED",
  "BLOCKED_CAPTCHA",
  "BLOCKED_MFA",
  "BLOCKED_OTP",
  "BLOCKED_AMBIGUOUS_QUESTION",
  "WAITING_FOR_USER_EDIT",
  "READY_TO_SUBMIT"
] as const;

const terminalQueueStatuses = ["SUBMITTED", "COMPLETED", "FAILED", "CANCELLED"] as const;

const reviewTypeForApprovalType: Record<Approval["approvalType"], ReviewRequest["reviewType"]> = {
  FINAL_SUBMIT: "FINAL_SUBMIT",
  ANSWER_EDIT: "ANSWER",
  DOCUMENT_APPROVAL: "DOCUMENT",
  OTP_READ: "OTP",
  AUTO_SUBMIT: "FINAL_SUBMIT"
};

export class RunRepository {
  constructor(private readonly db: Database) {}

  createApplicationRun(input: {
    queueItemId: string;
    profileId: string;
    jobTargetId: string;
    tailoringRunId?: string | null;
    autoSubmitEnabled?: boolean;
    workerId?: string | null;
  }): ApplicationRun {
    const id = randomUUID();
    const now = nowIso();
    this.db
      .prepare(
        `
        INSERT INTO application_runs (
          id, queue_item_id, profile_id, job_target_id, tailoring_run_id,
          status, auto_submit_enabled, worker_id, started_at, created_at, updated_at
        )
        VALUES (
          @id, @queueItemId, @profileId, @jobTargetId, @tailoringRunId,
          'PREPARING', @autoSubmitEnabled, @workerId, @now, @now, @now
        )
      `
      )
      .run({
        id,
        queueItemId: input.queueItemId,
        profileId: input.profileId,
        jobTargetId: input.jobTargetId,
        tailoringRunId: input.tailoringRunId ?? null,
        autoSubmitEnabled: input.autoSubmitEnabled ? 1 : 0,
        workerId: input.workerId ?? null,
        now
      });

    return this.getApplicationRun(id);
  }

  getApplicationRun(id: string): ApplicationRun {
    const row = this.db.prepare("SELECT * FROM application_runs WHERE id = ?").get(id) as
      | {
          id: string;
          queue_item_id: string;
          profile_id: string;
          job_target_id: string;
          tailoring_run_id: string | null;
          status: string;
          current_step_id: string | null;
          auto_submit_enabled: number;
          started_at: string | null;
          completed_at: string | null;
          failure_code: string | null;
          failure_message: string | null;
          created_at: string;
          updated_at: string;
        }
      | undefined;

    if (!row) {
      throw new Error(`Application run not found: ${id}`);
    }

    return ApplicationRunSchema.parse({
      id: row.id,
      queueItemId: row.queue_item_id,
      profileId: row.profile_id,
      jobTargetId: row.job_target_id,
      tailoringRunId: row.tailoring_run_id,
      status: row.status,
      currentStepId: row.current_step_id,
      autoSubmitEnabled: row.auto_submit_enabled === 1,
      startedAt: row.started_at,
      completedAt: row.completed_at,
      failureCode: row.failure_code,
      failureMessage: row.failure_message,
      createdAt: row.created_at,
      updatedAt: row.updated_at
    });
  }

  listApplicationRuns(limit = 50, offset = 0): ApplicationRun[] {
    const rows = this.db
      .prepare(
        `
        SELECT id
        FROM application_runs
        ORDER BY created_at DESC
        LIMIT ? OFFSET ?
      `
      )
      .all(limit, offset) as Array<{ id: string }>;

    return rows.map((row) => this.getApplicationRun(row.id));
  }

  countApplicationRuns(): number {
    const row = this.db.prepare("SELECT COUNT(*) AS count FROM application_runs").get() as { count: number };
    return row.count;
  }

  updateRunStatus(input: {
    runId: string;
    status: z.infer<typeof QueueStatusSchema>;
    currentStepId?: string | null;
    failureCode?: string | null;
    failureMessage?: string | null;
  }): ApplicationRun {
    const status = QueueStatusSchema.parse(input.status);
    const now = nowIso();
    this.db
      .prepare(
        `
        UPDATE application_runs
        SET status = @status,
            current_step_id = COALESCE(@currentStepId, current_step_id),
            failure_code = @failureCode,
            failure_message = @failureMessage,
            completed_at = CASE WHEN @status IN ('COMPLETED','FAILED','CANCELLED','SUBMITTED') THEN @now ELSE completed_at END,
            updated_at = @now
        WHERE id = @runId
      `
      )
      .run({
        runId: input.runId,
        status,
        currentStepId: input.currentStepId ?? null,
        failureCode: input.failureCode ?? null,
        failureMessage: input.failureMessage ?? null,
        now
      });
    return this.getApplicationRun(input.runId);
  }

  /** Cancel every run parked awaiting the user (paused/blocked/waiting) and its queue item.
   * Lets the user clear an accumulated backlog of stuck runs in one action. */
  cancelPausedRuns(): number {
    const now = nowIso();
    const parked = ["PAUSED", "WAITING_FOR_USER_EDIT", "WAITING_FOR_USER", "BLOCKED_CAPTCHA"];
    const placeholders = parked.map(() => "?").join(", ");
    const runResult = this.db
      .prepare(
        `
        UPDATE application_runs
        SET status = 'CANCELLED', failure_code = 'USER_CLEARED_PAUSED', completed_at = ?, updated_at = ?
        WHERE status IN (${placeholders})
      `
      )
      .run(now, now, ...parked);
    this.db
      .prepare(
        `
        UPDATE queue_items
        SET status = 'CANCELLED', updated_at = ?
        WHERE status IN (${placeholders})
      `
      )
      .run(now, ...parked);
    return runResult.changes;
  }

  recoverStaleRuns(now = nowIso()): number {
    const recover = this.db.transaction(() => {
      const statusList = recoverableActiveRunStatuses.map((status) => `'${status}'`).join(",");
      const staleRows = this.db
        .prepare(
          `
          SELECT id, queue_item_id
          FROM application_runs
          WHERE status IN (${statusList})
            AND lease_expires_at IS NOT NULL
            AND lease_expires_at < @now
        `
        )
        .all({ now }) as Array<{ id: string; queue_item_id: string }>;

      if (staleRows.length === 0) {
        return 0;
      }

      const runIds = staleRows.map((row) => row.id);
      const queueItemIds = [...new Set(staleRows.map((row) => row.queue_item_id))];
      const runParams = Object.fromEntries(runIds.map((id, index) => [`runId${index}`, id]));
      const queueParams = Object.fromEntries(queueItemIds.map((id, index) => [`queueItemId${index}`, id]));
      const runPlaceholders = runIds.map((_, index) => `@runId${index}`).join(",");
      const queuePlaceholders = queueItemIds.map((_, index) => `@queueItemId${index}`).join(",");
      const terminalStatusList = terminalQueueStatuses.map((status) => `'${status}'`).join(",");

      const result = this.db
        .prepare(
          `
          UPDATE application_runs
          SET status = 'PAUSED',
              worker_id = NULL,
              lease_expires_at = NULL,
              heartbeat_at = NULL,
              failure_code = 'STALE_WORKER_RECOVERED',
              failure_message = 'Run was paused during startup recovery after its worker lease expired.',
              updated_at = @now
          WHERE id IN (${runPlaceholders})
        `
        )
        .run({ ...runParams, now });

      this.db
        .prepare(
          `
          UPDATE queue_items
          SET status = 'PAUSED',
              claimed_by = NULL,
              lease_expires_at = NULL,
              heartbeat_at = NULL,
              updated_at = @now
          WHERE id IN (${queuePlaceholders})
            AND status NOT IN (${terminalStatusList})
        `
        )
        .run({ ...queueParams, now });

      return result.changes;
    });

    return recover();
  }

  addStep(input: {
    applicationRunId: string;
    stepOrder: number;
    stepType: string;
    status?: ApplicationStep["status"];
    pageUrl?: string | null;
    selector?: string | null;
    expectedState?: Record<string, unknown>;
  }): ApplicationStep {
    const id = randomUUID();
    const now = nowIso();
    this.db
      .prepare(
        `
        INSERT INTO application_steps (
          id, application_run_id, step_order, step_type, status, page_url,
          selector, expected_state_json, result_json, created_at, updated_at
        )
        VALUES (
          @id, @applicationRunId, @stepOrder, @stepType, @status, @pageUrl,
          @selector, @expectedStateJson, '{}', @now, @now
        )
      `
      )
      .run({
        id,
        applicationRunId: input.applicationRunId,
        stepOrder: input.stepOrder,
        stepType: input.stepType,
        status: input.status ?? "PENDING",
        pageUrl: input.pageUrl ?? null,
        selector: input.selector ?? null,
        expectedStateJson: stringifyJsonColumn(input.expectedState ?? {}),
        now
      });
    return this.listSteps(input.applicationRunId).find((step) => step.id === id)!;
  }

  listSteps(applicationRunId: string): ApplicationStep[] {
    const rows = this.db
      .prepare("SELECT * FROM application_steps WHERE application_run_id = ? ORDER BY step_order ASC")
      .all(applicationRunId) as Array<{
      id: string;
      application_run_id: string;
      step_order: number;
      step_type: string;
      status: string;
      page_url: string | null;
      selector: string | null;
      expected_state_json: string;
      result_json: string;
      created_at: string;
      updated_at: string;
    }>;

    return rows.map((row) =>
      ApplicationStepSchema.parse({
        id: row.id,
        applicationRunId: row.application_run_id,
        stepOrder: row.step_order,
        stepType: row.step_type,
        status: row.status,
        pageUrl: row.page_url,
        selector: row.selector,
        expectedState: parseJsonColumn(row.expected_state_json, {}),
        result: parseJsonColumn(row.result_json, {}),
        createdAt: row.created_at,
        updatedAt: row.updated_at
      })
    );
  }

  upsertAnswer(input: {
    id?: string;
    applicationRunId: string;
    stepId?: string | null;
    fieldLabel: string;
    fieldType: string;
    proposedValue?: string | null;
    userValue?: string | null;
    source: ApplicationAnswer["source"];
    confidence: number;
    status?: ApplicationAnswer["status"];
    applyMetadata?: ApplicationAnswer["applyMetadata"];
  }): ApplicationAnswer {
    const id = input.id ?? randomUUID();
    const now = nowIso();
    this.db
      .prepare(
        `
        INSERT INTO application_answers (
          id, application_run_id, step_id, field_label, field_type, proposed_value,
          user_value, source, confidence, status, apply_metadata_json, created_at, updated_at
        )
        VALUES (
          @id, @applicationRunId, @stepId, @fieldLabel, @fieldType, @proposedValue,
          @userValue, @source, @confidence, @status, @applyMetadataJson, @now, @now
        )
        ON CONFLICT(id) DO UPDATE SET
          step_id = excluded.step_id,
          proposed_value = excluded.proposed_value,
          user_value = excluded.user_value,
          confidence = excluded.confidence,
          status = excluded.status,
          apply_metadata_json = excluded.apply_metadata_json,
          updated_at = excluded.updated_at
      `
      )
      .run({
        id,
        applicationRunId: input.applicationRunId,
        stepId: input.stepId ?? null,
        fieldLabel: input.fieldLabel,
        fieldType: input.fieldType,
        proposedValue: input.proposedValue ?? null,
        userValue: input.userValue ?? null,
        source: input.source,
        confidence: input.confidence,
        status: input.status ?? "PROPOSED",
        applyMetadataJson: stringifyJsonColumn(input.applyMetadata ?? {}),
        now
      });

    return this.listAnswers(input.applicationRunId).find((answer) => answer.id === id)!;
  }

  listAnswers(applicationRunId: string): ApplicationAnswer[] {
    const rows = this.db
      .prepare("SELECT * FROM application_answers WHERE application_run_id = ? ORDER BY created_at ASC")
      .all(applicationRunId) as Array<{
      id: string;
      application_run_id: string;
      step_id: string | null;
      field_label: string;
      field_type: string;
      proposed_value: string | null;
      user_value: string | null;
      source: string;
      confidence: number;
      status: string;
      apply_metadata_json: string;
    }>;

    return rows.map((row) =>
      ApplicationAnswerSchema.parse({
        id: row.id,
        applicationRunId: row.application_run_id,
        stepId: row.step_id,
        fieldLabel: row.field_label,
        fieldType: row.field_type,
        proposedValue: row.proposed_value,
        userValue: row.user_value,
        source: row.source,
        confidence: row.confidence,
        status: row.status,
        applyMetadata: parseJsonColumn(row.apply_metadata_json, {})
      })
    );
  }

  updateAnswerValue(input: {
    applicationRunId: string;
    answerId: string;
    userValue: string | null;
    status: ApplicationAnswer["status"];
  }): ApplicationAnswer {
    const now = nowIso();
    this.db
      .prepare(
        `
        UPDATE application_answers
        SET user_value = @userValue,
            status = @status,
            updated_at = @now
        WHERE id = @answerId
          AND application_run_id = @applicationRunId
      `
      )
      .run({
        applicationRunId: input.applicationRunId,
        answerId: input.answerId,
        userValue: input.userValue,
        status: input.status,
        now
      });

    const answer = this.listAnswers(input.applicationRunId).find((item) => item.id === input.answerId);
    if (!answer) {
      throw new Error(`Application answer not found: ${input.answerId}`);
    }
    return answer;
  }

  approvePendingAnswers(applicationRunId: string): number {
    const now = nowIso();
    const result = this.db
      .prepare(
        `
        UPDATE application_answers
        SET status = 'APPROVED',
            updated_at = @now
        WHERE application_run_id = @applicationRunId
          AND status IN ('PROPOSED', 'EDITED')
          AND COALESCE(user_value, proposed_value) IS NOT NULL
          AND length(trim(COALESCE(user_value, proposed_value))) > 0
      `
      )
      .run({ applicationRunId, now });
    return result.changes;
  }

  rejectPendingAnswers(applicationRunId: string): number {
    const now = nowIso();
    const result = this.db
      .prepare(
        `
        UPDATE application_answers
        SET status = 'REJECTED',
            updated_at = @now
        WHERE application_run_id = @applicationRunId
          AND status IN ('PROPOSED', 'APPROVED', 'EDITED')
      `
      )
      .run({ applicationRunId, now });
    return result.changes;
  }

  updateStepStatus(input: { applicationRunId: string; stepId: string; status: ApplicationStep["status"] }): ApplicationStep {
    const now = nowIso();
    this.db
      .prepare(
        `
        UPDATE application_steps
        SET status = @status,
            updated_at = @now
        WHERE id = @stepId
          AND application_run_id = @applicationRunId
      `
      )
      .run({
        applicationRunId: input.applicationRunId,
        stepId: input.stepId,
        status: input.status,
        now
      });

    const step = this.listSteps(input.applicationRunId).find((item) => item.id === input.stepId);
    if (!step) {
      throw new Error(`Application step not found: ${input.stepId}`);
    }
    return step;
  }

  createReviewRequest(input: {
    applicationRunId: string;
    stepId?: string | null;
    reviewType: ReviewRequest["reviewType"];
    prompt: string;
    payload?: Record<string, unknown>;
  }): ReviewRequest {
    const id = randomUUID();
    const now = nowIso();
    this.db
      .prepare(
        `
        INSERT INTO review_requests (
          id, application_run_id, step_id, review_type, prompt, payload_json, status, created_at, updated_at
        )
        VALUES (
          @id, @applicationRunId, @stepId, @reviewType, @prompt, @payloadJson, 'OPEN', @now, @now
        )
      `
      )
      .run({
        id,
        applicationRunId: input.applicationRunId,
        stepId: input.stepId ?? null,
        reviewType: input.reviewType,
        prompt: input.prompt,
        payloadJson: stringifyJsonColumn(input.payload ?? {}),
        now
      });
    return this.listReviewRequests(input.applicationRunId).find((request) => request.id === id)!;
  }

  listReviewRequests(applicationRunId: string): ReviewRequest[] {
    const rows = this.db
      .prepare("SELECT * FROM review_requests WHERE application_run_id = ? ORDER BY created_at ASC")
      .all(applicationRunId) as Array<{
      id: string;
      application_run_id: string;
      step_id: string | null;
      review_type: string;
      prompt: string;
      payload_json: string;
      status: string;
      created_at: string;
      updated_at: string;
    }>;

    return rows.map((row) =>
      ReviewRequestSchema.parse({
        id: row.id,
        applicationRunId: row.application_run_id,
        stepId: row.step_id,
        reviewType: row.review_type,
        prompt: row.prompt,
        payload: parseJsonColumn(row.payload_json, {}),
        status: row.status,
        createdAt: row.created_at,
        updatedAt: row.updated_at
      })
    );
  }

  decideReview(input: { reviewRequestId: string; status: "APPROVED" | "REJECTED"; notes?: string | null }): void {
    const now = nowIso();
    this.db
      .prepare(
        `
        UPDATE review_requests
        SET status = @status,
            resolved_at = @now,
            updated_at = @now
        WHERE id = @reviewRequestId
      `
      )
      .run({ reviewRequestId: input.reviewRequestId, status: input.status, now });
  }

  private decideOpenReviewForApproval(input: {
    applicationRunId: string;
    approvalType: Approval["approvalType"];
    status: "APPROVED" | "REJECTED";
    notes?: string | null;
  }): ReviewRequest | null {
    const preferredReviewType = reviewTypeForApprovalType[input.approvalType];
    const reviewRequest =
      this.listReviewRequests(input.applicationRunId).find(
        (request) => request.status === "OPEN" && request.reviewType === preferredReviewType
      ) ?? this.listReviewRequests(input.applicationRunId).find((request) => request.status === "OPEN");
    if (!reviewRequest) {
      return null;
    }

    this.decideReview({
      reviewRequestId: reviewRequest.id,
      status: input.status,
      notes: input.notes ?? null
    });
    return this.listReviewRequests(input.applicationRunId).find((request) => request.id === reviewRequest.id) ?? null;
  }

  recordApprovalDecision(input: {
    applicationRunId: string;
    approvalType: Approval["approvalType"];
    status: "APPROVED" | "REJECTED";
    notes?: string | null;
  }): Approval {
    const transaction = this.db.transaction(() => {
      const reviewRequest = this.decideOpenReviewForApproval(input);
      return this.createApproval({
        applicationRunId: input.applicationRunId,
        reviewRequestId: reviewRequest?.id ?? null,
        approvalType: input.approvalType,
        status: input.status,
        notes: input.notes ?? null
      });
    });

    return transaction();
  }

  createApproval(input: {
    applicationRunId: string;
    reviewRequestId?: string | null;
    approvalType: Approval["approvalType"];
    status: Approval["status"];
    notes?: string | null;
  }): Approval {
    const id = randomUUID();
    const now = nowIso();
    this.db
      .prepare(
        `
        INSERT INTO approvals (
          id, application_run_id, review_request_id, approval_type, status, decided_at, notes, created_at, updated_at
        )
        VALUES (
          @id, @applicationRunId, @reviewRequestId, @approvalType, @status, @decidedAt, @notes, @now, @now
        )
      `
      )
      .run({
        id,
        applicationRunId: input.applicationRunId,
        reviewRequestId: input.reviewRequestId ?? null,
        approvalType: input.approvalType,
        status: input.status,
        decidedAt: input.status === "APPROVED" || input.status === "REJECTED" ? now : null,
        notes: input.notes ?? null,
        now
      });

    const row = this.db.prepare("SELECT * FROM approvals WHERE id = ?").get(id) as {
      id: string;
      application_run_id: string;
      review_request_id: string | null;
      approval_type: string;
      status: string;
      decided_at: string | null;
      notes: string | null;
    };

    return ApprovalSchema.parse({
      id: row.id,
      applicationRunId: row.application_run_id,
      reviewRequestId: row.review_request_id,
      approvalType: row.approval_type,
      status: row.status,
      decidedAt: row.decided_at,
      notes: row.notes
    });
  }

  addGeneratedFile(input: Omit<GeneratedFile, "id" | "applicationRunId"> & { applicationRunId?: string | null }): GeneratedFile {
    const id = randomUUID();
    const now = nowIso();
    this.db
      .prepare(
        `
        INSERT INTO generated_files (
          id, application_run_id, tailoring_run_id, profile_id, job_target_id, file_kind, format, filename, local_path,
          sha256, size_bytes, upload_status, uploaded_at, retention_policy, delete_after,
          created_at, updated_at, deleted_at
        )
        VALUES (
          @id, @applicationRunId, @tailoringRunId, @profileId, @jobTargetId, @fileKind, @format, @filename, @localPath,
          @sha256, @sizeBytes, @uploadStatus, @uploadedAt, @retentionPolicy, @deleteAfter,
          @now, @now, @deletedAt
        )
      `
      )
      .run({
        id,
        applicationRunId: input.applicationRunId ?? null,
        tailoringRunId: input.tailoringRunId,
        profileId: input.profileId,
        jobTargetId: input.jobTargetId,
        fileKind: input.fileKind,
        format: input.format,
        filename: input.filename,
        localPath: input.localPath,
        sha256: input.sha256,
        sizeBytes: input.sizeBytes,
        uploadStatus: input.uploadStatus,
        uploadedAt: input.uploadedAt,
        retentionPolicy: input.retentionPolicy,
        deleteAfter: input.deleteAfter,
        deletedAt: input.deletedAt,
        now
      });

    return GeneratedFileSchema.parse({
      ...input,
      id
    });
  }

  listGeneratedFiles(applicationRunId: string): GeneratedFile[] {
    const rows = this.db
      .prepare(
        `
        SELECT generated_files.*
        FROM generated_files
        JOIN application_runs
          ON application_runs.id = @applicationRunId
         AND (
           generated_files.application_run_id = application_runs.id
           OR (
             -- Legacy rows only: files created before application_run_id existed.
             generated_files.application_run_id IS NULL
             AND (
               generated_files.tailoring_run_id = application_runs.tailoring_run_id
               OR (
                 generated_files.tailoring_run_id IS NULL
                 AND generated_files.profile_id = application_runs.profile_id
                 AND generated_files.job_target_id = application_runs.job_target_id
               )
             )
           )
         )
        WHERE generated_files.deleted_at IS NULL
        ORDER BY generated_files.created_at ASC
      `
      )
      .all({ applicationRunId }) as Array<{
      id: string;
      application_run_id: string | null;
      tailoring_run_id: string | null;
      profile_id: string;
      job_target_id: string;
      file_kind: string;
      format: string;
      filename: string;
      local_path: string;
      sha256: string | null;
      size_bytes: number | null;
      upload_status: string;
      uploaded_at: string | null;
      retention_policy: string;
      delete_after: string | null;
      deleted_at: string | null;
    }>;

    return rows.map((row) =>
      GeneratedFileSchema.parse({
        id: row.id,
        applicationRunId: row.application_run_id,
        tailoringRunId: row.tailoring_run_id,
        profileId: row.profile_id,
        jobTargetId: row.job_target_id,
        fileKind: row.file_kind,
        format: row.format,
        filename: row.filename,
        localPath: row.local_path,
        sha256: row.sha256,
        sizeBytes: row.size_bytes,
        uploadStatus: row.upload_status,
        uploadedAt: row.uploaded_at,
        retentionPolicy: row.retention_policy,
        deleteAfter: row.delete_after,
        deletedAt: row.deleted_at
      })
    );
  }

  listRecentGeneratedFiles(limit = 50): GeneratedFile[] {
    const rows = this.db
      .prepare(
        `
        SELECT *
        FROM generated_files
        WHERE deleted_at IS NULL
        ORDER BY created_at DESC
        LIMIT @limit
      `
      )
      .all({ limit }) as Array<{
      id: string;
      application_run_id: string | null;
      tailoring_run_id: string | null;
      profile_id: string;
      job_target_id: string;
      file_kind: string;
      format: string;
      filename: string;
      local_path: string;
      sha256: string | null;
      size_bytes: number | null;
      upload_status: string;
      uploaded_at: string | null;
      retention_policy: string;
      delete_after: string | null;
      deleted_at: string | null;
    }>;

    return rows.map((row) =>
      GeneratedFileSchema.parse({
        id: row.id,
        applicationRunId: row.application_run_id,
        tailoringRunId: row.tailoring_run_id,
        profileId: row.profile_id,
        jobTargetId: row.job_target_id,
        fileKind: row.file_kind,
        format: row.format,
        filename: row.filename,
        localPath: row.local_path,
        sha256: row.sha256,
        sizeBytes: row.size_bytes,
        uploadStatus: row.upload_status,
        uploadedAt: row.uploaded_at,
        retentionPolicy: row.retention_policy,
        deleteAfter: row.delete_after,
        deletedAt: row.deleted_at
      })
    );
  }

  listBrowserArtifacts(applicationRunId: string): BrowserArtifact[] {
    const rows = this.db
      .prepare("SELECT * FROM browser_artifacts WHERE application_run_id = ? AND deleted_at IS NULL ORDER BY created_at ASC")
      .all(applicationRunId) as Array<{
      id: string;
      application_run_id: string;
      artifact_type: string;
      local_path: string;
      metadata_json: string;
      created_at: string;
    }>;

    return rows.map((row) =>
      BrowserArtifactSchema.parse({
        id: row.id,
        applicationRunId: row.application_run_id,
        artifactType: row.artifact_type,
        localPath: row.local_path,
        metadata: parseJsonColumn(row.metadata_json, {}),
        createdAt: row.created_at
      })
    );
  }

  addRunEvent(input: Omit<RunEvent, "id">): RunEvent {
    const id = randomUUID();
    this.db
      .prepare(
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
      )
      .run({
        id,
        runId: input.runId,
        stepId: input.stepId,
        eventType: input.eventType,
        severity: input.severity,
        message: input.message,
        machineStateJson: stringifyJsonColumn(input.machineState),
        uiStateJson: stringifyJsonColumn(input.uiState),
        payloadJson: stringifyJsonColumn(input.payload),
        createdAt: input.timestamp
      });

    return RunEventSchema.parse({ ...input, id });
  }

  listRunEvents(applicationRunId: string, limit = 250): RunEvent[] {
    const rows = this.db
      .prepare("SELECT * FROM run_events WHERE application_run_id = ? ORDER BY created_at ASC LIMIT ?")
      .all(applicationRunId, limit) as Array<{
      id: string;
      application_run_id: string;
      step_id: string | null;
      event_type: string;
      severity: string;
      message: string;
      machine_state_json: string;
      ui_state_json: string;
      payload_json: string;
      created_at: string;
    }>;

    return rows.map((row) =>
      RunEventSchema.parse({
        id: row.id,
        eventType: row.event_type,
        runId: row.application_run_id,
        stepId: row.step_id,
        timestamp: row.created_at,
        severity: row.severity,
        message: row.message,
        machineState: parseJsonColumn(row.machine_state_json, {}),
        uiState: parseJsonColumn(row.ui_state_json, {}),
        payload: parseJsonColumn(row.payload_json, {})
      })
    );
  }
}
