import { describe, expect, it } from 'vitest'
import {
  LOW_CONFIDENCE_THRESHOLD,
  countFacts,
  formatConfidence,
  lowConfidenceFacts,
  type ParsedCanonical,
} from './parsedFacts'

const canonical = (overrides: Partial<ParsedCanonical> = {}): ParsedCanonical =>
  ({
    documentKind: 'RESUME',
    sourceFormat: 'DOCX',
    identity: { legalName: null, email: null, phone: null, location: null, links: [] },
    sections: [],
    skillGroups: [],
    education: [],
    experience: [],
    projects: [],
    certifications: [],
    rawTextPreview: '',
    ...overrides,
  }) as ParsedCanonical

const experience = (confidence: number, company = 'Acme', title = 'Engineer') => ({
  company,
  title,
  location: null,
  startDate: null,
  endDate: null,
  bullets: ['did a thing', 'did another thing'],
  tools: [],
  confidence,
})

describe('countFacts', () => {
  it('counts nothing for an empty parse', () => {
    expect(countFacts(canonical())).toBe(0)
  })

  it('counts each populated identity field but not the empty ones', () => {
    const parsed = canonical({
      identity: { legalName: 'Ada Lovelace', email: 'ada@example.com', phone: null, location: null, links: [] },
    })
    expect(countFacts(parsed)).toBe(2)
  })

  it('counts individual skills rather than skill groups', () => {
    const parsed = canonical({
      skillGroups: [
        { label: 'Languages', skills: ['Python', 'Rust', 'TypeScript'], confidence: 0.9 },
        { label: 'Cloud', skills: ['AWS'], confidence: 0.9 },
      ],
    })
    expect(countFacts(parsed)).toBe(4)
  })

  it('does not count bullets, which belong to the role that carries them', () => {
    expect(countFacts(canonical({ experience: [experience(0.9)] }))).toBe(1)
  })

  it('sums every group of a realistic resume', () => {
    const parsed = canonical({
      identity: {
        legalName: 'Ada Lovelace',
        email: 'ada@example.com',
        phone: '555-0100',
        location: 'London',
        links: [{ label: 'GitHub', url: 'https://github.com/ada' }],
      },
      experience: [experience(0.82), experience(0.82), experience(0.82)],
      education: [{ institution: 'Uni', degree: null, field: null, startDate: null, endDate: null, details: [], confidence: 0.8 }],
      projects: [{ name: 'Engine', role: null, summary: null, bullets: [], tools: [], links: [], confidence: 0.8 }],
      certifications: [{ name: 'PMP', issuer: null, issuedAt: null, expiresAt: null, credentialUrl: null, confidence: 0.8 }],
      skillGroups: [{ label: 'Languages', skills: ['Python', 'Rust'], confidence: 0.9 }],
    })
    // 4 identity + 1 link + 3 experience + 1 education + 1 project + 1 cert + 2 skills
    expect(countFacts(parsed)).toBe(13)
  })
})

describe('lowConfidenceFacts', () => {
  it('returns nothing when every entry clears the threshold', () => {
    const parsed = canonical({ experience: [experience(LOW_CONFIDENCE_THRESHOLD)] })
    expect(lowConfidenceFacts(parsed)).toEqual([])
  })

  it('flags entries below the merge gate', () => {
    const parsed = canonical({ experience: [experience(0.4, 'Acme', 'Engineer')] })
    expect(lowConfidenceFacts(parsed)).toEqual([{ group: 'Experience', label: 'Engineer at Acme', confidence: 0.4 }])
  })

  it('orders the worst offender first across groups', () => {
    const parsed = canonical({
      experience: [experience(0.6)],
      education: [{ institution: 'Uni', degree: null, field: null, startDate: null, endDate: null, details: [], confidence: 0.2 }],
      skillGroups: [{ label: 'Languages', skills: ['Python'], confidence: 0.45 }],
    })
    expect(lowConfidenceFacts(parsed).map((flag) => flag.confidence)).toEqual([0.2, 0.45, 0.6])
  })

  it('covers every group the parser can emit', () => {
    const parsed = canonical({
      experience: [experience(0.1)],
      education: [{ institution: 'Uni', degree: null, field: null, startDate: null, endDate: null, details: [], confidence: 0.1 }],
      projects: [{ name: 'Engine', role: null, summary: null, bullets: [], tools: [], links: [], confidence: 0.1 }],
      certifications: [{ name: 'PMP', issuer: null, issuedAt: null, expiresAt: null, credentialUrl: null, confidence: 0.1 }],
      skillGroups: [{ label: 'Languages', skills: ['Python'], confidence: 0.1 }],
    })
    expect(lowConfidenceFacts(parsed).map((flag) => flag.group).sort()).toEqual([
      'Certifications',
      'Education',
      'Experience',
      'Projects',
      'Skills',
    ])
  })
})

describe('formatConfidence', () => {
  it('renders a rounded percentage', () => {
    expect(formatConfidence(0.824)).toBe('82%')
    expect(formatConfidence(1)).toBe('100%')
    expect(formatConfidence(0)).toBe('0%')
  })
})
