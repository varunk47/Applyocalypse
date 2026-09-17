import { IpcContracts } from "@applyocalypse/ipc-contracts";
import { RunEventSchema } from "@applyocalypse/shared-schemas";
import { profileReadiness } from "@applyocalypse/shared-types";
import { handleContract, lookupJobTargets, type IpcHandlerContext } from "./context";

const parseJson = <T>(value: string, fallback: T): T => {
  try {
    return JSON.parse(value) as T;
  } catch {
    return fallback;
  }
};

export const registerJobQueueHandlers = (ctx: IpcHandlerContext): void => {
  const { db, jobRepository, profileRepository, queueRepository } = ctx;

  handleContract(IpcContracts.jobsEnqueue, ({ profileId, items }) => {
    // The renderer greys out the paste box for the same reason, but the queue is
    // the actual door: a run enqueued against a profile that cannot carry it gets
    // as far as the browser before anyone finds out.
    const readiness = profileReadiness(profileRepository.getCanonicalProfile(profileId));
    if (!readiness.isReady) {
      throw new Error(`This profile is not ready to apply yet. Still needed: ${readiness.gaps.map((gap) => gap.label).join(", ")}.`);
    }
    return jobRepository.enqueueTargets({ profileId, items });
  });

  handleContract(IpcContracts.jobsList, ({ limit, offset }) => {
    const items = queueRepository.list(limit, offset);
    return {
      items,
      total: queueRepository.count(),
      jobTargets: lookupJobTargets(jobRepository, items.map((item) => item.jobTargetId))
    };
  });

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
};
