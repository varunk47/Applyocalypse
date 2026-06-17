import { chatState, chatDispatch } from './ChatStore'
import type { ChatMessage } from '@applyocalypse/shared-types'

// ---------------------------------------------------------------------------
// Pure core (no window access — unit-testable)
// ---------------------------------------------------------------------------

export type CardRef = {
  messageId: string
  queueItemId?: string | undefined
  runId?: string | undefined
  status?: string | undefined
}
export type RunRow = { id: string; queueItemId: string; status: string }

export const TERMINAL_STATUSES = new Set(['COMPLETED', 'FAILED', 'CANCELLED', 'SUBMITTED'])

/** Diff cards against the authoritative run list; return only the changed cards. */
export const reconcileCards = (
  cards: CardRef[],
  runs: RunRow[]
): Array<{ messageId: string; runId: string; status: string }> => {
  const byQueueItem = new Map(runs.map((r) => [r.queueItemId, r]))
  const out: Array<{ messageId: string; runId: string; status: string }> = []
  for (const card of cards) {
    if (!card.queueItemId) continue
    const run = byQueueItem.get(card.queueItemId)
    if (!run) continue
    if (card.runId !== run.id || card.status !== run.status) {
      out.push({ messageId: card.messageId, runId: run.id, status: run.status })
    }
  }
  return out
}

export const hasLiveCards = (cards: CardRef[]): boolean =>
  cards.some((c) => c.queueItemId && !TERMINAL_STATUSES.has(c.status ?? 'QUEUED'))

export const extractCardRefs = (messages: ChatMessage[]): CardRef[] =>
  messages
    .filter((m) => m.kind === 'JOB_CARD')
    .map((m) => {
      const meta = (m.metadata ?? {}) as { queueItemId?: string; runId?: string; status?: string }
      return { messageId: m.id, queueItemId: meta.queueItemId, runId: meta.runId, status: meta.status }
    })

// ---------------------------------------------------------------------------
// Effectful shell
// ---------------------------------------------------------------------------

const POLL_MS = 3000
const DEBOUNCE_MS = 250
const noop = (): void => {}

// Stable export the screen calls when it appends a new JOB_CARD; delegates to
// the active sync's handler (or noop when no sync is mounted).
let changeHandler: () => void = noop
export const notifyCardsChanged = (): void => changeHandler()

/**
 * Mount the live-sync engine: reconciles chat job cards against the
 * authoritative `runs.list` on a timer and on per-run log events, dispatching
 * CARD_RUN_STATE for changes. Never persists status back to chat history —
 * `runs.list` is the single source of truth. Returns a stop() disposer.
 */
export const startChatLiveSync = (): (() => void) => {
  let pollTimer: ReturnType<typeof setInterval> | undefined
  let debounceTimer: ReturnType<typeof setTimeout> | undefined
  let reconciling = false
  let pendingReconcile = false
  let stopped = false
  const subscriptions = new Map<string, () => void>() // runId -> unsubscribe

  const currentCards = (): CardRef[] => extractCardRefs(chatState.messages)

  const syncSubscriptions = (): void => {
    const liveRunIds = new Set(
      currentCards()
        .filter((c) => c.runId && !TERMINAL_STATUSES.has(c.status ?? 'QUEUED'))
        .map((c) => c.runId as string)
    )
    for (const runId of liveRunIds) {
      if (!subscriptions.has(runId)) {
        subscriptions.set(runId, window.applyocalypse.logs.subscribe(runId, () => scheduleReconcile()))
      }
    }
    for (const [runId, unsub] of subscriptions) {
      if (!liveRunIds.has(runId)) {
        unsub()
        subscriptions.delete(runId)
      }
    }
  }

  const syncPolling = (): void => {
    const live = hasLiveCards(currentCards())
    if (live && !pollTimer) {
      pollTimer = setInterval(() => void reconcile(), POLL_MS)
    } else if (!live && pollTimer) {
      clearInterval(pollTimer)
      pollTimer = undefined
    }
  }

  const reconcile = async (): Promise<void> => {
    if (stopped) return
    if (reconciling) {
      pendingReconcile = true
      return
    }
    reconciling = true
    try {
      const { items } = await window.applyocalypse.runs.list(100, 0)
      if (stopped) return
      const runs: RunRow[] = items.map((r) => ({ id: r.id, queueItemId: r.queueItemId, status: r.status }))
      for (const u of reconcileCards(currentCards(), runs)) {
        chatDispatch({ type: 'CARD_RUN_STATE', messageId: u.messageId, runId: u.runId, status: u.status })
      }
      syncSubscriptions()
      syncPolling()
    } finally {
      reconciling = false
      if (pendingReconcile && !stopped) {
        pendingReconcile = false
        void reconcile()
      }
    }
  }

  const scheduleReconcile = (): void => {
    if (stopped) return
    if (debounceTimer) clearTimeout(debounceTimer)
    debounceTimer = setTimeout(() => {
      debounceTimer = undefined
      void reconcile()
    }, DEBOUNCE_MS)
  }

  changeHandler = () => {
    if (stopped) return
    syncPolling()
    scheduleReconcile()
  }

  void reconcile()

  return () => {
    stopped = true
    if (pollTimer) clearInterval(pollTimer)
    if (debounceTimer) clearTimeout(debounceTimer)
    for (const [, unsub] of subscriptions) unsub()
    subscriptions.clear()
    changeHandler = noop
  }
}
