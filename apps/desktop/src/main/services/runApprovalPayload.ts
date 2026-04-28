import type { GeneratedFile, UploadedFile } from "@applyocalypse/db";

export type ControlDocumentFile = {
  id: string;
  fileKind: "RESUME" | "COVER_LETTER";
  format: string;
  filename: string;
  localPath: string;
  uploadStatus: string;
  source?: "GENERATED_FILE" | "UPLOADED_REVIEWED_ARTIFACT";
};

export const buildControlDocumentFiles = ({
  generatedFiles,
  uploadedFiles
}: {
  generatedFiles: GeneratedFile[];
  uploadedFiles: UploadedFile[];
}): ControlDocumentFile[] => {
  const generated = generatedFiles.map((file) => ({
    id: file.id,
    fileKind: file.fileKind,
    format: file.format,
    filename: file.filename,
    localPath: file.localPath,
    uploadStatus: file.uploadStatus,
    source: "GENERATED_FILE" as const
  }));

  const reviewedCoverLetterUploads = uploadedFiles
    .filter((file) => file.fileKind === "COVER_LETTER")
    .map((file) => ({
      id: file.id,
      fileKind: "COVER_LETTER" as const,
      format: file.sourceFormat,
      filename: file.originalName,
      localPath: file.localPath,
      uploadStatus: "NOT_UPLOADED",
      source: "UPLOADED_REVIEWED_ARTIFACT" as const
    }));

  return [...generated, ...reviewedCoverLetterUploads];
};
