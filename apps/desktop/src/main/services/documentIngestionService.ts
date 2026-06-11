import { spawn } from "node:child_process";
import { randomUUID } from "node:crypto";
import { copyFileSync, mkdirSync, statSync } from "node:fs";
import { basename, extname, join } from "node:path";
import { app } from "electron";
import { ParsedDocumentRepository, type ApplyocalypseDatabase, type ParsedDocumentMergeSummary, type UploadRepository, type UploadedFile } from "@applyocalypse/db";
import { ParsedDocumentCanonicalSchema, ParsedDocumentMergeSummarySchema } from "@applyocalypse/shared-schemas";
import { resolvePythonWorkerLaunch } from "./pythonWorkerPaths";

type PdfConversionResult = {
  original_pdf_path: string;
  candidate_docx_path: string;
  editable_master_status: string;
  user_message: string;
};

export type SourceCustodyInput = {
  localPath: string;
  profileId: string | null;
  fileKind: UploadedFile["fileKind"];
  rootDir: string;
};

const sanitizeSourceFilename = (filename: string): string => {
  const sanitized = filename.replace(/[<>:"/\\|?*\u0000-\u001f]/g, "_").replace(/\s+/g, " ").trim();
  return sanitized || "source-material";
};

export const copySourceIntoCustody = (input: SourceCustodyInput): string => {
  const stats = statSync(input.localPath);
  if (!stats.isFile()) {
    throw new Error("Source material path must point to a file");
  }

  const custodyDir = join(input.rootDir, input.profileId ?? "unassigned", input.fileKind.toLowerCase(), randomUUID());
  mkdirSync(custodyDir, { recursive: true });
  const custodyPath = join(custodyDir, sanitizeSourceFilename(basename(input.localPath)));
  copyFileSync(input.localPath, custodyPath);
  return custodyPath;
};

export type ResumeIngestionResult = {
  sourceFile: UploadedFile;
  editableMasterCandidate: UploadedFile | null;
  parsing: ParsedDocumentMergeSummary | null;
  requiresUserVerification: boolean;
  userMessage: string;
};

export type SourceMaterialIngestionResult = {
  uploadedFile: UploadedFile;
  parsing: ParsedDocumentMergeSummary | null;
};

export type EditableMasterAnchorRepairResult = {
  anchoredCandidate: UploadedFile;
  parsing: ParsedDocumentMergeSummary | null;
  addedPlaceholders: string[];
  alreadyPresentPlaceholders: string[];
  warnings: string[];
  userMessage: string;
};

const runPdfConversion = async (sourcePath: string, outputDir: string): Promise<PdfConversionResult> => {
  const launch = resolvePythonWorkerLaunch();
  const args = [...launch.baseArgs, "pdf-ingestion", "--source", sourcePath, "--output-dir", outputDir];

  return new Promise((resolve, reject) => {
    const child = spawn(launch.executable, args, {
      cwd: launch.cwd,
      env: process.env,
      shell: false,
      windowsHide: true
    });

    let stdout = "";
    let stderr = "";

    child.stdout.on("data", (chunk: Buffer) => {
      stdout += chunk.toString("utf8");
    });
    child.stderr.on("data", (chunk: Buffer) => {
      stderr += chunk.toString("utf8");
    });
    child.on("error", reject);
    child.on("exit", (code) => {
      if (code !== 0) {
        reject(new Error(stderr || `PDF conversion exited with code ${code ?? "unknown"}`));
        return;
      }
      try {
        resolve(JSON.parse(stdout) as PdfConversionResult);
      } catch (error) {
        reject(error);
      }
    });
  });
};

type ParseSourceResult = {
  parser_name: string;
  parser_version: string;
  confidence: number;
  canonical: unknown;
  style_map: Record<string, unknown>;
  anchor_map: Record<string, unknown>;
  warnings: string[];
};

const runDocumentParse = async (sourcePath: string, documentKind: UploadedFile["fileKind"]): Promise<ParseSourceResult> => {
  const launch = resolvePythonWorkerLaunch();
  const args = [...launch.baseArgs, "pipeline", "parse-source", "--source", sourcePath, "--document-kind", documentKind];

  return new Promise((resolve, reject) => {
    const child = spawn(launch.executable, args, {
      cwd: launch.cwd,
      env: process.env,
      shell: false,
      windowsHide: true
    });

    let stdout = "";
    let stderr = "";

    child.stdout.on("data", (chunk: Buffer) => {
      stdout += chunk.toString("utf8");
    });
    child.stderr.on("data", (chunk: Buffer) => {
      stderr += chunk.toString("utf8");
    });
    child.on("error", reject);
    child.on("exit", (code) => {
      if (code !== 0) {
        reject(new Error(stderr || `Document parser exited with code ${code ?? "unknown"}`));
        return;
      }
      try {
        resolve(JSON.parse(stdout) as ParseSourceResult);
      } catch (error) {
        reject(error);
      }
    });
  });
};

type AnchorRepairCliResult = {
  source_path: string;
  output_path: string;
  source_format: string;
  added_placeholders: string[];
  already_present_placeholders: string[];
  warnings: string[];
};

const runAnchorRepair = async (sourcePath: string, outputPath: string): Promise<AnchorRepairCliResult> => {
  const launch = resolvePythonWorkerLaunch();
  const args = [...launch.baseArgs, "pipeline", "repair-anchors", "--source", sourcePath, "--output", outputPath];

  return new Promise((resolve, reject) => {
    const child = spawn(launch.executable, args, {
      cwd: launch.cwd,
      env: process.env,
      shell: false,
      windowsHide: true
    });

    let stdout = "";
    let stderr = "";

    child.stdout.on("data", (chunk: Buffer) => {
      stdout += chunk.toString("utf8");
    });
    child.stderr.on("data", (chunk: Buffer) => {
      stderr += chunk.toString("utf8");
    });
    child.on("error", reject);
    child.on("exit", (code) => {
      if (code !== 0) {
        reject(new Error(stderr || `Anchor repair exited with code ${code ?? "unknown"}`));
        return;
      }
      try {
        resolve(JSON.parse(stdout) as AnchorRepairCliResult);
      } catch (error) {
        reject(error);
      }
    });
  });
};

export const getLatestCoverLetterText = (db: ApplyocalypseDatabase, profileId: string): string | null => {
  type Row = { canonical_json: string };
  const row = db
    .prepare(
      `
      SELECT pd.canonical_json
      FROM parsed_documents pd
      INNER JOIN uploaded_files uf ON uf.id = pd.uploaded_file_id
      WHERE uf.profile_id = ?
        AND uf.file_kind = 'COVER_LETTER'
        AND uf.deleted_at IS NULL
      ORDER BY pd.created_at DESC
      LIMIT 1
      `
    )
    .get(profileId) as Row | undefined;
  if (!row) return null;
  try {
    const canonical = JSON.parse(row.canonical_json) as { rawTextPreview?: string };
    return canonical.rawTextPreview || null;
  } catch {
    return null;
  }
};

export class DocumentIngestionService {
  constructor(
    private readonly uploads: UploadRepository,
    private readonly parsedDocuments: ParsedDocumentRepository,
    private readonly sourceCustodyRoot: string | null = null
  ) {}

  private custodyRoot(): string {
    return this.sourceCustodyRoot ?? join(app.getPath("userData"), "source-materials");
  }

  private copyPickedFile(input: {
    profileId: string | null;
    localPath: string;
    fileKind: UploadedFile["fileKind"];
  }): string {
    return copySourceIntoCustody({
      profileId: input.profileId,
      localPath: input.localPath,
      fileKind: input.fileKind,
      rootDir: this.custodyRoot()
    });
  }

  private async parseAndPersist(input: { uploadedFile: UploadedFile; mergeIntoProfile: boolean }): Promise<ParsedDocumentMergeSummary> {
    const parsed = await runDocumentParse(input.uploadedFile.localPath, input.uploadedFile.fileKind);
    if (input.mergeIntoProfile) {
      return this.parsedDocuments.createAndMerge({
        uploadedFileId: input.uploadedFile.id,
        parserName: parsed.parser_name,
        parserVersion: parsed.parser_version,
        confidence: parsed.confidence,
        canonical: ParsedDocumentCanonicalSchema.parse(parsed.canonical),
        styleMap: parsed.style_map,
        anchorMap: parsed.anchor_map,
        warnings: parsed.warnings
      });
    }

    const parsedDocument = this.parsedDocuments.create({
      uploadedFileId: input.uploadedFile.id,
      parserName: parsed.parser_name,
      parserVersion: parsed.parser_version,
      confidence: parsed.confidence,
      canonical: ParsedDocumentCanonicalSchema.parse(parsed.canonical),
      styleMap: parsed.style_map,
      anchorMap: parsed.anchor_map,
      warnings: parsed.warnings
    });

    return ParsedDocumentMergeSummarySchema.parse({
      parsedDocument,
      updatedProfile: null,
      applied: [],
      skipped: ["Editable master has not been confirmed by the user."],
      requiresReview: true
    });
  }

  async ingestResumeSource(input: { profileId: string | null; localPath: string }): Promise<ResumeIngestionResult> {
    const extension = extname(input.localPath).toLowerCase();
    const custodyPath = this.copyPickedFile({ profileId: input.profileId, localPath: input.localPath, fileKind: "RESUME" });
    const sourceFile = this.uploads.registerLocalFile({
      profileId: input.profileId,
      localPath: custodyPath,
      fileKind: "RESUME",
      status: extension === ".pdf" ? "IMMUTABLE_SOURCE" : "VERIFIED_EDITABLE_MASTER"
    });

    if (extension !== ".pdf") {
      return {
        sourceFile,
        editableMasterCandidate: null,
        parsing: await this.parseAndPersist({ uploadedFile: sourceFile, mergeIntoProfile: true }),
        requiresUserVerification: false,
        userMessage: "Editable resume source registered."
      };
    }

    const outputDir = join(app.getPath("userData"), "editable-masters", input.profileId ?? "unassigned", sourceFile.id);
    mkdirSync(outputDir, { recursive: true });
    const conversion = await runPdfConversion(custodyPath, outputDir);
    const editableMasterCandidate = this.uploads.registerLocalFile({
      profileId: input.profileId,
      localPath: conversion.candidate_docx_path,
      fileKind: "RESUME",
      status: "UNVERIFIED_EDITABLE_MASTER",
      parentFileId: sourceFile.id
    });

    return {
      sourceFile,
      editableMasterCandidate,
      parsing: await this.parseAndPersist({ uploadedFile: editableMasterCandidate, mergeIntoProfile: false }),
      requiresUserVerification: true,
      userMessage: conversion.user_message
    };
  }

  async ingestSourceMaterial(input: {
    profileId: string | null;
    localPath: string;
    fileKind: Exclude<UploadedFile["fileKind"], "RESUME">;
  }): Promise<SourceMaterialIngestionResult> {
    const custodyPath = this.copyPickedFile({ profileId: input.profileId, localPath: input.localPath, fileKind: input.fileKind });
    const uploadedFile = this.uploads.registerLocalFile({
      profileId: input.profileId,
      localPath: custodyPath,
      fileKind: input.fileKind
    });

    const shouldMergeIntoProfile = input.fileKind === "SUPPORTING_DETAILS";
    return {
      uploadedFile,
      parsing: await this.parseAndPersist({ uploadedFile, mergeIntoProfile: shouldMergeIntoProfile })
    };
  }

  async repairEditableMasterAnchors(input: { uploadedFileId: string }): Promise<EditableMasterAnchorRepairResult> {
    const sourceFile = this.uploads.getById(input.uploadedFileId);
    if (sourceFile.fileKind !== "RESUME" || !["DOCX", "TEX"].includes(sourceFile.sourceFormat)) {
      throw new Error("Anchor repair is only available for DOCX and TEX resume editable masters");
    }

    const extension = extname(sourceFile.localPath).toLowerCase();
    const originalStem = basename(sourceFile.localPath, extension);
    const outputDir = join(app.getPath("userData"), "editable-masters", "anchor-repair", sourceFile.profileId ?? "unassigned", sourceFile.id);
    mkdirSync(outputDir, { recursive: true });
    const outputPath = join(outputDir, `${originalStem} Applyocalypse Anchored${extension}`);
    const repair = await runAnchorRepair(sourceFile.localPath, outputPath);
    const anchoredCandidate = this.uploads.registerLocalFile({
      profileId: sourceFile.profileId,
      localPath: repair.output_path,
      fileKind: "RESUME",
      status: "UNVERIFIED_EDITABLE_MASTER",
      parentFileId: sourceFile.id
    });

    return {
      anchoredCandidate,
      parsing: await this.parseAndPersist({ uploadedFile: anchoredCandidate, mergeIntoProfile: false }),
      addedPlaceholders: repair.added_placeholders,
      alreadyPresentPlaceholders: repair.already_present_placeholders,
      warnings: repair.warnings,
      userMessage:
        "Created a reviewable anchored editable-master candidate. Open it, verify the placeholder placement, then confirm it before automated tailoring."
    };
  }
}
