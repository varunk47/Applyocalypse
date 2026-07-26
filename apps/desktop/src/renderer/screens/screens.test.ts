// Smoke tests for screen-level pure logic (no DOM/store required)
import { describe, it, expect } from 'vitest'
import { parseJobIntake } from '../features/intake/parseJobIntake'
import { REVIEW_INSTRUCTIONS } from '../features/run-console/reviewInstructions'
import { deriveLegalName } from '../features/onboarding/onboardingUtils'

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

  it('extracts a URL with trailing text on the same line', () => {
    const items = parseJobIntake('https://company.wd5.myworkdayjobs.com/en-US/careers/job/12345 (Remote)')
    const urls = items.filter((i) => i.sourceKind === 'URL')
    expect(urls).toHaveLength(1)
    expect(urls[0]?.sourceValue).toBe('https://company.wd5.myworkdayjobs.com/en-US/careers/job/12345')
  })

  it('strips trailing punctuation pasted after a URL', () => {
    const items = parseJobIntake('https://jobs.example.com/apply/12345),')
    expect(items[0]?.sourceKind).toBe('URL')
    expect(items[0]?.sourceValue).toBe('https://jobs.example.com/apply/12345')
  })

  it('keeps a mid-sentence URL mention as TEXT', () => {
    const items = parseJobIntake('Apply on our site at https://jobs.example.com/apply/12345 today')
    expect(items).toHaveLength(1)
    expect(items[0]?.sourceKind).toBe('TEXT')
  })

  it('detects TEXT kind for a job description paste', () => {
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

describe('RunConsoleScreen review instructions', () => {
  it('covers every review gate type the console renders', () => {
    const expectedTypes = [
      'OTP', 'CAPTCHA', 'MFA', 'LOGIN', 'PORTAL_ENTRY', 'PORTAL_STEP',
      'AMBIGUOUS_QUESTION', 'ANSWER', 'DOCUMENT', 'FINAL_SUBMIT',
    ]
    for (const type of expectedTypes) {
      expect(REVIEW_INSTRUCTIONS[type], `missing instruction for ${type}`).toBeTruthy()
    }
    expect(Object.keys(REVIEW_INSTRUCTIONS)).toHaveLength(expectedTypes.length)
  })

  it('has an OTP instruction mentioning the code', () => {
    expect(REVIEW_INSTRUCTIONS['OTP']).toContain('code')
  })

  it('has a CAPTCHA instruction mentioning the challenge', () => {
    expect(REVIEW_INSTRUCTIONS['CAPTCHA']).toContain('challenge')
  })

  it('returns undefined for unknown review types', () => {
    expect(REVIEW_INSTRUCTIONS['UNKNOWN_TYPE']).toBeUndefined()
  })
})

// ── OnboardingScreen: legalName derivation ────────────────────────────────────

describe('OnboardingScreen deriveLegalName', () => {
  it('combines first and last name', () => {
    expect(deriveLegalName('Grace', 'Hopper', '')).toBe('Grace Hopper')
  })

  it('trims extra whitespace', () => {
    expect(deriveLegalName('  Ada ', ' Lovelace ', '')).toBe('Ada Lovelace')
  })

  it('falls back to the fallback name when both parts are empty', () => {
    expect(deriveLegalName('', '', 'Fallback Name')).toBe('Fallback Name')
  })

  it('works with first name only', () => {
    expect(deriveLegalName('Cher', '', '')).toBe('Cher')
  })
})
