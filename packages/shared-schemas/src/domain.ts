import { z } from "zod";
import {
  ActiveThemeSchema,
  ApprovalTypeSchema,
  GeneratedFileFormatSchema,
  GeneratedFileKindSchema,
  ProviderTypeSchema,
  QueueStatusSchema,
  ReviewStatusSchema,
  RunEventTypeSchema,
  SeveritySchema,
  SourceFormatSchema,
  StepStatusSchema,
  ThemePreferenceSchema,
  UploadStatusSchema,
  UploadedFileStatusSchema
} from "./enums";
import { IdSchema, IsoDateTimeSchema, JsonObjectSchema, LocalPathSchema } from "./common";

export const ThemeStateSchema = z.object({
  preference: ThemePreferenceSchema,
  activeTheme: ActiveThemeSchema,
  updatedAt: IsoDateTimeSchema
});

export const AppSettingSchema = z.object({
  key: z.string().min(1),
  value: z.unknown(),
  updatedAt: IsoDateTimeSchema
});

export const ProviderConnectionSchema = z.object({
  id: IdSchema,
  provider: ProviderTypeSchema,
  displayName: z.string().min(1),
  status: z.enum(["DISCONNECTED", "CONNECTED", "ERROR"]),
  secretRefId: IdSchema.nullable(),
  metadata: JsonObjectSchema.default({}),
  createdAt: IsoDateTimeSchema,
  updatedAt: IsoDateTimeSchema
});

export const AddressSchema = z.object({
  country: z.string().nullable().default(null),
  city: z.string().nullable().default(null),
  state: z.string().nullable().default(null),
  addressLine1: z.string().nullable().default(null),
  addressLine2: z.string().nullable().default(null),
  postalCode: z.string().nullable().default(null),
  county: z.string().nullable().default(null)
});

export const EqualEmploymentDefaultsSchema = z.object({
  authorizedToWorkUS: z.enum(["Yes", "No"]).nullable().default(null),
  requiresSponsorship: z.enum(["Yes", "No"]).nullable().default(null),
  sponsorshipDetailText: z.string().nullable().default(null),
  disability: z.enum(["Yes", "No", "Prefer not to say"]).nullable().default(null),
  gender: z.string().nullable().default(null),
  lgbtq: z.enum(["Yes", "No", "Prefer not to say"]).nullable().default(null),
  veteran: z.enum(["Yes", "No", "Prefer not to say"]).nullable().default(null),
  race: z.string().nullable().default(null),
  hispanicOrLatino: z.enum(["Yes", "No"]).nullable().default(null),
  sexualOrientation: z.array(z.string()).nullable().default(null),
  previouslyEmployedDefault: z.literal("No").default("No"),
  criminalRecordDefault: z.literal("No").default("No")
});

export const EQUAL_EMPLOYMENT_SEED_DEFAULTS: z.infer<typeof EqualEmploymentDefaultsSchema> = {
  authorizedToWorkUS: "Yes",
  requiresSponsorship: "Yes",
  sponsorshipDetailText: "I'm authorized to work full-time for 36 months on F-1 OPT, no sponsorship required immediately.",
  disability: "No",
  gender: "Male",
  lgbtq: "No",
  veteran: "No",
  race: "Asian",
  hispanicOrLatino: "No",
  sexualOrientation: ["Heterosexual"],
  previouslyEmployedDefault: "No",
  criminalRecordDefault: "No"
};

export const ProfileSchema = z.object({
  id: IdSchema,
  displayName: z.string().min(1),
  legalName: z.string().min(1),
  firstName: z.string().nullable().default(null),
  lastName: z.string().nullable().default(null),
  email: z.string().email().nullable(),
  applicationEmail: z.string().email().nullable().default(null),
  applicationPasswordConfigured: z.boolean().default(false),
  otpProviderConnectionId: IdSchema.nullable().default(null),
  otpHandlingEnabled: z.boolean().default(false),
  phone: z.string().nullable(),
  location: z.string().nullable(),
  address: AddressSchema.default({}),
  linkedinUrl: z.string().url().nullable().default(null),
  githubUrl: z.string().url().nullable().default(null),
  links: z.array(z.object({ label: z.string(), url: z.string().url() })).default([]),
  jobDefaults: JsonObjectSchema.default({}),
  workAuthorization: JsonObjectSchema.default({}),
  equalEmploymentDefaults: EqualEmploymentDefaultsSchema.default({}),
  createdAt: IsoDateTimeSchema,
  updatedAt: IsoDateTimeSchema
});

