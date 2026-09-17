// Onboarding is meant to be the only door into applying. It was not: it opened
// on a missing profile row and never again, so a profile that existed but was
// half filled let the user paste links and watch runs that could not do the
// work. These tests hold the readiness check to naming every gap, in the terms
// of the thing the user has to go and do.
import { describe, it, expect } from 'vitest'
import type { CanonicalProfile } from './index'
import { profileReadiness, READINESS_CHECKS } from './profileReadiness'

const READY = {
  profile: {
    legalName: 'Grace Hopper',
    email: 'grace@example.com',
    phone: '+1-415-555-0132',
    workAuthorization: { status: 'US_CITIZEN', authorizedInUs: true, sponsorshipNeed: 'NEVER' },
  },
  experience: [{ company: 'Acme', title: 'Engineer' }],
  education: [],
  uploadedFiles: [
    { fileKind: 'RESUME', status: 'VERIFIED_EDITABLE_MASTER', sourceFormat: 'DOCX', localPath: 'C:/r.docx' },
  ],
} as unknown as CanonicalProfile

const without = (mutate: (draft: Record<string, unknown>) => void): CanonicalProfile => {
  const draft = structuredClone(READY) as unknown as Record<string, unknown>
  mutate(draft)
  return draft as unknown as CanonicalProfile
}

describe('profileReadiness', () => {
  it('lets a profile that can actually apply through', () => {
    const readiness = profileReadiness(READY)
    expect(readiness.isReady).toBe(true)
    expect(readiness.gaps).toHaveLength(0)
  })

  it('is not ready when there is no profile at all', () => {
    const readiness = profileReadiness(null)
    expect(readiness.isReady).toBe(false)
    expect(readiness.gaps.length).toBeGreaterThan(0)
  })

  // (what is missing, the check that should catch it)
  const CASES: Array<[string, CanonicalProfile, string]> = [
    ['no confirmed resume master', without((d) => { d['uploadedFiles'] = [] }), 'RESUME_MASTER'],
    [
      'a resume converted but never confirmed',
      without((d) => {
        d['uploadedFiles'] = [
          { fileKind: 'RESUME', status: 'UNVERIFIED_EDITABLE_MASTER', sourceFormat: 'DOCX', localPath: 'C:/c.docx' },
        ]
      }),
      'RESUME_MASTER',
    ],
    ['no email', without((d) => { (d['profile'] as Record<string, unknown>)['email'] = null }), 'CONTACT'],
    ['no phone', without((d) => { (d['profile'] as Record<string, unknown>)['phone'] = '' }), 'CONTACT'],
    [
      'work authorization never answered',
      without((d) => { (d['profile'] as Record<string, unknown>)['workAuthorization'] = {} }),
      'WORK_AUTHORIZATION',
    ],
    [
      // What older profiles stored. It reads like an answer and cannot fill a
      // Yes/No radio, so it does not count as one.
      'only the old free-text work authorization blob',
      without((d) => {
        (d['profile'] as Record<string, unknown>)['workAuthorization'] = {
          summary: 'Authorized to work in the US',
          sponsorshipRequired: false,
        }
      }),
      'WORK_AUTHORIZATION',
    ],
    [
      'nothing to tailor from',
      without((d) => { d['experience'] = []; d['education'] = [] }),
      'HISTORY',
    ],
  ]

  it.each(CASES)('reports %s', (_description, profile, checkId) => {
    const readiness = profileReadiness(profile)
    expect(readiness.isReady).toBe(false)
    expect(readiness.gaps.map((g) => g.id)).toContain(checkId)
  })

  it('accepts education alone as something to tailor from', () => {
    const readiness = profileReadiness(
      without((d) => {
        d['experience'] = []
        d['education'] = [{ institution: 'Yale' }]
      }),
    )
    expect(readiness.gaps.map((g) => g.id)).not.toContain('HISTORY')
  })

  it('reports every gap at once rather than one at a time', () => {
    const readiness = profileReadiness(
      without((d) => {
        d['uploadedFiles'] = []
        d['experience'] = []
        d['education'] = []
      }),
    )
    expect(readiness.gaps.map((g) => g.id)).toEqual(expect.arrayContaining(['RESUME_MASTER', 'HISTORY']))
  })

  it('tells the user where to go and what it is for', () => {
    for (const check of READINESS_CHECKS) {
      expect(check.label.trim(), check.id).toBeTruthy()
      expect(check.fix.trim(), check.id).toBeTruthy()
      // The banned-word gate applies to anything the user reads.
      expect(check.fix, check.id).not.toContain('\u2014')
      expect(check.label, check.id).not.toContain('\u2014')
    }
  })
})
