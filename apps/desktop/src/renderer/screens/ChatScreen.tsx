import { createSignal, For, onMount, createEffect, Show } from 'solid-js'
import { createStore } from 'solid-js/store'
import { Send } from 'lucide-solid'
import { chatState, chatDispatch } from '../contexts/ChatStore'
import { JobCard } from '../features/chat/JobCard'
import { BatchHeader } from '../features/chat/BatchHeader'
import { parseJobIntake } from '../features/intake/parseJobIntake'
import { useProfileStore } from '../contexts/ProfileStore'
import type { ChatMessage } from '@applyocalypse/shared-types'

export default function ChatScreen() {
  const { state: profileState } = useProfileStore()
  const [input, setInput] = createSignal('')
  const [submitting, setSubmitting] = createSignal(false)
  const [error, setError] = createSignal<string | null>(null)
  const [collapsed, setCollapsed] = createStore<Record<string, boolean>>({})
  let threadRef: HTMLDivElement | undefined

  onMount(async () => {
    chatDispatch({ type: 'LOADED', messages: [] })
    const { items } = await window.applyocalypse.chat.list(200, 0)
    chatDispatch({ type: 'LOADED', messages: items })
  })

  const scrollToBottom = () => {
    if (threadRef) threadRef.scrollTop = threadRef.scrollHeight
  }

  createEffect(() => {
    const _ = chatState.messages.length
    void _
    scrollToBottom()
  })

  const appendMsg = async (
    input: Parameters<typeof window.applyocalypse.chat.appendMessage>[0]
  ): Promise<ChatMessage> => {
    const msg = await window.applyocalypse.chat.appendMessage(input)
    chatDispatch({ type: 'APPENDED', message: msg })
    return msg
  }

  const handleSubmit = async () => {
    const value = input().trim()
    if (!value || submitting()) return
    const profileId = profileState.profile?.id
    if (!profileId) {
      setError('Create a profile before submitting jobs.')
      return
    }
    setError(null)
    setSubmitting(true)
    try {
      await appendMsg({ role: 'USER', kind: 'TEXT', content: value })
      setInput('')

      const parsed = parseJobIntake(value)
      if (parsed.length === 0) return

      const enqueued = await window.applyocalypse.jobs.enqueue(
        profileId,
        parsed.map((item) => ({ sourceKind: item.sourceKind, sourceValue: item.sourceValue }))
      )

      const isBatch = enqueued.queueItems.length > 1
      const batchId = isBatch ? crypto.randomUUID() : null

      if (isBatch) {
        await appendMsg({
          role: 'SYSTEM',
          kind: 'BATCH_HEADER',
          content: '',
          batchId,
          metadata: {
            batchId,
            jobCount: enqueued.queueItems.length
          }
        })
      }

      for (const queueItem of enqueued.queueItems) {
        const jobTarget = enqueued.jobTargets.find((jt) => jt.id === queueItem.jobTargetId)
        await appendMsg({
          role: 'SYSTEM',
          kind: 'JOB_CARD',
          content: '',
          batchId,
          jobId: queueItem.id,
          metadata: {
            sourceKind: jobTarget?.sourceKind ?? 'URL',
            sourceValue: jobTarget?.sourceValue ?? '',
            queueItemId: queueItem.id,
            company: jobTarget?.company ?? null,
            role: jobTarget?.role ?? null,
            status: queueItem.status
          }
        })
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Something went wrong')
    } finally {
      setSubmitting(false)
    }
  }

  const handleKeyDown = (e: KeyboardEvent) => {
    if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) void handleSubmit()
  }

  const isBatchCardHidden = (msg: ChatMessage): boolean => {
    if (msg.kind !== 'JOB_CARD' || !msg.batchId) return false
    return collapsed[msg.batchId] === true
  }

  return (
    <section class="chat-panel surface-panel surface-panel-active" data-gsap="panel" data-view-panel>
      <div class="panel-kicker">Job intake</div>
      <h2>Chat</h2>

      <div class="chat-thread" ref={threadRef}>
        <For each={chatState.messages} fallback={
          <div class="chat-empty">
            <p>Paste job links or descriptions below to get started.</p>
          </div>
        }>
          {(msg: ChatMessage) => (
            <Show when={!isBatchCardHidden(msg)}>
              <div
                class={`chat-message chat-message--${msg.role.toLowerCase()}`}
                data-kind={msg.kind}
              >
                {msg.kind === 'BATCH_HEADER' ? (
                  <BatchHeader
                    message={msg}
                    allMessages={chatState.messages}
                    collapsed={collapsed[msg.batchId ?? ''] === true}
                    onToggle={() => {
                      const id = msg.batchId ?? ''
                      setCollapsed(id, !collapsed[id])
                    }}
                  />
                ) : msg.kind === 'JOB_CARD' ? (
                  <JobCard message={msg} />
                ) : (
                  <span class="chat-message-text">{msg.content}</span>
                )}
              </div>
            </Show>
          )}
        </For>
      </div>

      <div class="chat-input-row">
        <Show when={error()}>
          <p class="chat-error">{error()}</p>
        </Show>
        <div class="chat-input-wrap">
          <textarea
            class="chat-input"
            spellcheck={false}
            value={input()}
            onInput={(e) => setInput(e.currentTarget.value)}
            onKeyDown={handleKeyDown}
            placeholder="Paste job links or a description (Ctrl+Enter to send)"
            rows={3}
          />
          <button
            class="icon-button chat-send-btn"
            type="button"
            aria-label="Send"
            disabled={!input().trim() || submitting()}
            onClick={() => void handleSubmit()}
          >
            <Send size={17} aria-hidden="true" />
          </button>
        </div>
      </div>
    </section>
  )
}