export const EducationEntrySchema = z.object({
  id: IdSchema,
  profileId: IdSchema,
  institution: z.string().min(1),
  degree: z.string().nullable(),
  field: z.string().nullable(),
  gpa: z.string().nullable().default(null),
  startDate: z.string().nullable(),
  endDate: z.string().nullable(),
  details: z.array(z.string()).default([]),
  confidence: z.number().min(0).max(1).default(1)
});

export const ExperienceEntrySchema = z.object({
  id: IdSchema,
  profileId: IdSchema,
  company: z.string().min(1),
  title: z.string().min(1),
  location: z.string().nullable(),
  startDate: z.string().nullable(),
  endDate: z.string().nullable(),
  bullets: z.array(z.string()).default([]),
  tools: z.array(z.string()).default([]),
  confidence: z.number().min(0).max(1).default(1)
});

export const ProjectEntrySchema = z.object({
  id: IdSchema,
  profileId: IdSchema,
  name: z.string().min(1),
  role: z.string().nullable(),
  summary: z.string().nullable(),
  bullets: z.array(z.string()).default([]),
  tools: z.array(z.string()).default([]),
  links: z.array(z.string().url()).default([]),
  confidence: z.number().min(0).max(1).default(1)
});

export const CertificationEntrySchema = z.object({
  id: IdSchema,
  profileId: IdSchema,
  name: z.string().min(1),
  issuer: z.string().nullable(),
  issuedAt: z.string().nullable(),
  expiresAt: z.string().nullable(),
  credentialUrl: z.string().url().nullable(),
  confidence: z.number().min(0).max(1).default(1)
});

export const SkillGroupSchema = z.object({
  id: IdSchema,
  profileId: IdSchema,
  label: z.string().min(1),
  skills: z.array(z.string().min(1)).default([]),
  confidence: z.number().min(0).max(1).default(1)
});

export const UploadedFileSchema = z.object({
  id: IdSchema,
  profileId: IdSchema.nullable(),
  fileKind: z.enum(["RESUME", "COVER_LETTER", "SUPPORTING_DETAILS", "OTHER"]),
  sourceFormat: SourceFormatSchema,
  originalName: z.string().min(1),
  localPath: LocalPathSchema,
  mimeType: z.string().nullable(),
  sizeBytes: z.number().int().nonnegative(),
  sha256: z.string().nullable(),
  status: UploadedFileStatusSchema,
  createdAt: IsoDateTimeSchema,
  updatedAt: IsoDateTimeSchema
});

export const CanonicalProfileSchema = z.object({
  profile: ProfileSchema,
  education: z.array(EducationEntrySchema).default([]),
  experience: z.array(ExperienceEntrySchema).default([]),
  projects: z.array(ProjectEntrySchema).default([]),
  certifications: z.array(CertificationEntrySchema).default([]),
  skillGroups: z.array(SkillGroupSchema).default([]),
  uploadedFiles: z.array(UploadedFileSchema).default([])
});

export const ParsedDocumentSectionSchema = z.object({
  sectionId: z.string().min(1),
  label: z.string().min(1),
  normalizedLabel: z.string().min(1),
  startLine: z.number().int().nonnegative(),
  endLine: z.number().int().nonnegative(),
  confidence: z.number().min(0).max(1),
  items: z.array(z.string()).default([])
});

