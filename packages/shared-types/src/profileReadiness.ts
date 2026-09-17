import type { z } from "zod";
import type { CanonicalProfileSchema } from "@applyocalypse/shared-schemas";
import { readWorkAuthorization } from "./workAuthorization";

type CanonicalProfile = z.infer<typeof CanonicalProfileSchema>;

/**
 * Whether this profile can actually carry an application, and if not, what is
 * missing.
 *
 * Onboarding was only ever entered when no profile row existed. Once one did,
 * however little was in it, the app opened on Home and took job links. So a
 * profile with no confirmed resume master, or no work authorization answer,
 * queued runs that had to stop partway or fill blanks. The door has to be a
 * state the profile reaches, not a screen it passed through once.
 *
 * The formats the tailoring paths can write into. Kept in step with
 * MUTABLE_FORMATS in the worker's resume_master_gate, which stops a run for the
 * same reason this stops a queue.
 */
const MUTABLE_FORMATS = new Set(['DOCX', 'TEX'])

export type ReadinessCheck = {
  id: string
  /** Named as the thing itself, because it is shown as a list of what is missing. */
  label: string
  /** What the user has to go and do about it. */
  fix: string
  /** Where doing it happens. */
  route: string
  isMet: (profile: CanonicalProfile) => boolean
}

export const READINESS_CHECKS: readonly ReadinessCheck[] = [
  {
    id: 'RESUME_MASTER',
    label: 'A confirmed resume',
    fix: 'Upload your resume and confirm the editable copy, so there is something to tailor.',
    route: '/documents',
    isMet: (p) =>
      p.uploadedFiles.some(
        (f) =>
          f.fileKind === 'RESUME' &&
          f.status === 'VERIFIED_EDITABLE_MASTER' &&
          MUTABLE_FORMATS.has(f.sourceFormat) &&
          Boolean(f.localPath),
      ),
  },
  {
    id: 'CONTACT',
    label: 'Your name, email and phone',
    fix: 'Fill in the contact details every application form asks for first.',
    route: '/profile',
    isMet: (p) =>
      Boolean(p.profile.legalName?.trim()) &&
      Boolean(p.profile.email?.trim()) &&
      Boolean(p.profile.phone?.trim()),
  },
  {
    id: 'WORK_AUTHORIZATION',
    label: 'Your work authorization',
    fix: 'Say how you are authorized to work and whether you need sponsorship. Portals ask on almost every form.',
    route: '/profile',
    // A typed sentence cannot answer a Yes/No radio, and the portals ask two of
    // them, so only the structured answer counts as having said.
    isMet: (p) => readWorkAuthorization(p.profile.workAuthorization) !== null,
  },
  {
    id: 'HISTORY',
    label: 'Some work or study history',
    fix: 'Add at least one job or degree, so tailoring has something of yours to draw on.',
    route: '/profile',
    isMet: (p) => p.experience.length > 0 || p.education.length > 0,
  },
]

export type ProfileReadiness = {
  isReady: boolean
  gaps: readonly ReadinessCheck[]
}

export const profileReadiness = (profile: CanonicalProfile | null): ProfileReadiness => {
  if (!profile) return { isReady: false, gaps: READINESS_CHECKS }
  const gaps = READINESS_CHECKS.filter((check) => !check.isMet(profile))
  return { isReady: gaps.length === 0, gaps }
}
