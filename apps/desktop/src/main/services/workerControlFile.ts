import { mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { app } from "electron";

export type WorkerControlCommand = "PAUSE" | "RESUME" | "CANCEL" | "RETRY_STEP" | "SKIP_STEP";

export const writeWorkerControlFile = (input: {
  runId: string;
  command: WorkerControlCommand;
  reason?: string;
  stepId?: string | null;
  payload?: Record<string, unknown>;
}): string => {
  const runDir = join(app.getPath("userData"), "runs", input.runId);
  mkdirSync(runDir, { recursive: true });
  const controlPath = join(runDir, "control.json");
  writeFileSync(
    controlPath,
    `${JSON.stringify(
      {
        command: input.command,
        reason: input.reason ?? null,
        step_id: input.stepId ?? null,
        payload: input.payload ?? {},
        written_at: new Date().toISOString()
      },
      null,
      2
    )}\n`,
    "utf8"
  );
  return controlPath;
};
