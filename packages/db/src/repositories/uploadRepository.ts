import type { Database } from "better-sqlite3";
import { createHash, randomUUID } from "node:crypto";
import { readFileSync, statSync } from "node:fs";
import { basename, extname, normalize } from "node:path";
import { UploadedFileSchema } from "@applyocalypse/shared-schemas";
import type { z } from "zod";

export type UploadedFile = z.infer<typeof UploadedFileSchema>;

const formatFromExtension = (path: string): UploadedFile["sourceFormat"] => {
  const ext = extname(path).toLowerCase();
  if (ext === ".pdf") return "PDF";
  if (ext === ".docx") return "DOCX";
  if (ext === ".tex") return "TEX";
  if (ext === ".md") return "MD";
  if (ext === ".txt") return "TXT";
  throw new Error(`Unsupported file extension: ${ext || "(none)"}`);
};

const mimeFromFormat = (format: UploadedFile["sourceFormat"]): string => {
  if (format === "PDF") return "application/pdf";
  if (format === "DOCX") return "application/vnd.openxmlformats-officedocument.wordprocessingml.document";
  if (format === "TEX") return "text/x-tex";
  if (format === "MD") return "text/markdown";
  return "text/plain";
};

const sha256ForFile = (localPath: string): string => createHash("sha256").update(readFileSync(localPath)).digest("hex");

export class UploadRepository {
  constructor(private readonly db: Database) {}

  list(profileId?: string | null): UploadedFile[] {
    const rows = (profileId
      ? this.db
          .prepare("SELECT id FROM uploaded_files WHERE profile_id = ? AND deleted_at IS NULL ORDER BY created_at DESC")
          .all(profileId)
      : this.db.prepare("SELECT id FROM uploaded_files WHERE deleted_at IS NULL ORDER BY created_at DESC").all()) as Array<{ id: string }>;
    return rows.map((row) => this.getById(row.id));
  }

  getById(id: string): UploadedFile {
    const row = this.db.prepare("SELECT * FROM uploaded_files WHERE id = ? AND deleted_at IS NULL").get(id) as
      | {
          id: string;
          profile_id: string | null;
          file_kind: string;
          source_format: string;
          original_name: string;
          local_path: string;
          mime_type: string | null;
          size_bytes: number;
          sha256: string | null;
          status: string;
          created_at: string;
          updated_at: string;
        }
      | undefined;
    if (!row) {
      throw new Error(`Uploaded file not found: ${id}`);
    }

    return UploadedFileSchema.parse({
      id: row.id,
      profileId: row.profile_id,
      fileKind: row.file_kind,
      sourceFormat: row.source_format,
      originalName: row.original_name,
      localPath: row.local_path,
      mimeType: row.mime_type,
      sizeBytes: row.size_bytes,
      sha256: row.sha256,
      status: row.status,
      createdAt: row.created_at,
      updatedAt: row.updated_at
    });
  }

  updateStatus(id: string, status: UploadedFile["status"]): UploadedFile {
    const now = new Date().toISOString();
    this.db.prepare("UPDATE uploaded_files SET status = ?, updated_at = ? WHERE id = ? AND deleted_at IS NULL").run(status, now, id);
    return this.getById(id);
  }

  /**
   * Claim uploads that were registered before any profile existed. Onboarding
   * asks for the resume first, so on a fresh install the very first upload lands
   * with a null profile_id and its parse would otherwise never merge into the
   * profile created moments later.
   */
  adoptOrphanedFiles(profileId: string): UploadedFile[] {
    const rows = this.db
      .prepare("SELECT id FROM uploaded_files WHERE profile_id IS NULL AND deleted_at IS NULL")
      .all() as Array<{ id: string }>;
    if (rows.length === 0) {
      return [];
    }
    const now = new Date().toISOString();
    this.db
      .prepare("UPDATE uploaded_files SET profile_id = ?, updated_at = ? WHERE profile_id IS NULL AND deleted_at IS NULL")
      .run(profileId, now);
    return rows.map((row) => this.getById(row.id));
  }

  registerLocalFile(input: {
    profileId: string | null;
    localPath: string;
    fileKind: UploadedFile["fileKind"];
    status?: UploadedFile["status"];
    parentFileId?: string | null;
  }): UploadedFile {
    const normalizedPath = normalize(input.localPath);
    const stats = statSync(normalizedPath);
    if (!stats.isFile()) {
      throw new Error("Upload path must point to a file");
    }

    const sourceFormat = formatFromExtension(normalizedPath);
    const now = new Date().toISOString();
    const uploadedFile = UploadedFileSchema.parse({
      id: randomUUID(),
      profileId: input.profileId,
      fileKind: input.fileKind,
      sourceFormat,
      originalName: basename(normalizedPath),
      localPath: normalizedPath,
      mimeType: mimeFromFormat(sourceFormat),
      sizeBytes: stats.size,
      sha256: sha256ForFile(normalizedPath),
      status: input.status ?? (sourceFormat === "PDF" ? "IMMUTABLE_SOURCE" : "UPLOADED"),
      createdAt: now,
      updatedAt: now
    });

    this.db
      .prepare(
        `
        INSERT INTO uploaded_files (
          id, profile_id, file_kind, source_format, original_name, local_path,
          mime_type, size_bytes, sha256, status, parent_file_id, created_at, updated_at
        )
        VALUES (
          @id, @profileId, @fileKind, @sourceFormat, @originalName, @localPath,
          @mimeType, @sizeBytes, @sha256, @status, @parentFileId, @createdAt, @updatedAt
        )
      `
      )
      .run({
        ...uploadedFile,
        profileId: uploadedFile.profileId,
        fileKind: uploadedFile.fileKind,
        sourceFormat: uploadedFile.sourceFormat,
        originalName: uploadedFile.originalName,
        localPath: uploadedFile.localPath,
        mimeType: uploadedFile.mimeType,
        sizeBytes: uploadedFile.sizeBytes,
        parentFileId: input.parentFileId ?? null,
        createdAt: uploadedFile.createdAt,
        updatedAt: uploadedFile.updatedAt
      });

    return uploadedFile;
  }
}
