// Smoke tests for screen-level pure logic (no DOM/store required)
import { describe, it, expect } from 'vitest'
import { parseJobIntake } from '../features/intake/parseJobIntake'

// ── IntakeScreen: URL chip detection ──────────────────────────────────────────

describe('IntakeScreen URL detection', () => {
  it('detects single URL', () => {
    const items = parseJobIntake('https://jobs.example.com/apply/12345')
    expect(items).toHaveLength(1)
    expect(items[0]?.sourceKind).toBe('URL')
    expect(items[0]?.sourceValue).toBe('https://jobs.example.com/apply/12345')
  })

  it('detects multiple URLs', () => {
    const items = parseJobIntake('https://a.com/1\nhttps://b.com/2')
    const urls = items.filter((i) => i.sourceKind === 'URL')
    expect(urls).toHaveLength(2)
  })

  it('detects TEXT kind for job description paste', () => {
    const items = parseJobIntake('We are looking for a senior engineer...')
    expect(items[0]?.sourceKind).toBe('TEXT')
  })

  it('returns empty array for blank input', () => {
    expect(parseJobIntake('')).toHaveLength(0)
    expect(parseJobIntake('   ')).toHaveLength(0)
  })

  it('handles mixed URLs and text', () => {
    const items = parseJobIntake('https://jobs.co/1\nSome extra context line')
    expect(items.some((i) => i.sourceKind === 'URL')).toBe(true)
    expect(items.some((i) => i.sourceKind === 'TEXT')).toBe(true)
  })
})

// ── RunConsoleScreen: review instruction lookup ───────────────────────────────

const REVIEW_INSTRUCTIONS: Record<string, string> = {
  OTP:                'Enter the code in the portal, then mark handled.',
  CAPTCHA:            'Complete the challenge in the portal, then resume.',
  MFA:                'Approve the sign-in challenge, then resume.',
  FINAL_SUBMIT:       'Final submission is blocked until approved.',
}

describe('RunConsoleScreen review instructions', () => {
  it('returns correct instruction for OTP', () => {
    expect(REVIEW_INSTRUCTIONS['OTP']).toContain('code')
  })

  it('returns correct instruction for CAPTCHA', () => {
    expect(REVIEW_INSTRUCTIONS['CAPTCHA']).toContain('challenge')
  })

  it('returns undefined for unknown review type', () => {
    expect(REVIEW_INSTRUCTIONS['UNKNOWN_TYPE']).toBeUndefined()
  })
})

// ── OverviewScreen: stat calculation logic ────────────────────────────────────

const computeStats = (
  queueItems: { status: string }[],
  runs: { status: string }[]
) => ({
  total:     queueItems.length + runs.length,
  pending:   queueItems.filter((i) => ['QUEUED', 'PREPARING'].includes(i.status)).length,
  completed: runs.filter((r) => r.status === 'COMPLETED').length,
  failed:    runs.filter((r) => ['FAILED', 'CANCELLED'].includes(r.status)).length,
})

describe('OverviewScreen stat computation', () => {
  it('totals queue + runs', () => {
    const stats = computeStats([{ status: 'QUEUED' }], [{ status: 'COMPLETED' }])
    expect(stats.total).toBe(2)
  })

  it('counts pending correctly', () => {
    const stats = computeStats(
      [{ status: 'QUEUED' }, { status: 'PREPARING' }, { status: 'RUNNING' }],
      []
    )
    expect(stats.pending).toBe(2)
  })

  it('counts completed and failed separately', () => {
    const stats = computeStats([], [
      { status: 'COMPLETED' },
      { status: 'FAILED' },
      { status: 'CANCELLED' },
      { status: 'RUNNING' },
    ])
    expect(stats.completed).toBe(1)
    expect(stats.failed).toBe(2)
  })

  it('returns zeros for empty state', () => {
    const stats = computeStats([], [])
    expect(stats.total).toBe(0)
    expect(stats.pending).toBe(0)
  })
})

// ── OnboardingScreen: legalName derivation ───────────────────────────────────

import { deriveLegalName } from '../features/onboarding/onboardingUtils'

describe('OnboardingScreen deriveLegalName', () => {
  it('combines first and last name', () => {
    expect(deriveLegalName('Grace', 'Hopper', '')).toBe('Grace Hopper')
  })

  it('trims extra whitespace', () => {
    expect(deriveLegalName('  Ada  ', '  Lovelace  ', '')).toBe('Ada Lovelace')
  })

  it('falls back to fallback when both are empty', () => {
    expect(deriveLegalName('', '', 'Fallback Name')).toBe('Fallback Name')
  })

  it('works with first name only', () => {
    expect(deriveLegalName('Cher', '', '')).toBe('Cher')
  })
})

// ── QueueScreen: run-for-queue-item lookup ────────────────────────────────────

describe('QueueScreen run lookup', () => {
  const runs = [
    { id: 'run-1', queueItemId: 'qi-a', status: 'RUNNING' },
    { id: 'run-2', queueItemId: 'qi-b', status: 'COMPLETED' },
  ]

  const runForQueueItem = (queueItemId: string) =>
    runs.find((r) => r.queueItemId === queueItemId) ?? null

  it('finds run for known queue item', () => {
    expect(runForQueueItem('qi-a')?.id).toBe('run-1')
  })

  it('returns null for unknown queue item', () => {
    expect(runForQueueItem('qi-unknown')).toBeNull()
  })
})
