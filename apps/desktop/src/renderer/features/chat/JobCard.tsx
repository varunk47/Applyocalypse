import { ExternalLink } from 'lucide-solid'
import type { ChatMessage } from '@applyocalypse/shared-types'

type JobCardMeta = {
  sourceKind?: 'URL' | 'TEXT'
  sourceValue?: string
  queueItemId?: string
  runId?: string
  status?: string
  company?: string
  role?: string
}

type Props = {
  message: ChatMessage
}

const statusLabel = (status: string): string => {
  const map: Record<string, string> = {
    QUEUED: 'Queued',
    PREPARING: 'Preparing',
    RUNNING_AUTOMATION: 'Running',
    PAUSED: 'Paused',
    COMPLETED: 'Completed',
    FAILED: 'Failed',
    CANCELLED: 'Cancelled',
  }
  return map[status] ?? status
}

const statusClass = (status: string): string => {
  if (status === 'COMPLETED') return 'status-completed'
  if (['FAILED', 'CANCELLED'].includes(status)) return 'status-failed'
  if (['RUNNING_AUTOMATION', 'PREPARING'].includes(status)) return 'status-running'
  return 'status-pending'
}

export const JobCard = (props: Props) => {
  const meta = () => {
    try {
      return props.message.metadata as JobCardMeta
    } catch {
      return {} as JobCardMeta
    }
  }

  const displayTitle = () => {
    const m = meta()
    if (m.company && m.role) return `${m.company} — ${m.role}`
    if (m.company) return m.company
    if (m.role) return m.role
    if (m.sourceValue && m.sourceKind === 'URL') {
      try { return new URL(m.sourceValue).hostname } catch { /* ignore */ }
    }
    return m.sourceValue?.slice(0, 60) ?? 'Job'
  }

  const url = () => {
    const m = meta()
    return m.sourceKind === 'URL' ? m.sourceValue : undefined
  }

  const status = () => meta().status ?? 'QUEUED'

  return (
    <div class="chat-job-card" data-status={status()}>
      <div class="chat-job-card-header">
        <span class="chat-job-card-title">{displayTitle()}</span>
        <span class={`chat-job-card-status ${statusClass(status())}`}>{statusLabel(status())}</span>
      </div>
      {url() && (
        <a
          class="chat-job-card-link"
          href="#"
          onClick={(e) => {
            e.preventDefault()
            void window.applyocalypse.files.openLocalPath(url()!)
          }}
        >
          <ExternalLink size={11} aria-hidden="true" />
          {url()}
        </a>
      )}
    </div>
  )
}
