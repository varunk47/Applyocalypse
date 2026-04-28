import { describe, expect, it } from "vitest";
import type { GeneratedFile, UploadedFile } from "@applyocalypse/db";

import { buildControlDocumentFiles } from "./runApprovalPayload";

const generatedFile = (overrides: Partial<GeneratedFile> = {}): GeneratedFile => ({
  id: "generated-resume",
  tailoringRunId: null,
  profileId: "profile-1",
  jobTargetId: "job-1",
  fileKind: "RESUME",
  format: "PDF",
  filename: "Ada Example Resume.pdf",
  localPath: "C:/Users/varun/Downloads/Ada Example Resume.pdf",
  sha256: null,
  sizeBytes: 512,
  uploadStatus: "NOT_UPLOADED",
  uploadedAt: null,
  retentionPolicy: "DELETE_AFTER_UPLOAD",
  deleteAfter: null,
  deletedAt: null,
  ...overrides
});

const uploadedFile = (overrides: Partial<UploadedFile> = {}): UploadedFile => ({
  id: "uploaded-cover-letter",
  profileId: "profile-1",
  fileKind: "COVER_LETTER",
  sourceFormat: "PDF",
  originalName: "Ada Example Cover Letter.pdf",
  localPath: "C:/Users/varun/Downloads/Ada Example Cover Letter.pdf",
  mimeType: "application/pdf",
  sizeBytes: 256,
  sha256: null,
  status: "UPLOADED",
  createdAt: "2026-04-27T10:00:00.000Z",
  updatedAt: "2026-04-27T10:00:00.000Z",
  ...overrides
});

describe("buildControlDocumentFiles", () => {
  it("includes generated files and reviewed cover-letter uploads", () => {
    const files = buildControlDocumentFiles({
      generatedFiles: [generatedFile()],
      uploadedFiles: [uploadedFile()]
    });

    expect(files).toEqual([
      expect.objectContaining({ id: "generated-resume", fileKind: "RESUME", source: "GENERATED_FILE" }),
      expect.objectContaining({
        id: "uploaded-cover-letter",
        fileKind: "COVER_LETTER",
        format: "PDF",
        uploadStatus: "NOT_UPLOADED",
        source: "UPLOADED_REVIEWED_ARTIFACT"
      })
    ]);
  });

  it("does not expose supporting details or other source uploads as automation files", () => {
    const files = buildControlDocumentFiles({
      generatedFiles: [],
      uploadedFiles: [
        uploadedFile({ id: "supporting-details", fileKind: "SUPPORTING_DETAILS", originalName: "projects.md", sourceFormat: "MD" }),
        uploadedFile({ id: "other", fileKind: "OTHER", originalName: "notes.txt", sourceFormat: "TXT" })
      ]
    });

    expect(files).toEqual([]);
  });
});
