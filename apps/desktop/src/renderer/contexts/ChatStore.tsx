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

const [chatState, setChatState] = createStore<ChatState>({ messages: [], loading: false })

export { chatState }

export const chatDispatch = (action: ChatAction): void => {
  const next = chatReducer({ messages: chatState.messages, loading: chatState.loading }, action)
  setChatState(next)
}
