import { describe, expect, it } from 'vitest'
import { chatReducer, getBatchJobCards, getBatchProgress } from './ChatStore'
import type { ChatState } from './ChatStore'
import type { ChatMessage } from '@applyocalypse/shared-types'

const makeMessage = (overrides?: Partial<ChatMessage>): ChatMessage => ({
  id: 'msg-1',
  batchId: null,
  runId: null,
  jobId: null,
  role: 'USER',
  kind: 'TEXT',
  content: 'hello',
  metadata: {},
  createdAt: '2026-01-01T00:00:00.000Z',
  ...overrides
})

const empty: ChatState = { messages: [], loading: false }

describe('chatReducer', () => {
  it('LOADED sets messages and clears loading flag', () => {
    const msg = makeMessage()
    const next = chatReducer({ messages: [], loading: true }, { type: 'LOADED', messages: [msg] })
    expect(next.messages).toEqual([msg])
    expect(next.loading).toBe(false)
  })

  it('APPENDED adds message to end of list', () => {
    const msg1 = makeMessage({ id: 'msg-1' })
    const msg2 = makeMessage({ id: 'msg-2', content: 'world' })
    const s1 = chatReducer(empty, { type: 'LOADED', messages: [msg1] })
    const s2 = chatReducer(s1, { type: 'APPENDED', message: msg2 })
    expect(s2.messages).toHaveLength(2)
    expect(s2.messages[1]).toEqual(msg2)
  })

  it('LOADED with empty array clears existing messages', () => {
    const s1 = chatReducer(empty, { type: 'LOADED', messages: [makeMessage()] })
    const s2 = chatReducer(s1, { type: 'LOADED', messages: [] })
    expect(s2.messages).toHaveLength(0)
  })

  it('APPENDED preserves loading flag', () => {
    const s = chatReducer({ messages: [], loading: true }, { type: 'APPENDED', message: makeMessage() })
    expect(s.loading).toBe(true)
  })

  it('LOADED preserves other fields from state', () => {
    const msg = makeMessage({ role: 'SYSTEM', kind: 'JOB_CARD' })
    const s = chatReducer(empty, { type: 'LOADED', messages: [msg] })
    expect(s.messages[0]?.role).toBe('SYSTEM')
    expect(s.messages[0]?.kind).toBe('JOB_CARD')
  })
})

describe('getBatchJobCards', () => {
  it('returns only JOB_CARD messages with the matching batchId', () => {
    const batchId = 'batch-abc'
    const msgs: ChatMessage[] = [
      makeMessage({ id: '1', kind: 'BATCH_HEADER', role: 'SYSTEM', batchId }),
      makeMessage({ id: '2', kind: 'JOB_CARD', role: 'SYSTEM', batchId }),
      makeMessage({ id: '3', kind: 'JOB_CARD', role: 'SYSTEM', batchId }),
      makeMessage({ id: '4', kind: 'JOB_CARD', role: 'SYSTEM', batchId: 'other-batch' }),
      makeMessage({ id: '5', kind: 'TEXT', role: 'USER' }),
    ]
    const cards = getBatchJobCards(msgs, batchId)
    expect(cards).toHaveLength(2)
    expect(cards.every((m) => m.batchId === batchId && m.kind === 'JOB_CARD')).toBe(true)
  })
})

describe('getBatchProgress', () => {
  const batchId = 'batch-xyz'

  const makeJobCard = (id: string, status: string): ChatMessage =>
    makeMessage({ id, kind: 'JOB_CARD', role: 'SYSTEM', batchId, metadata: { status } })

  it('counts 5 queued cards for a fresh 5-link batch', () => {
    const msgs: ChatMessage[] = [
      makeMessage({ id: 'header', kind: 'BATCH_HEADER', role: 'SYSTEM', batchId }),
      makeJobCard('c1', 'QUEUED'),
      makeJobCard('c2', 'QUEUED'),
      makeJobCard('c3', 'QUEUED'),
      makeJobCard('c4', 'QUEUED'),
      makeJobCard('c5', 'QUEUED'),
    ]
    const p = getBatchProgress(msgs, batchId)
    expect(p.total).toBe(5)
    expect(p.queued).toBe(5)
    expect(p.running).toBe(0)
    expect(p.completed).toBe(0)
  })

  it('aggregates mixed statuses correctly', () => {
    const msgs: ChatMessage[] = [
      makeJobCard('c1', 'COMPLETED'),
      makeJobCard('c2', 'RUNNING_AUTOMATION'),
      makeJobCard('c3', 'QUEUED'),
      makeJobCard('c4', 'FAILED'),
      makeJobCard('c5', 'PAUSED'),
    ]
    const p = getBatchProgress(msgs, batchId)
    expect(p.total).toBe(5)
    expect(p.completed).toBe(1)
    expect(p.running).toBe(2)
    expect(p.queued).toBe(1)
    expect(p.failed).toBe(1)
  })

  it('returns zeros for an empty batch', () => {
    const p = getBatchProgress([], batchId)
    expect(p.total).toBe(0)
    expect(p.queued).toBe(0)
  })
})
