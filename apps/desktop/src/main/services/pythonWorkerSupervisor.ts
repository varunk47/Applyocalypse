import { spawn, type ChildProcessWithoutNullStreams } from "node:child_process";
import { rmSync } from "node:fs";
import { join } from "node:path";
import { createInterface } from "node:readline";
import type { BrowserWindow } from "electron";
import { DEFAULT_QUEUE_LEASE_MS } from "@applyocalypse/config";
import type { ApplyocalypseDatabase } from "@applyocalypse/db";
import { IpcChannels } from "@applyocalypse/ipc-contracts";
import { SafeRendererRunEventSchema } from "@applyocalypse/shared-schemas";
import { ingestPythonEventLine } from "./pythonEventIngest";
import { resolvePythonWorkerLaunch } from "./pythonWorkerPaths";
import { redactSensitiveSupervisorText } from "./sensitiveRedaction";

export type StartWorkerInput = {
  runId: string;
  jobUrl?: string;
  jobTextFile?: string;
  jobMetadataFile?: string;
  profileJsonFile?: string;
  coverLetterSampleFile?: string;
  outputDir?: string;
  providerEnv?: Record<string, string>;
  workDir: string;
};

type ActiveWorker = {
  child: ChildProcessWithoutNullStreams;
  heartbeat: NodeJS.Timeout;
  stopping: boolean;
};

const terminalRunStatuses = new Set(["COMPLETED", "FAILED", "CANCELLED", "SUBMITTED"]);

export class PythonWorkerSupervisor {
  private readonly active = new Map<string, ActiveWorker>();

  constructor(
    private readonly db: ApplyocalypseDatabase,
    private readonly windows: () => BrowserWindow[],
    private readonly safeArtifactRoots: () => string[] = () => []
  ) {}

  start(input: StartWorkerInput): void {
    if (this.active.has(input.runId)) {
      throw new Error(`Worker already active for run: ${input.runId}`);
    }

    const launch = resolvePythonWorkerLaunch();
    const args = [
      ...launch.baseArgs,
      "--run-id",
      input.runId,
      "--work-dir",
      input.workDir,
      ...(input.jobUrl ? ["--job-url", input.jobUrl] : []),
      ...(input.jobTextFile ? ["--job-text-file", input.jobTextFile] : []),
      ...(input.jobMetadataFile ? ["--job-metadata-file", input.jobMetadataFile] : []),
      ...(input.profileJsonFile ? ["--profile-json-file", input.profileJsonFile] : []),
      ...(input.coverLetterSampleFile ? ["--cover-letter-sample-file", input.coverLetterSampleFile] : []),
      ...(input.outputDir ? ["--output-dir", input.outputDir] : [])
    ];

    const providerEnv = input.providerEnv ?? {};
    const child = spawn(launch.executable, args, {
      cwd: launch.cwd,
      env: { ...process.env, APPLYO_WORKER_WAIT_FOR_REVIEW: "1", ...providerEnv },
      shell: false,
      windowsHide: true
    });

    const heartbeat = setInterval(() => this.refreshLease(input.runId), Math.min(30_000, Math.floor(DEFAULT_QUEUE_LEASE_MS / 3)));
    this.active.set(input.runId, { child, heartbeat, stopping: false });
    this.refreshLease(input.runId);

    const stdout = createInterface({ input: child.stdout });
    stdout.on("line", (line) => {
      if (!line.trim().startsWith("{")) return;
      try {
        ingestPythonEventLine({ db: this.db, windows: this.windows, rawLine: line, safeArtifactRoots: this.safeArtifactRoots() });
      } catch (error) {
        this.persistSupervisorError(input.runId, error, (message) => redactSensitiveSupervisorText(message, providerEnv));
      }
    });

    child.stderr.on("data", (chunk: Buffer) => {
      this.persistSupervisorError(input.runId, new Error(chunk.toString("utf8")), (message) => redactSensitiveSupervisorText(message, providerEnv));
    });

    child.on("exit", (code: number | null, signal: NodeJS.Signals | null) => {
      const activeWorker = this.active.get(input.runId);
      clearInterval(activeWorker?.heartbeat ?? heartbeat);
      this.active.delete(input.runId);
      try {
        rmSync(join(input.workDir, "gmail-oauth-token.json"), { force: true });
      } catch {
        // best-effort: never let cleanup failure mask the exit handling
      }
      if (!activeWorker?.stopping) {
        this.pauseRunAfterUnexpectedWorkerExit(input.runId, code, signal);
      }
    });
  }

  stop(runId: string): boolean {
    const active = this.active.get(runId);
    if (!active) {
      return false;
    }
    clearInterval(active.heartbeat);
    this.active.set(runId, { ...active, stopping: true });
    active.child.kill();
    return true;
  }

  isActive(runId: string): boolean {
    return this.active.has(runId);
  }

