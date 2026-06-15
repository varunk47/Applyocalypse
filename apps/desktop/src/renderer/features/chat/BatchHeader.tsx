import { Show } from 'solid-js'
import { ChevronDown, ChevronRight } from 'lucide-solid'
import type { ChatMessage } from '@applyocalypse/shared-types'

type BatchMeta = {
  jobCount?: number
  batchId?: string
}

type BatchProgress = {
  total: number
  queued: number
  running: number
  completed: number
  failed: number
}

export const computeBatchProgress = (messages: ChatMessage[], batchId: string): BatchProgress => {
  const cards = messages.filter((m) => m.kind === 'JOB_CARD' && m.batchId === batchId)
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

type Props = {
  message: ChatMessage
  allMessages: ChatMessage[]
  collapsed: boolean
  onToggle: () => void
}

export const BatchHeader = (props: Props) => {
  const meta = () => props.message.metadata as BatchMeta
  const batchId = () => meta().batchId ?? props.message.batchId ?? ''
  const progress = () => computeBatchProgress(props.allMessages, batchId())

  const summary = () => {
    const p = progress()
    if (p.completed === p.total && p.total > 0) return `${p.total}/${p.total} completed`
    if (p.failed > 0) return `${p.failed} failed, ${p.completed} completed of ${p.total}`
    if (p.running > 0) return `${p.running} running, ${p.queued} queued of ${p.total}`
    return `${p.queued} awaiting review of ${p.total}`
  }

  return (
    <button
      class="chat-batch-header"
      type="button"
      onClick={props.onToggle}
      aria-expanded={!props.collapsed}
    >
      <Show when={props.collapsed} fallback={<ChevronDown size={13} aria-hidden="true" />}>
        <ChevronRight size={13} aria-hidden="true" />
      </Show>
      <span class="chat-batch-count">{progress().total} jobs</span>
      <span class="chat-batch-summary">{summary()}</span>
    </button>
  )
}
