import { mkdirSync, renameSync, writeFileSync } from "node:fs";
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
  const stagingPath = `${controlPath}.tmp`;
  writeFileSync(
    stagingPath,
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
    // Approved answers can carry applicant PII; match worker-secrets.json permissions.
    { encoding: "utf8", mode: 0o600 }
  );
  // Swap into place atomically so the worker's poll never reads a torn file. Windows
  // can briefly deny the swap while the worker holds the old file open for reading.
  for (let attempt = 0; ; attempt += 1) {
    try {
      renameSync(stagingPath, controlPath);
      break;
    } catch (error) {
      if (attempt >= 4) {
        throw error;
      }
      const retryAt = Date.now() + 10;
      while (Date.now() < retryAt) {
        // brief synchronous backoff; the worker's read window is microseconds
      }
    }
  }
  return controlPath;
};
