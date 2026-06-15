import { join } from "node:path";
import { randomUUID } from "node:crypto";
import { mkdirSync, writeFileSync } from "node:fs";
import { app } from "electron";
import { GmailOAuthService } from "../services/gmailOAuthService";
import { getLatestCoverLetterText } from "../services/documentIngestionService";
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
      const profileRepository = new ProfileRepository(this.db);
      const providerRepository = new ProviderRepository(this.db);
      const secureSecretStore = new SecureSecretStore();
      const canonicalProfile = profileRepository.getCanonicalProfile(item.profileId);
      const profileJsonFile = canonicalProfile ? join(runWorkDir, "canonical-profile.json") : undefined;
      if (profileJsonFile && canonicalProfile) {
        writeFileSync(profileJsonFile, JSON.stringify(canonicalProfile, null, 2), "utf8");
      }
      const jobTextFile = jobTarget.sourceKind === "TEXT" ? join(runWorkDir, "job-description.txt") : undefined;
      if (jobTextFile) {
        writeFileSync(jobTextFile, jobTarget.sourceValue, "utf8");
      }
      const coverLetterText = getLatestCoverLetterText(this.db, item.profileId);
      const coverLetterSampleFile = coverLetterText ? join(runWorkDir, "cover-letter-sample.txt") : undefined;
      if (coverLetterSampleFile && coverLetterText) {
        writeFileSync(coverLetterSampleFile, coverLetterText, "utf8");
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
      const providerSecret = providerRepository.getFirstConnectedSecretReference();
      let providerEnv: Record<string, string> | undefined;
      let secretsForRedaction: Record<string, string> | undefined;
      try {
        providerEnv = providerSecret
          ? buildProviderRuntimeEnv({
              provider: providerSecret.provider,
              apiKey: secureSecretStore.decryptSecret(providerSecret.encryptedReference),
              metadata: providerSecret.metadata
            })
          : undefined;

        const credentials = profileRepository.getApplicationCredentialReference(item.profileId);
        if (credentials?.applicationEmail && credentials.encryptedReference) {
          const applicationPassword = secureSecretStore.decryptSecret(credentials.encryptedReference);
          const secretPayload: Record<string, string> = {
            APPLYO_APPLICATION_PASSWORD: applicationPassword
          };
          providerEnv = {
            ...(providerEnv ?? {}),
            APPLYO_APPLICATION_EMAIL: credentials.applicationEmail
          };

          if (credentials.otpHandlingEnabled) {
            // OAuth token path (preferred over IMAP app password)
            const gmailSettingsRepository = new SettingsRepository(this.db);
            const gmailOAuthService = new GmailOAuthService(gmailSettingsRepository);
            const oauthTokenJson = gmailOAuthService.getDecryptedTokenJson();
            if (oauthTokenJson) {
              const tokenFilePath = join(runWorkDir, "gmail-oauth-token.json");
              writeFileSync(tokenFilePath, oauthTokenJson, { encoding: "utf8", mode: 0o600 });
              providerEnv = {
                ...providerEnv,
                APPLYO_GMAIL_OAUTH_TOKEN_PATH: tokenFilePath
              };
            } else {
              // IMAP app password fallback
              const otpSecret =
                credentials.otpProviderConnectionId !== null
                  ? providerRepository.getConnectedSecretReferenceById(credentials.otpProviderConnectionId)
                  : null;
              const otpPassword =
                otpSecret?.provider === "gmail"
                  ? secureSecretStore.decryptSecret(otpSecret.encryptedReference)
                  : applicationPassword;
              secretPayload.APPLYO_GMAIL_OTP_PASSWORD = otpPassword;
              providerEnv = {
                ...providerEnv,
                APPLYO_GMAIL_OTP_ENABLED: "1",
                APPLYO_GMAIL_OTP_EMAIL: credentials.applicationEmail
              };
            }
          }

          const secretsFilePath = join(runWorkDir, "worker-secrets.json");
          writeFileSync(secretsFilePath, JSON.stringify(secretPayload), { encoding: "utf8", mode: 0o600 });
          providerEnv = { ...providerEnv, APPLYO_SECRETS_FILE: secretsFilePath };
          secretsForRedaction = secretPayload;
        }
      } catch (error) {
        const message = error instanceof Error ? error.message : "Sensitive local credential could not be loaded";
        runRepository.addRunEvent({
          eventType: "USER_REVIEW_REQUIRED",
          runId,
          stepId: null,
          timestamp: new Date().toISOString(),
          severity: "ERROR",
          message: "A saved local credential needs attention before this run can continue",
          machineState: { reason: "LOCAL_CREDENTIAL_UNAVAILABLE" },
          uiState: { requiresUserReview: true },
          payload: { provider: providerSecret?.provider, error: message }
        });
        runRepository.createReviewRequest({
          applicationRunId: runId,
          reviewType: "DOCUMENT",
          prompt: "Reconnect or update the saved provider/profile credential before continuing this application run.",
          payload: { provider: providerSecret?.provider ?? null }
        });
        runRepository.updateRunStatus({
          runId,
          status: "WAITING_FOR_USER_EDIT",
          failureCode: "LOCAL_CREDENTIAL_UNAVAILABLE",
          failureMessage: "Saved local credential could not be decrypted from secure local storage."
        });
        this.db
          .prepare("UPDATE queue_items SET status = 'WAITING_FOR_USER_EDIT', updated_at = @updatedAt WHERE id = @queueItemId")
          .run({ queueItemId: item.id, updatedAt: new Date().toISOString() });
        return;
      }
      const autofillDefaults = new SettingsRepository(this.db).get<boolean>("automation.autofillApprovedDefaults", false);
      if (autofillDefaults === true) {
        providerEnv = { ...(providerEnv ?? {}), APPLYO_AUTOFILL_APPROVED_DEFAULTS: "1" };
      }
      this.supervisor.start({
        runId,
        ...(jobTarget.sourceKind === "URL" ? { jobUrl: jobTarget.sourceValue } : {}),
        ...(jobTextFile ? { jobTextFile } : {}),
        jobMetadataFile,
        ...(profileJsonFile ? { profileJsonFile } : {}),
        ...(coverLetterSampleFile ? { coverLetterSampleFile } : {}),
        outputDir,
        ...(providerEnv ? { providerEnv } : {}),
        ...(secretsForRedaction ? { secretsForRedaction } : {}),
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