  private refreshLease(runId: string): void {
    const now = Date.now();
    const heartbeatAt = new Date(now).toISOString();
    const leaseExpiresAt = new Date(now + DEFAULT_QUEUE_LEASE_MS).toISOString();
    this.db
      .prepare(
        `
        UPDATE application_runs
        SET heartbeat_at = @heartbeatAt,
            lease_expires_at = @leaseExpiresAt,
            updated_at = @heartbeatAt
        WHERE id = @runId
          AND status NOT IN ('COMPLETED','FAILED','CANCELLED','SUBMITTED')
      `
      )
      .run({ runId, heartbeatAt, leaseExpiresAt });
    this.db
      .prepare(
        `
        UPDATE queue_items
        SET heartbeat_at = @heartbeatAt,
            lease_expires_at = @leaseExpiresAt,
            updated_at = @heartbeatAt
        WHERE id = (SELECT queue_item_id FROM application_runs WHERE id = @runId)
          AND status NOT IN ('COMPLETED','FAILED','CANCELLED','SUBMITTED')
      `
      )
      .run({ runId, heartbeatAt, leaseExpiresAt });
  }

  private persistSupervisorError(runId: string, error: unknown, redact: (message: string) => string = (message) => message): void {
    const rawMessage = error instanceof Error ? error.message : String(error);
    const message = redact(rawMessage);
    this.db.prepare(
      `
      INSERT INTO run_events (
        id, application_run_id, step_id, event_type, severity, message,
        machine_state_json, ui_state_json, payload_json, created_at
      )
      VALUES (lower(hex(randomblob(16))), @runId, NULL, 'FAILED', 'ERROR', @message, '{}', '{}', '{}', @createdAt)
    `
    ).run({
      runId,
      message,
      createdAt: new Date().toISOString()
    });
  }

  private pauseRunAfterUnexpectedWorkerExit(runId: string, code: number | null, signal: NodeJS.Signals | null): void {
    const timestamp = new Date().toISOString();
    const failureCode = code === 0 && signal === null ? "WORKER_EXITED_WITHOUT_TERMINAL_EVENT" : "WORKER_EXITED_UNEXPECTEDLY";
    const exitDescription = signal ? `signal ${signal}` : `exit code ${code ?? "unknown"}`;
    const message =
      failureCode === "WORKER_EXITED_WITHOUT_TERMINAL_EVENT"
        ? "Automation worker exited before emitting a terminal event. Run paused for inspection."
        : `Automation worker exited unexpectedly with ${exitDescription}. Run paused for inspection.`;

    const event = this.db.transaction(() => {
      const run = this.db.prepare("SELECT status FROM application_runs WHERE id = ?").get(runId) as { status: string } | undefined;
      if (!run || terminalRunStatuses.has(run.status)) {
        return null;
      }

      this.db
        .prepare(
          `
          UPDATE application_runs
          SET status = 'PAUSED',
              worker_id = NULL,
              lease_expires_at = NULL,
              heartbeat_at = NULL,
              failure_code = @failureCode,
              failure_message = @message,
              updated_at = @timestamp
          WHERE id = @runId
        `
        )
        .run({ runId, failureCode, message, timestamp });

      this.db
        .prepare(
          `
          UPDATE queue_items
          SET status = 'PAUSED',
              claimed_by = NULL,
              lease_expires_at = NULL,
              heartbeat_at = NULL,
              updated_at = @timestamp
          WHERE id = (SELECT queue_item_id FROM application_runs WHERE id = @runId)
            AND status NOT IN ('COMPLETED','FAILED','CANCELLED','SUBMITTED')
        `
        )
        .run({ runId, timestamp });

      const payload = { code, signal, failure_code: failureCode };
      this.db
        .prepare(
          `
          INSERT INTO run_events (
            id, application_run_id, step_id, event_type, severity, message,
            machine_state_json, ui_state_json, payload_json, created_at
          )
          VALUES (
            lower(hex(randomblob(16))), @runId, NULL, 'PAUSED', 'ERROR', @message,
            @machineStateJson, @uiStateJson, @payloadJson, @timestamp
          )
        `
        )
        .run({
          runId,
          message,
          machineStateJson: JSON.stringify({ reason: failureCode }),
          uiStateJson: JSON.stringify({ requires_user_review: true, current_step: "worker_exit" }),
          payloadJson: JSON.stringify(payload),
          timestamp
        });

      this.db
        .prepare(
          `
          INSERT INTO audit_logs (id, actor, action, entity_type, entity_id, metadata_json, created_at)
          VALUES (
            lower(hex(randomblob(16))), 'electron_main', 'run.worker_exit.paused',
            'application_run', @runId, @metadataJson, @timestamp
          )
        `
        )
        .run({
          runId,
          metadataJson: JSON.stringify(payload),
          timestamp
        });

      return SafeRendererRunEventSchema.parse({
        eventType: "PAUSED",
        runId,
        stepId: null,
        timestamp,
        severity: "ERROR",
        message,
        uiState: { requires_user_review: true, current_step: "worker_exit" },
        payload
      });
    })();

    if (!event) {
      return;
    }

    for (const window of this.windows()) {
      if (!window.isDestroyed()) {
        window.webContents.send(IpcChannels.logsEvent, event);
      }
    }
  }
}
