import { For, Show, createEffect, createSignal, on, onCleanup, onMount } from 'solid-js'
import { SendHorizontal, X } from 'lucide-solid'
import { useProfileStore } from '../../contexts/ProfileStore'
import {
  chatTurns,
  dismissProposal,
  keepProposal,
  loadPreferences,
  sendChatMessage,
  undoProposal,
} from '../../contexts/PreferenceStore'
import { chatOpen, setChatOpen } from './chatDrawer'
import { describeProposal } from './preferenceText'

const EXAMPLES = [
  'Skip anything at Initech',
  'Only remote or hybrid, at least 120k',
  'When they ask about notice period, say 2 weeks',
]

/**
 * A drawer for telling the app how you apply. Every message comes back as
 * proposals; nothing is remembered until you keep it, and everything kept can
 * be edited later in Settings, under Remembered.
 */
export const PreferenceChat = () => {
  const { state: profileState } = useProfileStore()
  const [draft, setDraft] = createSignal('')
  const [pendingKey, setPendingKey] = createSignal<string | null>(null)
  let log: HTMLOListElement | undefined
  let composer: HTMLTextAreaElement | undefined

  const profileId = () => profileState.profile?.id ?? null

  createEffect(
    on(profileId, (id) => {
      if (id) void loadPreferences(id)
    })
  )

  createEffect(
    on(
      () => chatTurns.turns.length,
      () => log?.scrollTo({ top: log.scrollHeight, behavior: 'smooth' })
    )
  )

  createEffect(
    on(chatOpen, (open) => {
      if (open) requestAnimationFrame(() => composer?.focus())
    })
  )

  onMount(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && chatOpen()) setChatOpen(false)
    }
    window.addEventListener('keydown', onKey)
    onCleanup(() => window.removeEventListener('keydown', onKey))
  })

  const send = (text = draft()) => {
    const id = profileId()
    const message = text.trim()
    if (!id || !message || chatTurns.sending) return
    setDraft('')
    void sendChatMessage(id, message)
  }

  const act = async (key: string, action: () => Promise<void>) => {
    setPendingKey(key)
    try {
      await action()
    } finally {
      setPendingKey(null)
    }
  }

  return (
    <>
      <div class="pref-scrim" classList={{ open: chatOpen() }} onClick={() => setChatOpen(false)} aria-hidden="true" />
      <aside class="pref-chat" classList={{ open: chatOpen() }} aria-label="Ask anything" aria-hidden={!chatOpen()} inert={!chatOpen()}>
        <header class="pref-chat-head">
          <div class="pref-chat-title">
            <strong>Ask anything</strong>
            <span>Kept answers and filters apply to every run</span>
          </div>
          <button class="pref-chat-icon" type="button" onClick={() => setChatOpen(false)} aria-label="Close">
            <X size={16} aria-hidden="true" />
          </button>
        </header>

        <ol class="pref-chat-log" ref={log} aria-live="polite">
          <Show when={chatTurns.turns.length === 0}>
            <li class="pref-chat-empty">
              <p>Say what to skip, what you want, or how to answer a question. Try one:</p>
              <For each={EXAMPLES}>
                {(example) => (
                  <button class="pref-chat-example" type="button" disabled={!profileId()} onClick={() => send(example)}>
                    {example}
                  </button>
                )}
              </For>
            </li>
          </Show>
          <For each={chatTurns.turns}>
            {(turn) => (
              <li class={`pref-turn ${turn.role}`}>
                <p class="pref-bubble">{turn.text}</p>
                <For each={turn.proposals}>
                  {(proposal, index) => {
                    const text = describeProposal(proposal)
                    const key = () => `${turn.id}:${index()}`
                    const outcome = () => turn.outcomes[index()]
                    const id = () => profileId() ?? ''
                    return (
                      <div class="pref-proposal" classList={{ kept: !!outcome() && outcome() !== 'dismissed', dismissed: outcome() === 'dismissed' }}>
                        <strong>{text.title}</strong>
                        <span>{text.detail}</span>
                        <div class="pref-proposal-actions">
                          <Show
                            when={outcome()}
                            fallback={
                              <>
                                <button class="btn-wax" type="button" disabled={pendingKey() !== null} onClick={() => void act(key(), () => keepProposal(id(), turn.id, index()))}>
                                  {pendingKey() === key() ? 'Keeping' : 'Keep'}
                                </button>
                                <button class="btn-quiet" type="button" disabled={pendingKey() !== null} onClick={() => dismissProposal(turn.id, index())}>
                                  Not this
                                </button>
                              </>
                            }
                          >
                            <span class="pref-proposal-state">{outcome() === 'dismissed' ? 'Left out' : 'Kept'}</span>
                            <button class="btn-mono" type="button" disabled={pendingKey() !== null} onClick={() => void act(key(), () => undoProposal(id(), turn.id, index()))}>
                              Undo
                            </button>
                          </Show>
                        </div>
                      </div>
                    )
                  }}
                </For>
              </li>
            )}
          </For>
          <Show when={chatTurns.sending}>
            <li class="pref-turn assistant">
              <p class="pref-bubble pref-thinking">Reading that</p>
            </li>
          </Show>
        </ol>

        <form
          class="pref-chat-composer"
          onSubmit={(event) => {
            event.preventDefault()
            send()
          }}
        >
          <textarea
            ref={composer}
            rows={2}
            maxLength={4000}
            placeholder={profileId() ? 'Skip staffing agencies…' : 'Finish onboarding to start'}
            disabled={!profileId()}
            value={draft()}
            onInput={(event) => setDraft(event.currentTarget.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter' && !event.shiftKey) {
                event.preventDefault()
                send()
              }
            }}
            aria-label="Message"
          />
          <button class="pref-send" type="submit" disabled={!profileId() || !draft().trim() || chatTurns.sending} aria-label="Send">
            <SendHorizontal size={16} aria-hidden="true" />
          </button>
        </form>
      </aside>
    </>
  )
}