export const ParsedDocumentCanonicalSchema = z.object({
  documentKind: z.enum(["RESUME", "COVER_LETTER", "SUPPORTING_DETAILS", "OTHER"]),
  sourceFormat: SourceFormatSchema,
  identity: z
    .object({
      legalName: z.string().nullable().default(null),
      email: z.string().email().nullable().default(null),
      phone: z.string().nullable().default(null),
      location: z.string().nullable().default(null),
      links: z.array(z.object({ label: z.string(), url: z.string().url() })).default([])
    })
    .default({}),
  sections: z.array(ParsedDocumentSectionSchema).default([]),
  skillGroups: z.array(
    z.object({
      label: z.string().min(1),
      skills: z.array(z.string().min(1)).default([]),
      confidence: z.number().min(0).max(1)
    })
  ).default([]),
  education: z.array(
    z.object({
      institution: z.string().min(1),
      degree: z.string().nullable().default(null),
      field: z.string().nullable().default(null),
      startDate: z.string().nullable().default(null),
      endDate: z.string().nullable().default(null),
      details: z.array(z.string()).default([]),
      confidence: z.number().min(0).max(1)
    })
  ).default([]),
  experience: z.array(
    z.object({
      company: z.string().min(1),
      title: z.string().min(1),
      location: z.string().nullable().default(null),
      startDate: z.string().nullable().default(null),
      endDate: z.string().nullable().default(null),
      bullets: z.array(z.string()).default([]),
      tools: z.array(z.string()).default([]),
      confidence: z.number().min(0).max(1)
    })
  ).default([]),
  projects: z.array(
    z.object({
      name: z.string().min(1),
      role: z.string().nullable().default(null),
      summary: z.string().nullable().default(null),
      bullets: z.array(z.string()).default([]),
      tools: z.array(z.string()).default([]),
      links: z.array(z.string().url()).default([]),
      confidence: z.number().min(0).max(1)
    })
  ).default([]),
  certifications: z.array(
    z.object({
      name: z.string().min(1),
      issuer: z.string().nullable().default(null),
      issuedAt: z.string().nullable().default(null),
      expiresAt: z.string().nullable().default(null),
      credentialUrl: z.string().url().nullable().default(null),
      confidence: z.number().min(0).max(1)
    })
  ).default([]),
  rawTextPreview: z.string().default("")
});

export const ParsedDocumentSchema = z.object({
  id: IdSchema,
  uploadedFileId: IdSchema,
  parserName: z.string().min(1),
  parserVersion: z.string().min(1),
  confidence: z.number().min(0).max(1),
  canonical: ParsedDocumentCanonicalSchema,
  styleMap: JsonObjectSchema.default({}),
  anchorMap: JsonObjectSchema.default({}),
  warnings: z.array(z.string()).default([]),
  createdAt: IsoDateTimeSchema,
  updatedAt: IsoDateTimeSchema
});

export const ParsedDocumentMergeSummarySchema = z.object({
  parsedDocument: ParsedDocumentSchema,
  updatedProfile: ProfileSchema.nullable(),
  applied: z.array(z.string()).default([]),
  skipped: z.array(z.string()).default([]),
  requiresReview: z.boolean()
});

export const JobTargetSchema = z.object({
  id: IdSchema,
  sourceKind: z.enum(["URL", "TEXT"]),
  sourceValue: z.string().min(1),
  company: z.string().nullable(),
  role: z.string().nullable(),
  location: z.string().nullable(),
  portal: z.string().nullable(),
  status: QueueStatusSchema,
  createdAt: IsoDateTimeSchema,
  updatedAt: IsoDateTimeSchema
});

export const QueueItemSchema = z.object({
  id: IdSchema,
  profileId: IdSchema,
  jobTargetId: IdSchema,
  status: QueueStatusSchema,
  autoSubmitEnabled: z.boolean().default(false),
  priority: z.number().int().default(0),
  attempts: z.number().int().nonnegative().default(0),
  maxAttempts: z.number().int().min(1).max(5).default(3),
  claimedBy: z.string().nullable(),
  leaseExpiresAt: IsoDateTimeSchema.nullable(),
  heartbeatAt: IsoDateTimeSchema.nullable(),
  createdAt: IsoDateTimeSchema,
  updatedAt: IsoDateTimeSchema
});

export const ApplicationRunSchema = z.object({
  id: IdSchema,
  queueItemId: IdSchema,
  profileId: IdSchema,
  jobTargetId: IdSchema,
  tailoringRunId: IdSchema.nullable(),
  status: QueueStatusSchema,
  currentStepId: IdSchema.nullable(),
  autoSubmitEnabled: z.boolean(),
  startedAt: IsoDateTimeSchema.nullable(),
  completedAt: IsoDateTimeSchema.nullable(),
  failureCode: z.string().nullable(),
  failureMessage: z.string().nullable(),
  createdAt: IsoDateTimeSchema,
  updatedAt: IsoDateTimeSchema
});

