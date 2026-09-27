import { createStore } from 'solid-js/store'
import type {
  JobFilterDto,
  PreferenceChatReplyDto,
  PreferenceProposalDto,
  PreferenceRuleDto,
  ProfileAddressDto,
} from '@applyocalypse/ipc-contracts'

/** What the app remembers about how the user applies: answers, filters and addresses. */
export interface PreferenceState {
  rules: PreferenceRuleDto[]
  filters: JobFilterDto[]
  addresses: ProfileAddressDto[]
}

export type SavedRef = { type: PreferenceProposalDto['type']; id: string }

export interface ChatTurn {
  id: string
  role: 'user' | 'assistant'
  text: string
  proposals: PreferenceProposalDto[]
  /** Proposal index to what it was saved as, or 'dismissed'. */
  outcomes: Record<number, SavedRef | 'dismissed'>
}

const [preferenceState, setPreferenceState] = createStore<PreferenceState>({ rules: [], filters: [], addresses: [] })
const [chatTurns, setChatTurns] = createStore<{ turns: ChatTurn[]; sending: boolean }>({ turns: [], sending: false })

export { chatTurns, preferenceState }

export const loadPreferences = async (profileId: string): Promise<void> => {
  const api = window.applyocalypse
  const [rules, filters, addresses] = await Promise.all([
    api.preferenceRules.list(profileId),
    api.jobFilters.list(profileId),
    api.profileAddresses.list(profileId),
  ])
  setPreferenceState({ rules: rules.items, filters: filters.items, addresses: addresses.items })
}

const saveProposal = async (profileId: string, proposal: PreferenceProposalDto): Promise<SavedRef> => {
  const api = window.applyocalypse
  switch (proposal.type) {
    case 'answer_rule': {
      const { question, answer, conditions } = proposal
      return { type: proposal.type, id: (await api.preferenceRules.upsert({ profileId, question, answer, conditions })).id }
    }
    case 'job_filter':
      return { type: proposal.type, id: (await api.jobFilters.upsert({ profileId, kind: proposal.kind, value: proposal.value })).id }
    case 'address': {
      const { type: _type, ...address } = proposal
      return { type: proposal.type, id: (await api.profileAddresses.upsert({ profileId, ...address })).id }
    }
  }
}

export const forgetPreference = async (profileId: string, ref: SavedRef): Promise<void> => {
  const api = window.applyocalypse
  if (ref.type === 'answer_rule') await api.preferenceRules.delete(ref.id)
  if (ref.type === 'job_filter') await api.jobFilters.delete(ref.id)
  if (ref.type === 'address') await api.profileAddresses.delete(ref.id)
  await loadPreferences(profileId)
}

const setOutcome = (turnId: string, index: number, outcome: SavedRef | 'dismissed' | undefined) =>
  setChatTurns('turns', (turn) => turn.id === turnId, 'outcomes', index, outcome as SavedRef | 'dismissed')

export const keepProposal = async (profileId: string, turnId: string, index: number): Promise<void> => {
  const turn = chatTurns.turns.find((t) => t.id === turnId)
  const proposal = turn?.proposals[index]
  if (!proposal) return
  setOutcome(turnId, index, await saveProposal(profileId, proposal))
  await loadPreferences(profileId)
}

export const dismissProposal = (turnId: string, index: number): void => setOutcome(turnId, index, 'dismissed')

export const undoProposal = async (profileId: string, turnId: string, index: number): Promise<void> => {
  const outcome = chatTurns.turns.find((t) => t.id === turnId)?.outcomes[index]
  if (outcome && outcome !== 'dismissed') await forgetPreference(profileId, outcome)
  setChatTurns('turns', (turn) => turn.id === turnId, 'outcomes', (outcomes) => {
    const { [index]: _removed, ...rest } = outcomes
    return rest
  })
}

const appendTurn = (role: ChatTurn['role'], text: string, proposals: PreferenceProposalDto[] = []): void =>
  setChatTurns('turns', (turns) => [...turns, { id: crypto.randomUUID(), role, text, proposals, outcomes: {} }])

export const sendChatMessage = async (profileId: string, message: string): Promise<void> => {
  appendTurn('user', message)
  setChatTurns('sending', true)
  try {
    const reply: PreferenceChatReplyDto = await window.applyocalypse.preferenceChat.send({ profileId, message })
    appendTurn('assistant', reply.reply, reply.proposals)
  } catch (error) {
    appendTurn('assistant', error instanceof Error ? `That did not go through: ${error.message}` : 'That did not go through.')
  } finally {
    setChatTurns('sending', false)
  }
}
