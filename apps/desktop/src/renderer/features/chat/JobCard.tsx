import { ExternalLink } from 'lucide-solid'
import { Show } from 'solid-js'
import { useNavigate } from '@solidjs/router'
import type { ChatMessage } from '@applyocalypse/shared-types'

// Statuses where the user must act in the Run Console.
const REVIEW_STATUSES = new Set(['READY_FOR_REVIEW', 'WAITING_FOR_USER_EDIT', 'BLOCKED_OTP', 'READY_TO_SUBMIT'])

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
    ANALYZING: 'Analyzing',
    TAILORING_RESUME: 'Tailoring',
    GENERATING_COVER_LETTER: 'Cover letter',
    READY_FOR_REVIEW: 'Review required',
    WAITING_FOR_USER_EDIT: 'Edit required',
    RUNNING_AUTOMATION: 'Running',
    BLOCKED_OTP: 'OTP needed',
    READY_TO_SUBMIT: 'Ready to submit',
    SUBMITTED: 'Submitted',
    PAUSED: 'Paused',
    COMPLETED: 'Completed',
    FAILED: 'Failed',
    CANCELLED: 'Cancelled',
  }
  return map[status] ?? status
}

const statusClass = (status: string): string => {
  if (status === 'COMPLETED' || status === 'SUBMITTED') return 'status-completed'
  if (['FAILED', 'CANCELLED'].includes(status)) return 'status-failed'
  if (REVIEW_STATUSES.has(status)) return 'status-review'
  if (['RUNNING_AUTOMATION', 'PREPARING', 'ANALYZING', 'TAILORING_RESUME', 'GENERATING_COVER_LETTER'].includes(status))
    return 'status-running'
  return 'status-pending'
}

export const JobCard = (props: Props) => {
  const navigate = useNavigate()

  const meta = () => {
    try {
      return props.message.metadata as JobCardMeta
    } catch {
      return {} as JobCardMeta
    }
  }

  const needsReview = () => REVIEW_STATUSES.has(status()) && Boolean(meta().runId)

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
      <Show when={needsReview()}>
        <button
          type="button"
          class="chat-job-card-open-run"
          onClick={() => navigate(`/run/${meta().runId}`)}
        >
          Open run
        </button>
      </Show>
    </div>
  )
}
