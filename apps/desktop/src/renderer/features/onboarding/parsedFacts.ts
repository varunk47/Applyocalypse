import type { ParsedDocument } from '@applyocalypse/shared-types'

export type ParsedCanonical = ParsedDocument['canonical']

/**
 * Anything the parser is less sure about than this gets pulled to the top of the
 * review as "needs a look". It matches the gate `mergeIntoProfile` applies, so
 * the flagged rows are exactly the ones that would otherwise be silently dropped
 * instead of landing in the profile.
 */
export const LOW_CONFIDENCE_THRESHOLD = 0.75

export type FactGroup = 'Experience' | 'Education' | 'Projects' | 'Certifications' | 'Skills'

export type FactFlag = {
  group: FactGroup
  label: string
  confidence: number
}

/**
 * How many discrete facts the resume gave up. Individual skills count; bullets
 * do not, because they are read as part of the role they hang off.
 */
export const countFacts = (canonical: ParsedCanonical): number => {
  const identity = canonical.identity
  const identityFacts = [identity.legalName, identity.email, identity.phone, identity.location].filter(Boolean).length

  return (
    identityFacts +
    identity.links.length +
    canonical.experience.length +
    canonical.education.length +
    canonical.projects.length +
    canonical.certifications.length +
    canonical.skillGroups.reduce((total, group) => total + group.skills.length, 0)
  )
}

/** Every parsed entry we are not confident about, worst first. */
export const lowConfidenceFacts = (canonical: ParsedCanonical): FactFlag[] => {
  const flags: FactFlag[] = [
    ...canonical.experience.map((entry) => ({
      group: 'Experience' as const,
      label: [entry.title, entry.company].filter(Boolean).join(' at '),
      confidence: entry.confidence,
    })),
    ...canonical.education.map((entry) => ({
      group: 'Education' as const,
      label: entry.institution,
      confidence: entry.confidence,
    })),
    ...canonical.projects.map((entry) => ({
      group: 'Projects' as const,
      label: entry.name,
      confidence: entry.confidence,
    })),
    ...canonical.certifications.map((entry) => ({
      group: 'Certifications' as const,
      label: entry.name,
      confidence: entry.confidence,
    })),
    ...canonical.skillGroups.map((group) => ({
      group: 'Skills' as const,
      label: group.label,
      confidence: group.confidence,
    })),
  ]

  return flags
    .filter((flag) => flag.confidence < LOW_CONFIDENCE_THRESHOLD)
    .sort((a, b) => a.confidence - b.confidence)
}

/** `0.82` reads as `82%` in the ledger. */
export const formatConfidence = (confidence: number): string => `${Math.round(confidence * 100)}%`
