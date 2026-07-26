import { For, Show } from 'solid-js'
import { useNavigate } from '@solidjs/router'
import { useQueueStore, jobLabel } from '../contexts/QueueStore'
import { useRunStore } from '../contexts/RunStore'

const receiptState = (status: string): { text: string; kind: 'submitted' | 'failed' | 'neutral' } => {
  if (status === 'SUBMITTED' || status === 'COMPLETED') return { text: 'SUBMITTED ✓', kind: 'submitted' }
  if (status === 'FAILED') return { text: 'FAILED', kind: 'failed' }
  if (status === 'CANCELLED') return { text: 'WITHDRAWN', kind: 'neutral' }
  return { text: status.replace(/_/g, ' '), kind: 'neutral' }
}

const receiptTime = (iso: string | null): string => {
  if (!iso) return '—'
  const t = new Date(iso)
  if (Number.isNaN(t.getTime())) return '—'
  return `${t.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })} · ${t.toTimeString().slice(0, 5)}`
}

export default function HistoryScreen() {
  const { state: queueState } = useQueueStore()
  const { loadRunDetail } = useRunStore()
  const navigate = useNavigate()

  const handleRowClick = async (runId: string) => {
    await loadRunDetail(runId)
    navigate(`/run/${runId}`)
  }

  return (
    <section class="screen screen-scroll" data-gsap="panel" data-view-panel>
      <div class="screen-pad">
        <h1 class="screen-headline" style={{ 'font-size': '30px' }}>History</h1>
        <p class="screen-sub">Every action, receipted. Append-only, local, exportable.</p>

        <div class="rule-row" style={{ 'margin-bottom': '10px' }}>
          <span class="kicker">RUN LEDGER</span>
          <span class="rule" />
          <span class="kicker">{queueState.runsTotal} TOTAL</span>
        </div>

        <Show
          when={queueState.applicationRuns.length > 0}
          fallback={
            <div class="empty-state">
              <span>{queueState.isLoading ? 'Loading the run ledger...' : 'No runs yet. The ledger starts with your first mission.'}</span>
            </div>
          }
        >
          <div class="receipt-table">
            <For each={queueState.applicationRuns}>
              {(run) => (
                <button class="receipt-row" type="button" style={{ width: '100%' }} onClick={() => void handleRowClick(run.id)}>
                  <span class="receipt-time">{receiptTime(run.completedAt ?? run.startedAt ?? run.createdAt)}</span>
                  <span class="receipt-title">{jobLabel(queueState.jobTargetMap[run.jobTargetId], run.id)}</span>
                  <span class="mono-chip">RUN {run.id.slice(0, 6).toUpperCase()}</span>
                  <span class="receipt-state" classList={{
                    submitted: receiptState(run.status).kind === 'submitted',
                    failed: receiptState(run.status).kind === 'failed',
                    neutral: receiptState(run.status).kind === 'neutral',
                  }}>
                    {receiptState(run.status).text}
                  </span>
                </button>
              )}
            </For>
          </div>
        </Show>

        <div class="validators-note" style={{ 'margin-top': '16px' }}>
          EVERY RUN IS AUDIT-LOGGED AND ARCHIVED ON THIS MACHINE — NOTHING LEAVES IT
        </div>
      </div>
    </section>
  )
}
