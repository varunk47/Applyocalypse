import { z } from "zod";
import { IdSchema, IsoDateTimeSchema, JsonObjectSchema, LocalPathSchema } from "./common";
import { GeneratedFileFormatSchema, GeneratedFileKindSchema, RunEventTypeSchema, SeveritySchema } from "./enums";

export const ScreenshotPayloadSchema = z.object({
  screenshot_id: z.string().min(1),
  local_path: LocalPathSchema,
  mime_type: z.string().min(1),
  width: z.number().int().positive(),
  height: z.number().int().positive(),
  sha256: z.string().nullable().optional(),
  captured_at: IsoDateTimeSchema
}).strict();

export const GeneratedFilePayloadSchema = z.object({
  file_kind: GeneratedFileKindSchema,
  format: GeneratedFileFormatSchema,
  filename: z.string().min(1),
  local_path: LocalPathSchema,
  sha256: z.string().min(16).nullable(),
  size_bytes: z.number().int().nonnegative().nullable(),
  retention_policy: z.enum(["DELETE_AFTER_UPLOAD", "DELETE_AFTER_RETENTION", "KEEP_UNTIL_USER_DELETES"]),
  delete_after: IsoDateTimeSchema.nullable(),
  review_only: z.boolean().optional(),
  validation_report_path: LocalPathSchema.optional()
}).strict();

export const BrowserArtifactPayloadSchema = z.object({
  artifact_id: z.string().min(1),
  artifact_type: z.enum(["DOM_SNAPSHOT", "NETWORK_LOG", "CONSOLE_LOG", "TRACE", "DOWNLOAD"]),
  local_path: LocalPathSchema,
  mime_type: z.string().min(1).optional(),
  metadata: JsonObjectSchema.default({}),
  captured_at: IsoDateTimeSchema
}).strict();

export const PythonWorkerEventSchema = z.object({
  event_type: RunEventTypeSchema,
  run_id: IdSchema,
  step_id: IdSchema.nullable(),
  timestamp: IsoDateTimeSchema,
  severity: SeveritySchema,
  message: z.string().min(1),
  machine_state: JsonObjectSchema.default({}),
  ui_state: JsonObjectSchema.default({}),
  payload: JsonObjectSchema.default({})
});

export const SafeRendererRunEventSchema = z.object({
  eventType: RunEventTypeSchema,
  runId: IdSchema,
  stepId: IdSchema.nullable(),
  timestamp: IsoDateTimeSchema,
  severity: SeveritySchema,
  message: z.string(),
  uiState: JsonObjectSchema.default({}),
  payload: JsonObjectSchema.default({})
});
