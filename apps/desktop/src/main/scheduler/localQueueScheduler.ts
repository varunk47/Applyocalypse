import { join } from "node:path";
import { randomUUID } from "node:crypto";
import { mkdirSync, writeFileSync } from "node:fs";
import { app } from "electron";
import {
  JobRepository,
  ProfileRepository,
  ProviderRepository,
  RunRepository,
  SettingsRepository,
  type ApplyocalypseDatabase,
  type QueueItem,
  type QueueRepository
} from "@applyocalypse/db";
import { DEFAULT_MAX_CONCURRENT_APPLICATIONS, DEFAULT_QUEUE_LEASE_MS, HARD_MAX_CONCURRENT_APPLICATIONS } from "@applyocalypse/config";
import type { PythonWorkerSupervisor } from "../services/pythonWorkerSupervisor";
import { buildProviderRuntimeEnv } from "../services/providerRuntimeEnv";
import { SecureSecretStore } from "../services/secureSecretStore";

export type LocalQueueSchedulerOptions = {
  maxConcurrentApplications?: number;
  pollIntervalMs?: number;
};

export class LocalQueueScheduler {
  private timer: NodeJS.Timeout | null = null;
  private readonly defaultMaxConcurrentApplications: number;
  private readonly pollIntervalMs: number;
  private readonly workerId = `main-${process.pid}`;

  constructor(
    private readonly db: ApplyocalypseDatabase,
    private readonly queueRepository: QueueRepository,
    private readonly supervisor: PythonWorkerSupervisor,
    options: LocalQueueSchedulerOptions = {}
  ) {
    this.defaultMaxConcurrentApplications = Math.min(
      options.maxConcurrentApplications ?? DEFAULT_MAX_CONCURRENT_APPLICATIONS,
      HARD_MAX_CONCURRENT_APPLICATIONS
    );
    this.pollIntervalMs = options.pollIntervalMs ?? 3_000;
  }

  start(): void {
    if (this.timer) {
      return;
    }
    this.timer = setInterval(() => this.tick(), this.pollIntervalMs);
    this.tick();
  }

  stop(): void {
    if (this.timer) {
      clearInterval(this.timer);
      this.timer = null;
    }
  }

  tick(): void {
    try {
      this.queueRepository.recoverExpired();
      const runRepository = new RunRepository(this.db);
      runRepository.recoverStaleRuns();
      const item = this.queueRepository.claimNext(this.workerId, DEFAULT_QUEUE_LEASE_MS, this.configuredMaxConcurrentApplications());
      if (!item) {
        return;
      }
      this.startClaimedItem(item, runRepository);
    } catch (error) {
      this.persistSchedulerLoopError(error);
    }
  }

  private configuredMaxConcurrentApplications(): number {
    const value = new SettingsRepository(this.db).get(
      "automation.maxConcurrentApplications",
      this.defaultMaxConcurrentApplications
    );
    if (typeof value !== "number" || !Number.isInteger(value)) {
      return this.defaultMaxConcurrentApplications;
    }
    return Math.max(1, Math.min(HARD_MAX_CONCURRENT_APPLICATIONS, value));
  }

