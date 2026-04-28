import { z } from "zod";

export const IdSchema = z.string().trim().min(1).max(128);
export const OptionalIdSchema = IdSchema.nullable().optional();

export const IsoDateTimeSchema = z
  .string()
  .datetime({ offset: true })
  .or(z.string().regex(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}/));

export const JsonObjectSchema = z.record(z.unknown());
export const JsonArraySchema = z.array(z.unknown());

export const LocalPathSchema = z.string().trim().min(1).max(4096);

export const ApplicationPasswordSchema = z
  .string()
  .min(12, "Password must be at least 12 characters")
  .max(256, "Password is too long")
  .regex(/[a-z]/, "Password must include a lowercase letter")
  .regex(/[A-Z]/, "Password must include an uppercase letter")
  .regex(/[0-9]/, "Password must include a number")
  .regex(/[^A-Za-z0-9]/, "Password must include a symbol");

export const PaginationSchema = z.object({
  limit: z.number().int().min(1).max(250).default(50),
  offset: z.number().int().min(0).default(0)
});

export const EmptyRequestSchema = z.object({}).strict();

export const SuccessResponseSchema = z.object({
  success: z.literal(true)
});

export const FailureResponseSchema = z.object({
  success: z.literal(false),
  error: z.object({
    code: z.string().min(1),
    message: z.string().min(1)
  })
});
