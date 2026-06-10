import { z } from "zod";
import {
  ApplicationAnswerSchema,
  ApplicationRunSchema,
  ApplicationStepSchema,
  ApplicationPasswordSchema,
  ApprovalTypeSchema,
  BrowserArtifactSchema,
  CanonicalProfileSchema,
  EmptyRequestSchema,
  GeneratedFileSchema,
  IdSchema,
  JobTargetSchema,
  JsonObjectSchema,
  LlmProviderTypeSchema,
  PaginationSchema,
  ParsedDocumentMergeSummarySchema,
  ParsedDocumentSchema,
  ProfileSchema,
  ProviderConnectionSchema,
  QueueItemSchema,
  ReviewRequestSchema,
  RunEventSchema,
  SafeRendererRunEventSchema,
  ScreenshotSchema,
  ThemePreferenceSchema,
  ThemeStateSchema,
  UploadedFileSchema
} from "@applyocalypse/shared-schemas";

const StructuredEntryIdField = { id: IdSchema.nullable().optional() };
const StructuredEducationInputSchema = z.object({ ...StructuredEntryIdField, institution: z.string().min(1), degree: z.string().nullable().optional(), field: z.string().nullable().optional(), startDate: z.string().nullable().optional(), endDate: z.string().nullable().optional() });
const StructuredExperienceInputSchema = z.object({ ...StructuredEntryIdField, company: z.string().min(1), title: z.string().min(1), location: z.string().nullable().optional(), startDate: z.string().nullable().optional(), endDate: z.string().nullable().optional(), bullets: z.array(z.string()).default([]) });
const StructuredProjectInputSchema = z.object({ ...StructuredEntryIdField, name: z.string().min(1), summary: z.string().nullable().optional(), bullets: z.array(z.string()).default([]), tools: z.array(z.string()).default([]) });
const StructuredSkillGroupInputSchema = z.object({ ...StructuredEntryIdField, label: z.string().min(1), skills: z.array(z.string()).default([]) });

export type IpcContract<Request extends z.ZodTypeAny, Response extends z.ZodTypeAny> = {
  channel: string;
  request: Request;
  response: Response;
};

const contract = <Request extends z.ZodTypeAny, Response extends z.ZodTypeAny>(
  channel: string,
  request: Request,
  response: Response
): IpcContract<Request, Response> => ({ channel, request, response });

const RunControlResponseSchema = z.object({ accepted: z.boolean(), message: z.string().optional() });
const RendererAnswerUpdateStatusSchema = z.enum(["EDITED", "REJECTED"]);

export const IpcChannels = {
  appGetVersion: "app:get-version",
  themeGetInitialState: "theme:get-initial-state",
  themeSetPreference: "theme:set-preference",
  themeUpdated: "theme:updated",
  settingsGet: "settings:get",
  settingsUpdate: "settings:update",
  providersList: "providers:list",
  providersSaveApiKey: "providers:save-api-key",
  documentsIngestResumeSource: "documents:ingest-resume-source",
  documentsConfirmEditableMaster: "documents:confirm-editable-master",
  documentsRepairEditableMasterAnchors: "documents:repair-editable-master-anchors",
  documentsListParsed: "documents:list-parsed",
  profileGet: "profile:get",
  profileGetCanonical: "profile:get-canonical",
  profileCreateStarter: "profile:create-starter",
  profileConfigureApplicationCredentials: "profile:configure-application-credentials",
  profileUpdate: "profile:update",
  profileUpdateStructured: "profile:update-structured",
  filesPick: "files:pick",
  filesListUploads: "files:list-uploads",
  filesRegisterUpload: "files:register-upload",
  filesOpenLocalPath: "files:open-local-path",
  jobsEnqueue: "jobs:enqueue",
  jobsList: "jobs:list",
  jobsGet: "jobs:get",
  runsPause: "runs:pause",
  runsResume: "runs:resume",
  runsCancel: "runs:cancel",
  runsList: "runs:list",
  runsGetDetail: "runs:get-detail",
  runsListAnswers: "runs:list-answers",
  runsUpdateAnswer: "runs:update-answer",
  runsListReviewRequests: "runs:list-review-requests",
  runsResolveReview: "runs:resolve-review",
  runsRetryStep: "runs:retry-step",
  runsSkipStep: "runs:skip-step",
  runsApprove: "runs:approve",
  runsReject: "runs:reject",
  logsSubscribe: "logs:subscribe",
  logsEvent: "logs:event",
  screenshotsList: "screenshots:list",
  foldersOpenDownloads: "folders:open-downloads",
  foldersChooseOutputDir: "folders:choose-output-dir"
} as const;

