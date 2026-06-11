import { For, Show, onMount } from 'solid-js'
import { useNavigate } from '@solidjs/router'
import { CheckCircle2, ListTodo } from 'lucide-solid'
import { useQueueStore, jobLabel } from '../contexts/QueueStore'
import { useRunStore } from '../contexts/RunStore'
import { gsap } from '../animations/gsap'
import { EmptyState } from '../components/EmptyState'

export default function QueueScreen() {
  const { state } = useQueueStore()
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

  const runForQueueItem = (queueItemId: string) =>
    state.applicationRuns.find((r) => r.queueItemId === queueItemId) ?? null

  const handleRowClick = async (runId: string) => {
    await loadRunDetail(runId)
    navigate('/run')
  }

  return (
    <section class="queue-panel surface-panel surface-panel-active" data-gsap="panel" data-view-panel>
      <div class="section-header">
        <div>
          <div class="panel-kicker">Queue</div>
          <h2>Application runs</h2>
        </div>
        <span class="metric">{state.queueTotal + state.runsTotal}</span>
      </div>

      <Show
        when={state.queueItems.length > 0 || state.applicationRuns.length > 0}
        fallback={
          <EmptyState
            icon={CheckCircle2}
            title="No active jobs yet"
            description="Add source materials and paste job targets to begin."
            action={{ label: 'Go to Intake', onClick: () => navigate('/intake') }}
          />
        }
      >
        <div class="queue-list" ref={listRef}>
          <For each={state.queueItems}>
            {(item) => {
              const run = runForQueueItem(item.id)
              return (
                <button
                  class="queue-row"
                  classList={{ active: runState.activeRunId === run?.id }}
                  type="button"
                  data-list-item
                  disabled={!run}
                  onClick={() => run ? void handleRowClick(run.id) : undefined}
                >
                  <span>{run?.status ?? item.status}</span>
                  <strong>{jobLabel(state.jobTargetMap[item.jobTargetId], item.jobTargetId)}</strong>
                </button>
              )
            }}
          </For>
          <For each={state.applicationRuns.filter((r) => !state.queueItems.some((i) => i.id === r.queueItemId)).slice(0, 6)}>
            {(run) => (
              <button
                class="queue-row"
                classList={{ active: runState.activeRunId === run.id }}
                type="button"
                data-list-item
                onClick={() => void handleRowClick(run.id)}
              >
                <span>{run.status}</span>
                <strong>{jobLabel(state.jobTargetMap[run.jobTargetId], run.id)}</strong>
              </button>
            )}
          </For>
        </div>
      </Show>

      <Show when={!state.isLoading && state.queueItems.length === 0 && state.applicationRuns.length === 0}>
        <div style={{ display: 'flex', gap: '0.5rem', 'margin-top': '1rem' }}>
          <ListTodo size={16} aria-hidden="true" style={{ color: 'var(--muted)' }} />
          <span class="fine-print">Use Intake to add job links or paste job descriptions.</span>
        </div>
      </Show>
    </section>
  )
}
