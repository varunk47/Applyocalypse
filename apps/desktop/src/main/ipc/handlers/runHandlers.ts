import { IpcContracts } from "@applyocalypse/ipc-contracts";
import { buildControlDocumentFiles } from "../../services/runApprovalPayload";
import { writeWorkerControlFile } from "../../services/workerControlFile";
import { handleContract, type IpcHandlerContext } from "./context";
import { createRejectIfWorkerInactive, createUpdateRunAndQueueStatus } from "./runStatus";

export const registerRunHandlers = (ctx: IpcHandlerContext): void => {
  const { runRepository, uploadRepository, auditRepository, workerSupervisor } = ctx;
  const updateRunAndQueueStatus = createUpdateRunAndQueueStatus(ctx);
  const rejectIfWorkerInactive = createRejectIfWorkerInactive(ctx);

  handleContract(IpcContracts.runsPause, ({ runId }) => {
    writeWorkerControlFile({ runId, command: "PAUSE", reason: "local_user_pause" });
    return updateRunAndQueueStatus(runId, "PAUSED");
  });
  handleContract(IpcContracts.runsResume, ({ runId }) => {
    const inactive = rejectIfWorkerInactive(runId, "RESUME");
    if (inactive) {
      return inactive;
    }
    writeWorkerControlFile({ runId, command: "RESUME", reason: "local_user_resume" });
    return updateRunAndQueueStatus(runId, "RUNNING_AUTOMATION");
  });
  handleContract(IpcContracts.runsCancel, ({ runId }) => {
    writeWorkerControlFile({ runId, command: "CANCEL", reason: "local_user_cancel" });
    workerSupervisor.stop(runId);
    return updateRunAndQueueStatus(runId, "CANCELLED");
  });
  handleContract(IpcContracts.runsResolveReview, ({ runId, reviewRequestId, status, reason }) => {
    const reviewRequest = runRepository.listReviewRequests(runId).find((request) => request.id === reviewRequestId);
    if (!reviewRequest) {
      throw new Error("Review request was not found for this run");
    }
    if (!["CAPTCHA", "MFA", "OTP", "AMBIGUOUS_QUESTION", "LOGIN", "PORTAL_ENTRY", "PORTAL_STEP"].includes(reviewRequest.reviewType)) {
      throw new Error("This review type requires the explicit approval workflow");
    }
    if (reviewRequest.status !== "OPEN") {
      return { accepted: true };
    }

    if (status === "APPROVED") {
      const inactive = rejectIfWorkerInactive(runId, `RESOLVE_${reviewRequest.reviewType}`);
      if (inactive) {
        return inactive;
      }
    }

    runRepository.decideReview({
      reviewRequestId,
      status,
      notes: reason ?? null
    });
    auditRepository.append({
      action: status === "APPROVED" ? "review.manual_blocker_resolved" : "review.manual_blocker_rejected",
      entityType: "review_request",
      entityId: reviewRequestId,
      metadata: {
        runId,
        reviewType: reviewRequest.reviewType,
        reasonLength: reason?.length ?? 0
      }
    });

    if (status === "APPROVED") {
      writeWorkerControlFile({ runId, command: "RESUME", reason: `local_user_resolved_${reviewRequest.reviewType.toLowerCase()}` });
      return updateRunAndQueueStatus(runId, "RUNNING_AUTOMATION");
    }

    writeWorkerControlFile({ runId, command: "CANCEL", reason: reason ?? `local_user_rejected_${reviewRequest.reviewType.toLowerCase()}` });
    workerSupervisor.stop(runId);
    return updateRunAndQueueStatus(runId, "CANCELLED");
  });
  handleContract(IpcContracts.runsRetryStep, ({ runId, stepId }) => {
    const inactive = rejectIfWorkerInactive(runId, "RETRY_STEP");
    if (inactive) {
      return inactive;
    }
    writeWorkerControlFile({ runId, command: "RETRY_STEP", reason: "local_user_retry", stepId });
    runRepository.updateStepStatus({ applicationRunId: runId, stepId, status: "RETRYING" });
    return { accepted: true };
  });
  handleContract(IpcContracts.runsSkipStep, ({ runId, stepId }) => {
    const inactive = rejectIfWorkerInactive(runId, "SKIP_STEP");
    if (inactive) {
      return inactive;
    }
    writeWorkerControlFile({ runId, command: "SKIP_STEP", reason: "local_user_skip", stepId });
    runRepository.updateStepStatus({ applicationRunId: runId, stepId, status: "SKIPPED" });
    auditRepository.append({
      action: "run.step.skipped",
      entityType: "application_step",
      entityId: stepId,
      metadata: { runId }
    });
    return { accepted: true };
  });
  handleContract(IpcContracts.runsApprove, ({ runId, approvalType }) => {
    const inactive = rejectIfWorkerInactive(runId, approvalType);
    if (inactive) {
      return inactive;
    }
    if (approvalType === "ANSWER_EDIT") {
      runRepository.approvePendingAnswers(runId);
    }
    const applicationRun = runRepository.getApplicationRun(runId);
    const approvedAnswers = runRepository
      .listAnswers(runId)
      .filter((answer) => answer.status === "APPROVED")
      .map((answer) => ({
        answerId: answer.id,
        fieldLabel: answer.fieldLabel,
        fieldType: answer.fieldType,
        value: answer.userValue ?? answer.proposedValue,
        source: answer.source,
        confidence: answer.confidence,
        status: answer.status
      }))
      .filter((answer) => typeof answer.value === "string" && answer.value.length > 0);
    const generatedFiles = buildControlDocumentFiles({
      generatedFiles: runRepository.listGeneratedFiles(runId),
      uploadedFiles: uploadRepository.list(applicationRun.profileId)
    });
    writeWorkerControlFile({
      runId,
      command: "RESUME",
      reason: `local_user_approved_${approvalType.toLowerCase()}`,
      payload: {
        approvalType,
        autoSubmitEnabled: applicationRun.autoSubmitEnabled,
        approvedAnswers,
        generatedFiles
      }
    });
    runRepository.recordApprovalDecision({
      applicationRunId: runId,
      approvalType,
      status: "APPROVED"
    });
    auditRepository.append({
      action: "run.approved",
      entityType: "application_run",
      entityId: runId,
      metadata: { approvalType }
    });
    return { accepted: true };
  });
  handleContract(IpcContracts.runsReject, ({ runId, reason, approvalType }) => {
    const resolvedApprovalType = approvalType ?? "FINAL_SUBMIT";
    writeWorkerControlFile({ runId, command: "CANCEL", reason });
    if (resolvedApprovalType === "ANSWER_EDIT") {
      runRepository.rejectPendingAnswers(runId);
    }
    runRepository.recordApprovalDecision({
      applicationRunId: runId,
      approvalType: resolvedApprovalType,
      status: "REJECTED",
      notes: reason
    });
    workerSupervisor.stop(runId);
    auditRepository.append({
      action: "run.rejected",
      entityType: "application_run",
      entityId: runId,
      metadata: { reasonLength: reason.length, approvalType: resolvedApprovalType }
    });
    return updateRunAndQueueStatus(runId, "CANCELLED");
  });
};