export const IpcContracts = {
  appGetVersion: contract(
    IpcChannels.appGetVersion,
    EmptyRequestSchema,
    z.object({ version: z.string().min(1) })
  ),
  themeGetInitialState: contract(IpcChannels.themeGetInitialState, EmptyRequestSchema, ThemeStateSchema),
  themeSetPreference: contract(
    IpcChannels.themeSetPreference,
    z.object({ preference: ThemePreferenceSchema }).strict(),
    ThemeStateSchema
  ),
  settingsGet: contract(IpcChannels.settingsGet, EmptyRequestSchema, z.record(z.unknown())),
  settingsUpdate: contract(
    IpcChannels.settingsUpdate,
    z.object({ patch: JsonObjectSchema }).strict(),
    z.record(z.unknown())
  ),
  providersList: contract(IpcChannels.providersList, EmptyRequestSchema, z.object({ items: z.array(ProviderConnectionSchema) })),
  providersSaveApiKey: contract(
    IpcChannels.providersSaveApiKey,
    z.object({
      provider: LlmProviderTypeSchema,
      displayName: z.string().trim().min(1),
      apiKey: z.string().min(1).max(8192),
      metadata: JsonObjectSchema.optional()
    }).strict(),
    ProviderConnectionSchema
  ),
  documentsIngestResumeSource: contract(
    IpcChannels.documentsIngestResumeSource,
    z.object({
      profileId: IdSchema.nullable(),
      localPath: z.string().min(1)
    }).strict(),
    z.object({
      sourceFile: UploadedFileSchema,
      editableMasterCandidate: UploadedFileSchema.nullable(),
      parsing: ParsedDocumentMergeSummarySchema.nullable(),
      requiresUserVerification: z.boolean(),
      userMessage: z.string().min(1)
    })
  ),
  documentsConfirmEditableMaster: contract(
    IpcChannels.documentsConfirmEditableMaster,
    z.object({ uploadedFileId: IdSchema }).strict(),
    UploadedFileSchema
  ),
  documentsRepairEditableMasterAnchors: contract(
    IpcChannels.documentsRepairEditableMasterAnchors,
    z.object({ uploadedFileId: IdSchema }).strict(),
    z.object({
      anchoredCandidate: UploadedFileSchema,
      parsing: ParsedDocumentMergeSummarySchema.nullable(),
      addedPlaceholders: z.array(z.string()),
      alreadyPresentPlaceholders: z.array(z.string()),
      warnings: z.array(z.string()),
      userMessage: z.string().min(1)
    })
  ),
  documentsListParsed: contract(
    IpcChannels.documentsListParsed,
    z.object({ uploadedFileId: IdSchema.optional(), profileId: IdSchema.nullable().optional() }).strict(),
    z.object({ items: z.array(ParsedDocumentSchema) })
  ),
  profileGet: contract(IpcChannels.profileGet, EmptyRequestSchema, ProfileSchema.nullable()),
  profileGetCanonical: contract(
    IpcChannels.profileGetCanonical,
    z.object({ profileId: IdSchema.optional() }).strict(),
    CanonicalProfileSchema.nullable()
  ),
  profileCreateStarter: contract(
    IpcChannels.profileCreateStarter,
    z.object({
      legalName: z.string().trim().min(1),
      email: z.string().email().nullable().optional(),
      location: z.string().trim().min(1).nullable().optional(),
      applicationEmail: z.string().email(),
      applicationPassword: ApplicationPasswordSchema,
      gmailOtpEnabled: z.boolean().default(false),
      workAuthorization: z.object({
        summary: z.string(),
        sponsorshipRequired: z.boolean(),
        status: z.string().optional()
      }).optional()
    }).strict(),
    ProfileSchema
  ),
  profileConfigureApplicationCredentials: contract(
    IpcChannels.profileConfigureApplicationCredentials,
    z.object({
      profileId: IdSchema,
      applicationEmail: z.string().email(),
      applicationPassword: ApplicationPasswordSchema,
      gmailOtpEnabled: z.boolean().default(false)
    }).strict(),
    ProfileSchema
  ),
  profileUpdate: contract(IpcChannels.profileUpdate, z.object({ profile: ProfileSchema }).strict(), ProfileSchema),
  profileUpdateStructured: contract(
    IpcChannels.profileUpdateStructured,
    z.object({
      profileId: IdSchema,
      education: z.array(StructuredEducationInputSchema),
      experience: z.array(StructuredExperienceInputSchema),
      projects: z.array(StructuredProjectInputSchema),
      skillGroups: z.array(StructuredSkillGroupInputSchema)
    }).strict(),
    CanonicalProfileSchema.nullable()
  ),
  filesPick: contract(
    IpcChannels.filesPick,
    z.object({ purpose: z.enum(["resume", "cover_letter", "supporting_details", "other"]) }).strict(),
    z
      .object({
        canceled: z.literal(false),
        paths: z.array(z.string().min(1)).min(1)
      })
      .or(z.object({ canceled: z.literal(true), paths: z.array(z.string()).length(0) }))
  ),
  filesListUploads: contract(
    IpcChannels.filesListUploads,
    z.object({ profileId: IdSchema.nullable().optional() }).strict(),
    z.object({ items: z.array(UploadedFileSchema) })
  ),
  filesRegisterUpload: contract(
    IpcChannels.filesRegisterUpload,
    z.object({
      profileId: IdSchema.nullable(),
      localPath: z.string().min(1),
      fileKind: z.enum(["RESUME", "COVER_LETTER", "SUPPORTING_DETAILS", "OTHER"])
    }).strict(),
    z.object({ uploadedFile: UploadedFileSchema, parsing: ParsedDocumentMergeSummarySchema.nullable() })
  ),
  filesOpenLocalPath: contract(IpcChannels.filesOpenLocalPath, z.object({ localPath: z.string().min(1) }).strict(), z.object({ opened: z.boolean() })),
  jobsEnqueue: contract(
    IpcChannels.jobsEnqueue,
    z.object({
      profileId: IdSchema,
      items: z
        .array(
          z.object({
            sourceKind: z.enum(["URL", "TEXT"]),
            sourceValue: z.string().min(1),
            autoSubmitEnabled: z.boolean().optional().default(false)
          })
        )
        .min(1)
    }),
    z.object({ jobTargets: z.array(JobTargetSchema), queueItems: z.array(QueueItemSchema) })
  ),
  jobsList: contract(IpcChannels.jobsList, PaginationSchema, z.object({ items: z.array(QueueItemSchema), total: z.number().int().nonnegative() })),
  jobsGet: contract(IpcChannels.jobsGet, z.object({ runId: IdSchema }).strict(), z.object({ run: RunEventSchema.nullable() })),
  runsPause: contract(IpcChannels.runsPause, z.object({ runId: IdSchema }).strict(), RunControlResponseSchema),
  runsResume: contract(IpcChannels.runsResume, z.object({ runId: IdSchema }).strict(), RunControlResponseSchema),
  runsCancel: contract(IpcChannels.runsCancel, z.object({ runId: IdSchema }).strict(), RunControlResponseSchema),
  runsList: contract(
    IpcChannels.runsList,
    PaginationSchema,
    z.object({ items: z.array(ApplicationRunSchema), total: z.number().int().nonnegative() })
  ),
  runsGetDetail: contract(
    IpcChannels.runsGetDetail,
    z.object({ runId: IdSchema }).strict(),
    z.object({
      run: ApplicationRunSchema,
      steps: z.array(ApplicationStepSchema),
      answers: z.array(ApplicationAnswerSchema),
      reviewRequests: z.array(ReviewRequestSchema),
      generatedFiles: z.array(GeneratedFileSchema),
      browserArtifacts: z.array(BrowserArtifactSchema),
      events: z.array(RunEventSchema)
    })
  ),
  runsListAnswers: contract(
    IpcChannels.runsListAnswers,
    z.object({ runId: IdSchema }).strict(),
    z.object({ items: z.array(ApplicationAnswerSchema) })
  ),
  runsUpdateAnswer: contract(
    IpcChannels.runsUpdateAnswer,
    z.object({
      runId: IdSchema,
      answerId: IdSchema,
      userValue: z.string().nullable(),
      status: RendererAnswerUpdateStatusSchema
    }).strict(),
    ApplicationAnswerSchema
  ),
  runsListReviewRequests: contract(
    IpcChannels.runsListReviewRequests,
    z.object({ runId: IdSchema }).strict(),
    z.object({ items: z.array(ReviewRequestSchema) })
  ),
  runsResolveReview: contract(
    IpcChannels.runsResolveReview,
    z.object({
      runId: IdSchema,
      reviewRequestId: IdSchema,
      status: z.enum(["APPROVED", "REJECTED"]),
      reason: z.string().max(2000).optional()
    }).strict(),
    RunControlResponseSchema
  ),
  runsRetryStep: contract(IpcChannels.runsRetryStep, z.object({ runId: IdSchema, stepId: IdSchema }).strict(), RunControlResponseSchema),
  runsSkipStep: contract(IpcChannels.runsSkipStep, z.object({ runId: IdSchema, stepId: IdSchema }).strict(), RunControlResponseSchema),
  runsApprove: contract(IpcChannels.runsApprove, z.object({ runId: IdSchema, approvalType: ApprovalTypeSchema }).strict(), RunControlResponseSchema),
  runsReject: contract(
    IpcChannels.runsReject,
    z.object({ runId: IdSchema, reason: z.string().min(1), approvalType: ApprovalTypeSchema.optional() }).strict(),
    RunControlResponseSchema
  ),
  logsSubscribe: contract(IpcChannels.logsSubscribe, z.object({ runId: IdSchema }).strict(), z.object({ subscribed: z.boolean() })),
  screenshotsList: contract(IpcChannels.screenshotsList, z.object({ runId: IdSchema }).strict(), z.object({ items: z.array(ScreenshotSchema) })),
  foldersOpenDownloads: contract(IpcChannels.foldersOpenDownloads, EmptyRequestSchema, z.object({ opened: z.boolean() })),
  foldersChooseOutputDir: contract(
    IpcChannels.foldersChooseOutputDir,
    EmptyRequestSchema,
    z.object({ canceled: z.boolean(), localPath: z.string().nullable() })
  )
} as const;

export const RendererEventSchemas = {
  themeUpdated: ThemeStateSchema,
  logsEvent: SafeRendererRunEventSchema,
  generatedFile: GeneratedFileSchema
} as const;

export type IpcContractKey = keyof typeof IpcContracts;
