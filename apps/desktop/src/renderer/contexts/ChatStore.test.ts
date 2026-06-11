import { describe, expect, it } from 'vitest'
import { chatReducer } from './ChatStore'
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
