import { describe, expect, it } from "vitest";
import { IpcContracts } from "./index";

describe("ipc contracts", () => {
  it("validates job enqueue requests", () => {
    const parsed = IpcContracts.jobsEnqueue.request.parse({
      profileId: "profile-1",
      items: [{ sourceKind: "URL", sourceValue: "https://example.com/job" }]
    });

    expect(parsed.items[0]!.sourceKind).toBe("URL");
  });

  it("rejects invalid theme preferences", () => {
    expect(() => IpcContracts.themeSetPreference.request.parse({ preference: "blue" })).toThrow();
  });

  it("validates run answer updates", () => {
    const parsed = IpcContracts.runsUpdateAnswer.request.parse({
      runId: "run-1",
      answerId: "answer-1",
      userValue: "Yes",
      status: "EDITED"
    });

    expect(parsed.status).toBe("EDITED");
    expect(() =>
      IpcContracts.runsUpdateAnswer.request.parse({
        runId: "run-1",
        answerId: "answer-1",
        userValue: "Yes",
        status: "APPROVED"
      })
    ).toThrow();
    expect(() =>
      IpcContracts.runsUpdateAnswer.request.parse({
        runId: "run-1",
        answerId: "answer-1",
        userValue: "Yes",
        status: "APPLIED"
      })
    ).toThrow();
  });

  it("validates canonical profile requests", () => {
    expect(IpcContracts.profileGetCanonical.request.parse({ profileId: "profile-1" }).profileId).toBe("profile-1");
    expect(IpcContracts.profileGetCanonical.response.parse(null)).toBeNull();
  });

  it("requires strong application credentials during starter profile setup", () => {
    const parsed = IpcContracts.profileCreateStarter.request.parse({
      legalName: "Ada Lovelace",
      email: "ada@example.com",
      applicationEmail: "ada@gmail.com",
      applicationPassword: "Str0ng!Pass12",
      gmailOtpEnabled: true
    });

    expect(parsed.gmailOtpEnabled).toBe(true);
    expect(() =>
      IpcContracts.profileCreateStarter.request.parse({
        legalName: "Ada Lovelace",
        applicationEmail: "ada@gmail.com",
        applicationPassword: "weak-password"
      })
    ).toThrow();
  });

  it("validates explicit approval types", () => {
    expect(
      IpcContracts.runsApprove.request.parse({
        runId: "run-1",
        approvalType: "DOCUMENT_APPROVAL"
      }).approvalType
    ).toBe("DOCUMENT_APPROVAL");
    expect(() => IpcContracts.runsApprove.request.parse({ runId: "run-1", approvalType: "DOCUMENT" })).toThrow();
  });

  it("validates skip-step control requests", () => {
    const parsed = IpcContracts.runsSkipStep.request.parse({ runId: "run-1", stepId: "step-1" });

    expect(parsed.stepId).toBe("step-1");
  });

  it("validates manual blocker review resolution requests", () => {
    const parsed = IpcContracts.runsResolveReview.request.parse({
      runId: "run-1",
      reviewRequestId: "review-1",
      status: "APPROVED",
      reason: "Challenge completed in the portal."
    });

    expect(parsed.status).toBe("APPROVED");
    expect(() =>
      IpcContracts.runsResolveReview.request.parse({
        runId: "run-1",
        reviewRequestId: "review-1",
        status: "OPEN"
      })
    ).toThrow();
  });

  it("validates parsed document list filters", () => {
    const parsed = IpcContracts.documentsListParsed.request.parse({ uploadedFileId: "upload-1" });

    expect(parsed.uploadedFileId).toBe("upload-1");
  });

  it("validates editable-master anchor repair requests", () => {
    const parsed = IpcContracts.documentsRepairEditableMasterAnchors.request.parse({ uploadedFileId: "upload-1" });

    expect(parsed.uploadedFileId).toBe("upload-1");
  });

  it("accepts absolute localPath values and rejects relative or null-byte paths", () => {
    const parse = (localPath: string) => IpcContracts.filesOpenLocalPath.request.parse({ localPath });

    expect(parse("C:\\Users\\someone\\file.docx").localPath).toBe("C:\\Users\\someone\\file.docx");
    expect(parse("/home/user/file.docx").localPath).toBe("/home/user/file.docx");

    expect(() => parse("..\\..\\secrets.txt")).toThrow();
    expect(() => parse("docs/resume.docx")).toThrow();
    expect(() => parse("/home/user/file\0.docx")).toThrow();
  });
});
