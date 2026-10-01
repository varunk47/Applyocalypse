/**
 * How a run looks on Missions. The tone picks the tile colour: gold when it is
 * the user's turn to sign, garnet when a run is stuck on them, emerald once
 * sent, and plain white while the machine is working.
 */
export type RunTone = 'sign' | 'needs' | 'working' | 'queued' | 'sent' | 'failed' | 'withdrawn'

const TONES: Record<string, RunTone> = {
  READY_TO_SUBMIT: 'sign',
  READY_FOR_REVIEW: 'sign',
  WAITING_FOR_USER_EDIT: 'sign',
  BLOCKED_OTP: 'needs',
  BLOCKED_CAPTCHA: 'needs',
  BLOCKED_MFA: 'needs',
  BLOCKED_AMBIGUOUS_QUESTION: 'needs',
  PAUSED: 'needs',
  PENDING: 'queued',
  SUBMITTED: 'sent',
  COMPLETED: 'sent',
  FAILED: 'failed',
  CANCELLED: 'withdrawn',
}

export const runTone = (status: string): RunTone => TONES[status] ?? 'working'

export const STAGES = ['Read', 'Tailor', 'Fill', 'Sign', 'Sent'] as const

/** `done` stages are filled; `current` is the one in progress, if any. */
export type RunStage = { done: number; current: number | null }

const STAGE_BY_STATUS: Record<string, RunStage> = {
  READY_FOR_REVIEW: { done: 1, current: 1 },
  WAITING_FOR_USER_EDIT: { done: 1, current: 1 },
  TAILORING_RESUME: { done: 1, current: 1 },
  GENERATING_COVER_LETTER: { done: 1, current: 1 },
  RUNNING_AUTOMATION: { done: 2, current: 2 },
  BLOCKED_OTP: { done: 2, current: 2 },
  BLOCKED_CAPTCHA: { done: 2, current: 2 },
  BLOCKED_MFA: { done: 2, current: 2 },
  BLOCKED_AMBIGUOUS_QUESTION: { done: 2, current: 2 },
  PAUSED: { done: 2, current: 2 },
  READY_TO_SUBMIT: { done: 3, current: 3 },
  SUBMITTED: { done: 5, current: null },
  COMPLETED: { done: 5, current: null },
  FAILED: { done: 0, current: null },
  CANCELLED: { done: 0, current: null },
}

export const runStage = (status: string): RunStage => STAGE_BY_STATUS[status] ?? { done: 0, current: 0 }

const LABELS: Record<string, string> = {
  SUBMITTED: 'Sent',
  COMPLETED: 'Sent',
  FAILED: 'Failed',
  CANCELLED: 'Withdrawn',
  READY_TO_SUBMIT: 'Ready to sign',
  READY_FOR_REVIEW: 'Review documents',
  WAITING_FOR_USER_EDIT: 'Waiting on you',
  BLOCKED_OTP: 'Needs a code',
  BLOCKED_CAPTCHA: 'Needs a human check',
  BLOCKED_MFA: 'Needs a sign-in approval',
  BLOCKED_AMBIGUOUS_QUESTION: 'Needs an answer',
  PAUSED: 'Paused',
  PENDING: 'Queued',
  CLAIMED: 'Starting',
  PREPARING: 'Starting',
  PARSING_JD: 'Reading the posting',
  ANALYZING: 'Checking the fit',
  TAILORING_RESUME: 'Tailoring',
  GENERATING_COVER_LETTER: 'Writing the letter',
  RUNNING_AUTOMATION: 'Filling the portal',
}

/** A short status in plain words, for lists and pills. */
export const statusLabel = (status: string): string => LABELS[status] ?? 'In progress'
