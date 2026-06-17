import { IpcContracts } from "@applyocalypse/ipc-contracts";
import { RunEventSchema } from "@applyocalypse/shared-schemas";
import { handleContract, type IpcHandlerContext } from "./context";

const parseJson = <T>(value: string, fallback: T): T => {
  try {
    return JSON.parse(value) as T;
  } catch {
    return fallback;
  }
};

export const registerJobQueueHandlers = (ctx: IpcHandlerContext): void => {
  const { db, jobRepository, queueRepository } = ctx;

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
};
