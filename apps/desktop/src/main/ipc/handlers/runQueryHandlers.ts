import { IpcContracts } from "@applyocalypse/ipc-contracts";
import { ScreenshotSchema } from "@applyocalypse/shared-schemas";
import { handleContract, type IpcHandlerContext } from "./context";

export const registerRunQueryHandlers = (ctx: IpcHandlerContext): void => {
  const { db, runRepository } = ctx;

  handleContract(IpcContracts.runsList, ({ limit, offset }) => ({
    items: runRepository.listApplicationRuns(limit, offset),
    total: runRepository.countApplicationRuns()
  }));
  handleContract(IpcContracts.runsGetDetail, ({ runId }) => ({
    run: runRepository.getApplicationRun(runId),
    steps: runRepository.listSteps(runId),
    answers: runRepository.listAnswers(runId),
    reviewRequests: runRepository.listReviewRequests(runId),
    generatedFiles: runRepository.listGeneratedFiles(runId),
    browserArtifacts: runRepository.listBrowserArtifacts(runId),
    events: runRepository.listRunEvents(runId)
  }));
  handleContract(IpcContracts.runsListAnswers, ({ runId }) => ({ items: runRepository.listAnswers(runId) }));
  handleContract(IpcContracts.runsUpdateAnswer, ({ runId, answerId, userValue, status }) =>
    runRepository.updateAnswerValue({ applicationRunId: runId, answerId, userValue, status })
  );
  handleContract(IpcContracts.runsListReviewRequests, ({ runId }) => ({ items: runRepository.listReviewRequests(runId) }));

  handleContract(IpcContracts.logsSubscribe, () => ({ subscribed: true }));

  handleContract(IpcContracts.screenshotsList, ({ runId }) => {
    const rows = db.prepare("SELECT * FROM screenshots WHERE application_run_id = ? ORDER BY captured_at ASC").all(runId) as Array<{
      id: string;
      application_run_id: string;
      step_id: string | null;
      screenshot_id: string;
      local_path: string;
      mime_type: string;
      width: number;
      height: number;
      sha256: string | null;
      captured_at: string;
    }>;

    return {
      items: rows.map((row) =>
        ScreenshotSchema.parse({
          id: row.id,
          applicationRunId: row.application_run_id,
          stepId: row.step_id,
          screenshotId: row.screenshot_id,
          localPath: row.local_path,
          mimeType: row.mime_type,
          width: row.width,
          height: row.height,
          sha256: row.sha256,
          capturedAt: row.captured_at
        })
      )
    };
  });
};
