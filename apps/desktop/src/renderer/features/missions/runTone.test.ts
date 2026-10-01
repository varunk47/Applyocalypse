import { describe, expect, it } from 'vitest'
import { runStage, runTone, statusLabel } from './runTone'

describe('runTone', () => {
  it.each([
    ['READY_TO_SUBMIT', 'sign'],
    ['READY_FOR_REVIEW', 'sign'],
    ['WAITING_FOR_USER_EDIT', 'sign'],
    ['BLOCKED_OTP', 'needs'],
    ['BLOCKED_CAPTCHA', 'needs'],
    ['BLOCKED_MFA', 'needs'],
    ['BLOCKED_AMBIGUOUS_QUESTION', 'needs'],
    ['PAUSED', 'needs'],
    ['PARSING_JD', 'working'],
    ['TAILORING_RESUME', 'working'],
    ['RUNNING_AUTOMATION', 'working'],
    ['PENDING', 'queued'],
    ['SUBMITTED', 'sent'],
    ['COMPLETED', 'sent'],
    ['FAILED', 'failed'],
    ['CANCELLED', 'withdrawn'],
  ])('%s is %s', (status, tone) => {
    expect(runTone(status)).toBe(tone)
  })

  it('treats an unknown status as working rather than asking for the user', () => {
    expect(runTone('SOMETHING_NEW')).toBe('working')
  })
})

describe('runStage', () => {
  it.each([
    ['PARSING_JD', { done: 0, current: 0 }],
    ['TAILORING_RESUME', { done: 1, current: 1 }],
    ['READY_FOR_REVIEW', { done: 1, current: 1 }],
    ['RUNNING_AUTOMATION', { done: 2, current: 2 }],
    ['BLOCKED_OTP', { done: 2, current: 2 }],
    ['READY_TO_SUBMIT', { done: 3, current: 3 }],
    ['SUBMITTED', { done: 5, current: null }],
    ['FAILED', { done: 0, current: null }],
  ])('%s', (status, stage) => {
    expect(runStage(status)).toEqual(stage)
  })
})

describe('statusLabel', () => {
  it.each([
    ['SUBMITTED', 'Sent'],
    ['COMPLETED', 'Sent'],
    ['FAILED', 'Failed'],
    ['CANCELLED', 'Withdrawn'],
    ['READY_TO_SUBMIT', 'Ready to sign'],
    ['BLOCKED_OTP', 'Needs a code'],
    ['PENDING', 'Queued'],
    ['TAILORING_RESUME', 'Tailoring'],
    ['SOMETHING_NEW', 'In progress'],
  ])('%s reads as %s', (status, label) => {
    expect(statusLabel(status)).toBe(label)
  })
})
