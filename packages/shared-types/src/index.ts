import type { z } from "zod";
import type {
  ActiveThemeSchema,
  AddressSchema,
  ApplicationAnswerSchema,
  EqualEmploymentDefaultsSchema,
  ApplicationRunSchema,
  ApplicationStepSchema,
  ApprovalSchema,
  BrowserArtifactSchema,
  CanonicalProfileSchema,
  CertificationEntrySchema,
  ChatMessageSchema,
  EducationEntrySchema,
  ExperienceEntrySchema,
  GeneratedFileSchema,
  JobTargetSchema,
  ParsedDocumentMergeSummarySchema,
  ParsedDocumentSchema,
  ProfileSchema,
  ProjectEntrySchema,
  ProviderConnectionSchema,
  PythonWorkerEventSchema,
  QueueItemSchema,
  ReviewRequestSchema,
  RunEventSchema,
  SafeRendererRunEventSchema,
  ScreenshotSchema,
  SkillGroupSchema,
  ThemePreferenceSchema,
  ThemeStateSchema,
  UploadedFileSchema
} from "@applyocalypse/shared-schemas";

export * from "./dateUtils";

export type ThemePreference = z.infer<typeof ThemePreferenceSchema>;
export type ActiveTheme = z.infer<typeof ActiveThemeSchema>;
export type ThemeState = z.infer<typeof ThemeStateSchema>;
export type ProviderConnection = z.infer<typeof ProviderConnectionSchema>;
export type Profile = z.infer<typeof ProfileSchema>;
export type EducationEntry = z.infer<typeof EducationEntrySchema>;
export type ExperienceEntry = z.infer<typeof ExperienceEntrySchema>;
export type CertificationEntry = z.infer<typeof CertificationEntrySchema>;
export type SkillGroup = z.infer<typeof SkillGroupSchema>;
export type CanonicalProfile = z.infer<typeof CanonicalProfileSchema>;
export type UploadedFile = z.infer<typeof UploadedFileSchema>;
export type ParsedDocument = z.infer<typeof ParsedDocumentSchema>;
export type ParsedDocumentMergeSummary = z.infer<typeof ParsedDocumentMergeSummarySchema>;
export type JobTarget = z.infer<typeof JobTargetSchema>;
export type QueueItem = z.infer<typeof QueueItemSchema>;
export type ApplicationRun = z.infer<typeof ApplicationRunSchema>;
export type ApplicationStep = z.infer<typeof ApplicationStepSchema>;
export type ApplicationAnswer = z.infer<typeof ApplicationAnswerSchema>;
export type ReviewRequest = z.infer<typeof ReviewRequestSchema>;
export type Approval = z.infer<typeof ApprovalSchema>;
export type BrowserArtifact = z.infer<typeof BrowserArtifactSchema>;
export type Screenshot = z.infer<typeof ScreenshotSchema>;
export type GeneratedFile = z.infer<typeof GeneratedFileSchema>;
export type RunEvent = z.infer<typeof RunEventSchema>;
export type PythonWorkerEvent = z.infer<typeof PythonWorkerEventSchema>;
export type SafeRendererRunEvent = z.infer<typeof SafeRendererRunEventSchema>;
export type ProjectEntry = z.infer<typeof ProjectEntrySchema>;
export type Address = z.infer<typeof AddressSchema>;
export type EqualEmploymentDefaults = z.infer<typeof EqualEmploymentDefaultsSchema>;
export type ChatMessage = z.infer<typeof ChatMessageSchema>;
export { EQUAL_EMPLOYMENT_SEED_DEFAULTS } from "@applyocalypse/shared-schemas";
