import { describe, expect, it } from 'vitest'
import { reconcileCards, hasLiveCards, extractCardRefs } from './chatLiveSync'
import type { CardRef, RunRow } from './chatLiveSync'
import type { ChatMessage } from '@applyocalypse/shared-types'

describe('reconcileCards', () => {
  it('maps queueItemId -> run and emits the run id + status for changed cards', () => {
    const cards: CardRef[] = [{ messageId: 'm1', queueItemId: 'q1', status: 'QUEUED' }]
    const runs: RunRow[] = [{ id: 'run-1', queueItemId: 'q1', status: 'TAILORING_RESUME' }]
    expect(reconcileCards(cards, runs)).toEqual([{ messageId: 'm1', runId: 'run-1', status: 'TAILORING_RESUME' }])
  })

  it('ignores cards without a queueItemId', () => {
    const cards: CardRef[] = [{ messageId: 'm1', status: 'QUEUED' }]
    const runs: RunRow[] = [{ id: 'run-1', queueItemId: 'q1', status: 'RUNNING_AUTOMATION' }]
    expect(reconcileCards(cards, runs)).toEqual([])
  })

  it('ignores cards whose queueItem has no matching run yet', () => {
    const cards: CardRef[] = [{ messageId: 'm1', queueItemId: 'q-pending', status: 'QUEUED' }]
    const runs: RunRow[] = [{ id: 'run-1', queueItemId: 'q1', status: 'RUNNING_AUTOMATION' }]
    expect(reconcileCards(cards, runs)).toEqual([])
  })

  it('emits nothing when the card already matches the run (runId and status current)', () => {
    const cards: CardRef[] = [{ messageId: 'm1', queueItemId: 'q1', runId: 'run-1', status: 'RUNNING_AUTOMATION' }]
    const runs: RunRow[] = [{ id: 'run-1', queueItemId: 'q1', status: 'RUNNING_AUTOMATION' }]
    expect(reconcileCards(cards, runs)).toEqual([])
  })

  it('emits an update when only the status changed', () => {
    const cards: CardRef[] = [{ messageId: 'm1', queueItemId: 'q1', runId: 'run-1', status: 'RUNNING_AUTOMATION' }]
    const runs: RunRow[] = [{ id: 'run-1', queueItemId: 'q1', status: 'READY_FOR_REVIEW' }]
    expect(reconcileCards(cards, runs)).toEqual([{ messageId: 'm1', runId: 'run-1', status: 'READY_FOR_REVIEW' }])
  })
})

describe('hasLiveCards', () => {
  it('is false when every card is terminal', () => {
    const cards: CardRef[] = [
      { messageId: 'm1', queueItemId: 'q1', status: 'COMPLETED' },
      { messageId: 'm2', queueItemId: 'q2', status: 'FAILED' },
      { messageId: 'm3', queueItemId: 'q3', status: 'CANCELLED' },
      { messageId: 'm4', queueItemId: 'q4', status: 'SUBMITTED' },
    ]
    expect(hasLiveCards(cards)).toBe(false)
  })

  it('is true when at least one non-terminal card has a queueItemId', () => {
    const cards: CardRef[] = [
      { messageId: 'm1', queueItemId: 'q1', status: 'COMPLETED' },
      { messageId: 'm2', queueItemId: 'q2', status: 'QUEUED' },
    ]
    expect(hasLiveCards(cards)).toBe(true)
  })

  it('treats a missing status as live (QUEUED default)', () => {
    expect(hasLiveCards([{ messageId: 'm1', queueItemId: 'q1' }])).toBe(true)
  })

  it('ignores cards without a queueItemId', () => {
    expect(hasLiveCards([{ messageId: 'm1', status: 'QUEUED' }])).toBe(false)
  })
})

describe('extractCardRefs', () => {
  const makeMessage = (overrides?: Partial<ChatMessage>): ChatMessage => ({
    id: 'msg-1',
    batchId: null,
    runId: null,
    jobId: null,
    role: 'SYSTEM',
    kind: 'JOB_CARD',
    content: '',
    metadata: {},
    createdAt: '2026-01-01T00:00:00.000Z',
    ...overrides
  })

  it('extracts refs only from JOB_CARD messages, pulling queueItemId/runId/status from metadata', () => {
    const messages: ChatMessage[] = [
      makeMessage({ id: 'text', kind: 'TEXT', metadata: {} }),
      makeMessage({ id: 'card', metadata: { queueItemId: 'q1', runId: 'run-1', status: 'RUNNING_AUTOMATION' } }),
    ]
    expect(extractCardRefs(messages)).toEqual([
      { messageId: 'card', queueItemId: 'q1', runId: 'run-1', status: 'RUNNING_AUTOMATION' },
    ])
  })

  it('yields undefined fields for a card with empty metadata', () => {
    expect(extractCardRefs([makeMessage({ id: 'card', metadata: {} })])).toEqual([
      { messageId: 'card', queueItemId: undefined, runId: undefined, status: undefined },
    ])
  })
})
