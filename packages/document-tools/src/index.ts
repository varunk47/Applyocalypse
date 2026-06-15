import { existsSync } from "node:fs";
import { extname, join } from "node:path";

// eslint-disable-next-line no-control-regex -- strips C0 control chars from filenames
const INVALID_FILENAME_CHARS = /[<>:"/\\|?*\u0000-\u001F]/g;
const COLLAPSE_WHITESPACE = /\s+/g;

export type GeneratedDocumentNameInput = {
  firstName: string;
  lastName: string;
  company: string;
  role: string;
  kind: "Resume" | "CoverLetter";
  extension: "docx" | "pdf" | "tex" | "txt" | "md";
};

export const sanitizeFilenamePart = (value: string): string => {
  const sanitized = value.replace(INVALID_FILENAME_CHARS, " ").replace(COLLAPSE_WHITESPACE, " ").trim();
  return sanitized.length > 0 ? sanitized : "Untitled";
};

export const buildGeneratedDocumentFilename = (input: GeneratedDocumentNameInput): string => {
  const base = [
    input.firstName,
    input.lastName,
    input.company,
    input.role,
    input.kind
  ]
    .map(sanitizeFilenamePart)
    .join(" ");

  return `${base}.${input.extension}`;
};

export const chooseCollisionSafePath = (directory: string, filename: string): string => {
  const extension = extname(filename);
  const stem = extension ? filename.slice(0, -extension.length) : filename;
  let candidate = join(directory, filename);
  let suffix = 2;

  while (existsSync(candidate)) {
    candidate = join(directory, `${stem} (${suffix})${extension}`);
    suffix += 1;
  }

  return candidate;
};
