import { createStore } from 'solid-js/store'
import type { ChatMessage } from '@applyocalypse/shared-types'

export interface ChatState {
  messages: ChatMessage[]
  loading: boolean
}

export type ChatAction =
  | { type: 'LOADED'; messages: ChatMessage[] }
  | { type: 'APPENDED'; message: ChatMessage }

export const chatReducer = (state: ChatState, action: ChatAction): ChatState => {
  switch (action.type) {
    case 'LOADED':
      return { ...state, messages: action.messages, loading: false }
    case 'APPENDED':
      return { ...state, messages: [...state.messages, action.message] }
  }
}

export const getBatchJobCards = (messages: ChatMessage[], batchId: string): ChatMessage[] =>
  messages.filter((m) => m.kind === 'JOB_CARD' && m.batchId === batchId)

export const getBatchProgress = (
  messages: ChatMessage[],
  batchId: string
): { total: number; queued: number; running: number; completed: number; failed: number } => {
  const cards = getBatchJobCards(messages, batchId)
  let queued = 0, running = 0, completed = 0, failed = 0
  for (const m of cards) {
    const status = (m.metadata as { status?: string }).status ?? 'QUEUED'
    if (status === 'QUEUED' || status === 'PREPARING') queued++
    else if (status === 'RUNNING_AUTOMATION' || status === 'PAUSED') running++
    else if (status === 'COMPLETED') completed++
    else if (status === 'FAILED' || status === 'CANCELLED') failed++
    else queued++
  }
  return { total: cards.length, queued, running, completed, failed }
}

const [chatState, setChatState] = createStore<ChatState>({ messages: [], loading: false })

export { chatState }

export const chatDispatch = (action: ChatAction): void => {
  const next = chatReducer({ messages: chatState.messages, loading: chatState.loading }, action)
  setChatState(next)
}
