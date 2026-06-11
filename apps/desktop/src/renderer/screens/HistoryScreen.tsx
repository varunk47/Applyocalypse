import { For, Show, onMount } from 'solid-js'
import { useNavigate } from '@solidjs/router'
import { FileText } from 'lucide-solid'
import { EmptyState } from '../components/EmptyState'
import { useQueueStore, jobLabel } from '../contexts/QueueStore'
import { useRunStore } from '../contexts/RunStore'
import { gsap } from '../animations/gsap'

export default function HistoryScreen() {
  const { state: queueState } = useQueueStore()
  const { state: runState, loadRunDetail } = useRunStore()
  const navigate = useNavigate()
  let listRef: HTMLDivElement | undefined

  onMount(() => {
    if (listRef) {
      gsap.from(listRef.querySelectorAll('[data-list-item]'), {
        y: 12, opacity: 0, duration: 0.35, stagger: 0.04, ease: 'expo.out',
      })
    }
  })

  const handleRowClick = async (runId: string) => {
    await loadRunDetail(runId)
    navigate('/run')
  }

  return (
    <section class="history-panel diagnostics-panel surface-panel surface-panel-active" data-gsap="panel" data-view-panel>
      <div class="section-header">
        <div>
          <div class="panel-kicker">History</div>
          <h2>Run history and audit trail</h2>
        </div>
        <span class="metric">{queueState.runsTotal}</span>
      </div>

      <Show
        when={queueState.applicationRuns.length > 0 || runState.events.length > 0}
        fallback={
          <EmptyState
            icon={FileText}
            title="No run history yet"
            description="Completed, paused, blocked, and failed runs appear here after the first queue item starts."
          />
        }
      >
        <div class="queue-list" ref={listRef}>
          <For each={queueState.applicationRuns}>
            {(run) => (
              <button
                class="queue-row"
                classList={{ active: runState.activeRunId === run.id }}
                type="button"
                data-list-item
                onClick={() => void handleRowClick(run.id)}
              >
                <span>{run.status}</span>
                <strong>{jobLabel(queueState.jobTargetMap[run.jobTargetId], run.id)}</strong>
              </button>
            )}
          </For>
        </div>

        <Show when={runState.events.length > 0}>
          <div class="event-stream">
            <div class="panel-kicker">Recent events</div>
            <For each={runState.events.slice(0, 12)}>
              {(event) => (
                <div class="event-line">
                  <span>{event.severity}</span>
                  <p>{event.message}</p>
                </div>
              )}
            </For>
          </div>
        </Show>
      </Show>
    </section>
  )
}
