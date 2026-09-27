import { describe, expect, it } from 'vitest'
import { describeAddress, describeConditions, describeFilter, describeProposal } from './preferenceText'

describe('preference text', () => {
  it.each([
    ['skip_company', 'Initech', 'Never apply to Initech'],
    ['skip_keyword', 'clearance', 'Skip jobs that mention "clearance"'],
    ['min_salary', '120000', 'Skip jobs that pay under 120,000'],
    ['work_arrangement', 'remote', 'Remote jobs are fine'],
    ['place', 'Denver', 'Onsite and hybrid jobs in Denver are fine'],
  ] as const)('describes a %s filter', (kind, value, expected) => {
    expect(describeFilter(kind, value)).toBe(expected)
  })

  it('describes an address with and without a street or label', () => {
    expect(describeAddress({ label: 'Home', addressLine1: '1 Beacon St', city: 'Boston', state: 'MA', postalCode: '02108' })).toBe(
      'Home: 1 Beacon St, Boston, MA 02108'
    )
    expect(describeAddress({ label: '', addressLine1: '', city: 'Denver', state: '', postalCode: '' })).toBe('Denver')
  })

  it('describes the jobs an answer applies to', () => {
    expect(describeConditions({})).toBe('For every job')
    expect(describeConditions({ company: 'Initech', location: 'GA' })).toBe('Only for jobs at Initech, in GA')
  })

  it('never uses an em dash', () => {
    const text = describeProposal({ type: 'answer_rule', question: 'Notice period', answer: '2 weeks', conditions: {} })
    expect(`${text.title} ${text.detail}`).not.toContain('—')
  })
})