  private startClaimedItem(item: QueueItem, runRepository: RunRepository): void {
    const runId = randomUUID();
    const now = new Date().toISOString();
    try {
      this.db
        .prepare(
          `
          INSERT INTO application_runs (
            id, queue_item_id, profile_id, job_target_id, status, auto_submit_enabled, worker_id,
            lease_expires_at, heartbeat_at, started_at, created_at, updated_at
          )
          VALUES (
            @runId, @queueItemId, @profileId, @jobTargetId, 'PREPARING', @autoSubmitEnabled, @workerId,
            @leaseExpiresAt, @now, @now, @now, @now
          )
        `
        )
        .run({
          runId,
          queueItemId: item.id,
          profileId: item.profileId,
          jobTargetId: item.jobTargetId,
          autoSubmitEnabled: item.autoSubmitEnabled ? 1 : 0,
          workerId: this.workerId,
          leaseExpiresAt: new Date(Date.now() + DEFAULT_QUEUE_LEASE_MS).toISOString(),
          now
        });

      const runWorkDir = join(app.getPath("userData"), "runs", runId);
      mkdirSync(runWorkDir, { recursive: true });
      const jobTarget = new JobRepository(this.db).getTargetById(item.jobTargetId);
      const canonicalProfile = new ProfileRepository(this.db).getCanonicalProfile(item.profileId);
      const profileJsonFile = canonicalProfile ? join(runWorkDir, "canonical-profile.json") : undefined;
      if (profileJsonFile && canonicalProfile) {
        writeFileSync(profileJsonFile, JSON.stringify(canonicalProfile, null, 2), "utf8");
      }
      const jobTextFile = jobTarget.sourceKind === "TEXT" ? join(runWorkDir, "job-description.txt") : undefined;
      if (jobTextFile) {
        writeFileSync(jobTextFile, jobTarget.sourceValue, "utf8");
      }
      const jobMetadataFile = join(runWorkDir, "job-target.json");
      writeFileSync(
        jobMetadataFile,
        JSON.stringify(
          {
            id: jobTarget.id,
            sourceKind: jobTarget.sourceKind,
            company: jobTarget.company,
            role: jobTarget.role,
            location: jobTarget.location,
            portal: jobTarget.portal
          },
          null,
          2
        ),
        "utf8"
      );
      const outputDir = new SettingsRepository(this.db).get("files.outputDir", app.getPath("downloads"));
      const providerSecret = new ProviderRepository(this.db).getFirstConnectedSecretReference();
      let providerEnv: Record<string, string> | undefined;
      try {
        providerEnv = providerSecret
          ? buildProviderRuntimeEnv({
              provider: providerSecret.provider,
              apiKey: new SecureSecretStore().decryptSecret(providerSecret.encryptedReference),
              metadata: providerSecret.metadata
            })
          : undefined;
      } catch (error) {
        const message = error instanceof Error ? error.message : "Provider secret could not be loaded";
        runRepository.addRunEvent({
          eventType: "USER_REVIEW_REQUIRED",
          runId,
          stepId: null,
          timestamp: new Date().toISOString(),
          severity: "ERROR",
          message: "Provider connection needs attention before this run can continue",
          machineState: { reason: "PROVIDER_SECRET_UNAVAILABLE" },
          uiState: { requiresUserReview: true },
          payload: { provider: providerSecret?.provider, error: message }
        });
        runRepository.createReviewRequest({
          applicationRunId: runId,
          reviewType: "DOCUMENT",
          prompt: "Reconnect or update the selected AI provider key before continuing this application run.",
          payload: { provider: providerSecret?.provider ?? null }
        });
        runRepository.updateRunStatus({
          runId,
          status: "WAITING_FOR_USER_EDIT",
          failureCode: "PROVIDER_SECRET_UNAVAILABLE",
          failureMessage: "Provider secret could not be decrypted from secure local storage."
        });
        this.db
          .prepare("UPDATE queue_items SET status = 'WAITING_FOR_USER_EDIT', updated_at = @updatedAt WHERE id = @queueItemId")
          .run({ queueItemId: item.id, updatedAt: new Date().toISOString() });
        return;
      }
      this.supervisor.start({
        runId,
        ...(jobTarget.sourceKind === "URL" ? { jobUrl: jobTarget.sourceValue } : {}),
        ...(jobTextFile ? { jobTextFile } : {}),
        jobMetadataFile,
        ...(profileJsonFile ? { profileJsonFile } : {}),
        outputDir,
        ...(providerEnv ? { providerEnv } : {}),
        workDir: runWorkDir
      });
    } catch (error) {
      this.markRunPreparationFailed({ runId, queueItemId: item.id, error });
    }
  }

  private markRunPreparationFailed(input: { runId: string; queueItemId: string; error: unknown }): void {
    const message = input.error instanceof Error ? input.error.message : String(input.error);
    const now = new Date().toISOString();
    const runExists = this.db.prepare("SELECT 1 AS ok FROM application_runs WHERE id = ?").get(input.runId) as { ok: number } | undefined;
    const markFailed = this.db.transaction(() => {
      if (runExists) {
        new RunRepository(this.db).updateRunStatus({
          runId: input.runId,
          status: "FAILED",
          failureCode: "SCHEDULER_PREPARE_FAILED",
          failureMessage: message
        });
        new RunRepository(this.db).addRunEvent({
          eventType: "FAILED",
          runId: input.runId,
          stepId: null,
          timestamp: now,
          severity: "ERROR",
          message: "Scheduler could not prepare this run for automation",
          machineState: { reason: "SCHEDULER_PREPARE_FAILED" },
          uiState: { requires_user_review: true, current_step: "run_preparation" },
          payload: { error: message }
        });
      }
      this.db
        .prepare(
          `
          UPDATE queue_items
          SET status = 'FAILED',
              claimed_by = NULL,
              lease_expires_at = NULL,
              heartbeat_at = NULL,
              updated_at = @now
          WHERE id = @queueItemId
        `
        )
        .run({ queueItemId: input.queueItemId, now });
      this.db
        .prepare(
          `
          INSERT INTO audit_logs (id, actor, action, entity_type, entity_id, metadata_json, created_at)
          VALUES (
            lower(hex(randomblob(16))), 'electron_main', 'scheduler.run_prepare_failed',
            'application_run', @runId, @metadataJson, @now
          )
        `
        )
        .run({
          runId: input.runId,
          metadataJson: JSON.stringify({ queueItemId: input.queueItemId, error: message }),
          now
        });
    });
    markFailed();
  }

  private persistSchedulerLoopError(error: unknown): void {
    const message = error instanceof Error ? error.message : String(error);
    this.db
      .prepare(
        `
        INSERT INTO audit_logs (id, actor, action, entity_type, metadata_json, created_at)
        VALUES (
          lower(hex(randomblob(16))), 'electron_main', 'scheduler.tick_failed',
          'scheduler', @metadataJson, @now
        )
      `
      )
      .run({
        metadataJson: JSON.stringify({ error: message }),
        now: new Date().toISOString()
      });
  }
}
