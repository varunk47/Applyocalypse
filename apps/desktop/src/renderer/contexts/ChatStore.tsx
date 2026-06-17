import { createStore } from 'solid-js/store'
import type { ChatMessage } from '@applyocalypse/shared-types'

export interface ChatState {
  messages: ChatMessage[]
  loading: boolean
}

export type ChatAction =
  | { type: 'LOADED'; messages: ChatMessage[] }
  | { type: 'APPENDED'; message: ChatMessage }
  | { type: 'CARD_RUN_STATE'; messageId: string; runId: string; status: string }

export const chatReducer = (state: ChatState, action: ChatAction): ChatState => {
  switch (action.type) {
    case 'LOADED':
      return { ...state, messages: action.messages, loading: false }
    case 'APPENDED':
      return { ...state, messages: [...state.messages, action.message] }
    case 'CARD_RUN_STATE':
      return {
        ...state,
        messages: state.messages.map((m) =>
          m.id === action.messageId
            ? { ...m, metadata: { ...(m.metadata as object), runId: action.runId, status: action.status } }
            : m
        )
      }
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
    if (status === 'QUEUED') queued++
    else if (status === 'COMPLETED' || status === 'SUBMITTED') completed++
    else if (status === 'FAILED' || status === 'CANCELLED') failed++
    // Everything in-flight (PREPARING, ANALYZING, TAILORING_RESUME,
    // GENERATING_COVER_LETTER, READY_FOR_REVIEW, WAITING_FOR_USER_EDIT,
    // RUNNING_AUTOMATION, BLOCKED_OTP, READY_TO_SUBMIT, PAUSED) is active work.
    else running++
  }
  return { total: cards.length, queued, running, completed, failed }
}

const [chatState, setChatState] = createStore<ChatState>({ messages: [], loading: false })

export { chatState }

export const chatDispatch = (action: ChatAction): void => {
  const next = chatReducer({ messages: chatState.messages, loading: chatState.loading }, action)
  setChatState(next)
}