export const ApplicationStepSchema = z.object({
  id: IdSchema,
  applicationRunId: IdSchema,
  stepOrder: z.number().int().nonnegative(),
  stepType: z.string().min(1),
  status: StepStatusSchema,
  pageUrl: z.string().nullable(),
  selector: z.string().nullable(),
  expectedState: JsonObjectSchema.default({}),
  result: JsonObjectSchema.default({}),
  createdAt: IsoDateTimeSchema,
  updatedAt: IsoDateTimeSchema
});

export const ApplicationAnswerSchema = z.object({
  id: IdSchema,
  applicationRunId: IdSchema,
  stepId: IdSchema.nullable(),
  fieldLabel: z.string().min(1),
  fieldType: z.string().min(1),
  proposedValue: z.string().nullable(),
  userValue: z.string().nullable(),
  source: z.enum(["PROFILE", "JD_ANALYSIS", "USER_EDIT", "LLM_PROPOSAL", "UNKNOWN"]),
  confidence: z.number().min(0).max(1),
  status: z.enum(["PROPOSED", "APPROVED", "EDITED", "APPLIED", "REJECTED"]),
  applyMetadata: JsonObjectSchema.default({})
});

export const ReviewRequestSchema = z.object({
  id: IdSchema,
  applicationRunId: IdSchema,
  stepId: IdSchema.nullable(),
  reviewType: z.enum(["FINAL_SUBMIT", "ANSWER", "DOCUMENT", "OTP", "AMBIGUOUS_QUESTION", "CAPTCHA", "MFA", "LOGIN", "PORTAL_ENTRY", "PORTAL_STEP"]),
  prompt: z.string().min(1),
  payload: JsonObjectSchema.default({}),
  status: ReviewStatusSchema,
  createdAt: IsoDateTimeSchema,
  updatedAt: IsoDateTimeSchema
});

export const ApprovalSchema = z.object({
  id: IdSchema,
  applicationRunId: IdSchema,
  reviewRequestId: IdSchema.nullable(),
  approvalType: ApprovalTypeSchema,
  status: ReviewStatusSchema,
  decidedAt: IsoDateTimeSchema.nullable(),
  notes: z.string().nullable()
});

export const ScreenshotSchema = z.object({
  id: IdSchema,
  applicationRunId: IdSchema,
  stepId: IdSchema.nullable(),
  screenshotId: z.string().min(1),
  localPath: LocalPathSchema,
  mimeType: z.string().min(1),
  width: z.number().int().positive(),
  height: z.number().int().positive(),
  sha256: z.string().nullable(),
  capturedAt: IsoDateTimeSchema
});

export const BrowserArtifactSchema = z.object({
  id: IdSchema,
  applicationRunId: IdSchema,
  artifactType: z.enum(["DOM_SNAPSHOT", "NETWORK_LOG", "CONSOLE_LOG", "TRACE", "DOWNLOAD"]),
  localPath: LocalPathSchema,
  metadata: JsonObjectSchema.default({}),
  createdAt: IsoDateTimeSchema
});

export const GeneratedFileSchema = z.object({
  id: IdSchema,
  tailoringRunId: IdSchema.nullable(),
  profileId: IdSchema,
  jobTargetId: IdSchema,
  fileKind: GeneratedFileKindSchema,
  format: GeneratedFileFormatSchema,
  filename: z.string().min(1),
  localPath: LocalPathSchema,
  sha256: z.string().nullable(),
  sizeBytes: z.number().int().nonnegative().nullable(),
  uploadStatus: UploadStatusSchema,
  uploadedAt: IsoDateTimeSchema.nullable(),
  retentionPolicy: z.enum(["DELETE_AFTER_UPLOAD", "DELETE_AFTER_RETENTION", "KEEP_UNTIL_USER_DELETES"]),
  deleteAfter: IsoDateTimeSchema.nullable(),
  deletedAt: IsoDateTimeSchema.nullable()
});

export const RunEventSchema = z.object({
  id: IdSchema.optional(),
  eventType: RunEventTypeSchema,
  runId: IdSchema,
  stepId: IdSchema.nullable(),
  timestamp: IsoDateTimeSchema,
  severity: SeveritySchema,
  message: z.string().min(1),
  machineState: JsonObjectSchema.default({}),
  uiState: JsonObjectSchema.default({}),
  payload: JsonObjectSchema.default({})
});
