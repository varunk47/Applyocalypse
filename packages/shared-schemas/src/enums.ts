import { z } from "zod";

export const ThemePreferenceSchema = z.enum(["dark", "light", "system"]);
export const ActiveThemeSchema = z.enum(["dark", "light"]);

export const LlmProviderTypeSchema = z.enum([
  "openai",
  "anthropic",
  "gemini",
  "zai",
  "xai",
  "groq",
  "nvidia_nim",
  "openrouter",
  "azure_openai",
  "aws_bedrock"
]);

export const ProviderTypeSchema = z.enum([...LlmProviderTypeSchema.options, "gmail"]);
export const SecretProviderTypeSchema = z.enum([...ProviderTypeSchema.options, "local"]);

export const SourceFormatSchema = z.enum(["PDF", "DOCX", "TEX", "TXT", "MD"]);
export const UploadedFileStatusSchema = z.enum([
  "UPLOADED",
  "IMMUTABLE_SOURCE",
  "UNVERIFIED_EDITABLE_MASTER",
  "VERIFIED_EDITABLE_MASTER",
  "REJECTED",
  "DELETED"
]);

export const QueueStatusSchema = z.enum([
  "PENDING",
  "CLAIMED",
  "PREPARING",
  "PARSING_JD",
  "ANALYZING",
  "TAILORING_RESUME",
  "GENERATING_COVER_LETTER",
  "READY_FOR_REVIEW",
  "RUNNING_AUTOMATION",
  "PAUSED",
  "BLOCKED_CAPTCHA",
  "BLOCKED_MFA",
  "BLOCKED_OTP",
  "BLOCKED_AMBIGUOUS_QUESTION",
  "WAITING_FOR_USER_EDIT",
  "READY_TO_SUBMIT",
  "SUBMITTED",
  "COMPLETED",
  "FAILED",
  "CANCELLED"
]);

export const StepStatusSchema = z.enum([
  "PENDING",
  "RUNNING",
  "WAITING_FOR_USER",
  "PAUSED",
  "SKIPPED",
  "RETRYING",
  "COMPLETED",
  "FAILED",
  "CANCELLED"
]);

export const SeveritySchema = z.enum(["DEBUG", "INFO", "WARN", "ERROR", "CRITICAL"]);

export const RunEventTypeSchema = z.enum([
  "RUN_STARTED",
  "JD_SCRAPE_STARTED",
  "JD_SCRAPE_COMPLETED",
  "JD_ANALYSIS_COMPLETED",
  "RESUME_TAILORING_STARTED",
  "RESUME_MUTATION_COMPLETED",
  "RESUME_RENDERED",
  "COVER_LETTER_REQUIRED",
  "COVER_LETTER_RENDERED",
  "VALIDATION_FAILED",
  "BROWSER_LAUNCHED",
  "PAGE_NAVIGATED",
  "PORTAL_WORKFLOW_SELECTED",
  "PORTAL_ACTION_APPLIED",
  "PORTAL_STATE_OBSERVED",
  "BROWSER_ARTIFACT_CAPTURED",
  "FIELD_DETECTED",
  "FIELD_VALUE_PROPOSED",
  "FIELD_VALUE_APPLIED",
  "FILE_UPLOADED",
  "SCREENSHOT_CAPTURED",
  "OTP_RETRIEVAL_STARTED",
  "OTP_RETRIEVAL_COMPLETED",
  "OTP_RETRIEVAL_FAILED",
  "USER_REVIEW_REQUIRED",
  "PAUSED",
  "RESUMED",
  "READY_TO_SUBMIT",
  "SUBMITTED",
  "FAILED",
  "CLEANUP_COMPLETED"
]);

export const ReviewStatusSchema = z.enum(["OPEN", "APPROVED", "REJECTED", "EXPIRED", "CANCELLED"]);
export const ApprovalTypeSchema = z.enum(["FINAL_SUBMIT", "ANSWER_EDIT", "DOCUMENT_APPROVAL", "OTP_READ", "AUTO_SUBMIT"]);
export const GeneratedFileKindSchema = z.enum(["RESUME", "COVER_LETTER"]);
export const GeneratedFileFormatSchema = z.enum(["DOCX", "PDF", "TEX", "TXT", "MD"]);
export const UploadStatusSchema = z.enum(["NOT_UPLOADED", "UPLOADED", "FAILED", "SKIPPED"]);
