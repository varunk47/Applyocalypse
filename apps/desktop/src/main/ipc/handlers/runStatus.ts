import type { IpcHandlerContext } from "./context";

/**
 * Shared run-control helpers used by the run mutation handlers. Factories take
 * the handler context and return the closure with its original behavior.
 */
export const createUpdateRunAndQueueStatus =
  (ctx: IpcHandlerContext) =>
  (runId: string, status: "PAUSED" | "RUNNING_AUTOMATION" | "CANCELLED") => {
    const { db, runRepository, auditRepository } = ctx;
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

export const createRejectIfWorkerInactive =
  (ctx: IpcHandlerContext) =>
  (runId: string, action: string): { accepted: false; message: string } | null => {
    const { runRepository, auditRepository, workerSupervisor } = ctx;
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
