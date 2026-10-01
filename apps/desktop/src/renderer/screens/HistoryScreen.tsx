import { createMemo, createResource, createSignal, For, Show } from 'solid-js'
import { useNavigate } from '@solidjs/router'
import { Search } from 'lucide-solid'
import type { ApplicationRun, JobTarget } from '@applyocalypse/shared-types'
import { Segmented } from '../components/Segmented'
import { jobLabel, useQueueStore } from '../contexts/QueueStore'
import { useRunStore } from '../contexts/RunStore'
import { runTone, statusLabel, type RunTone } from '../features/missions/runTone'
import { loadAllRuns } from '../features/stats/loadAllRuns'

type Filter = 'all' | 'sent' | 'needs' | 'working' | 'failed' | 'withdrawn'

const FILTER_OF: Record<RunTone, Filter> = {
  sent: 'sent',
  sign: 'needs',
  needs: 'needs',
  working: 'working',
  queued: 'working',
  failed: 'failed',
  withdrawn: 'withdrawn',
}

const FILTER_NAMES: Record<Filter, string> = {
  all: 'All',
  sent: 'Sent',
  needs: 'Needs you',
  working: 'In progress',
  failed: 'Failed',
  withdrawn: 'Withdrawn',
}

const PAGE = 60

const when = (run: ApplicationRun): Date => new Date(run.completedAt ?? run.startedAt ?? run.createdAt)

const dayHeading = (date: Date): string => {
  const today = new Date()
  const yesterday = new Date(today.getFullYear(), today.getMonth(), today.getDate() - 1)
  if (date.toDateString() === today.toDateString()) return 'Today'
  if (date.toDateString() === yesterday.toDateString()) return 'Yesterday'
  const sameYear = date.getFullYear() === today.getFullYear()
  return date.toLocaleDateString('en-US', { weekday: 'long', month: 'long', day: 'numeric', ...(sameYear ? {} : { year: 'numeric' }) })
}

export default function HistoryScreen() {
  const { state: queueState } = useQueueStore()
  const { loadRunDetail } = useRunStore()
  const navigate = useNavigate()
  const [stored] = createResource(loadAllRuns)
  const [filter, setFilter] = createSignal<Filter>('all')
  const [query, setQuery] = createSignal('')
  const [shown, setShown] = createSignal(PAGE)

  // Everything stored, with the live queue laid over it so running jobs stay current.
  const runs = createMemo(() => {
    const byId = new Map<string, ApplicationRun>()
    for (const run of stored()?.runs ?? []) byId.set(run.id, run)
    for (const run of queueState.applicationRuns) byId.set(run.id, run)
    return [...byId.values()].sort((a, b) => when(b).getTime() - when(a).getTime())
  })
  const targets = createMemo<Record<string, JobTarget | undefined>>(() => ({ ...(stored()?.targets ?? {}), ...queueState.jobTargetMap }))

  const counts = createMemo(() => {
    const totals: Record<Filter, number> = { all: 0, sent: 0, needs: 0, working: 0, failed: 0, withdrawn: 0 }
    for (const run of runs()) {
      totals.all += 1
      totals[FILTER_OF[runTone(run.status)]] += 1
    }
    return totals
  })

  const filterOptions = createMemo(() =>
    (Object.keys(FILTER_NAMES) as Filter[])
      .filter((key) => key === 'all' || counts()[key] > 0)
      .map((key) => ({ value: key, label: `${FILTER_NAMES[key]} ${counts()[key]}` }))
  )

  const matching = createMemo(() => {
    const words = query().trim().toLowerCase()
    return runs().filter((run) => {
      if (filter() !== 'all' && FILTER_OF[runTone(run.status)] !== filter()) return false
      if (!words) return true
      const target = targets()[run.jobTargetId]
      return [target?.company, target?.role, target?.portal].some((text) => text?.toLowerCase().includes(words))
    })
  })

  const groups = createMemo(() => {
    const out: Array<{ heading: string; runs: ApplicationRun[] }> = []
    for (const run of matching().slice(0, shown())) {
      const heading = dayHeading(when(run))
      const last = out[out.length - 1]
      if (last && last.heading === heading) last.runs.push(run)
      else out.push({ heading, runs: [run] })
    }
    return out
  })

  const chooseFilter = (next: Filter) => {
    setFilter(next)
    setShown(PAGE)
  }

  const open = async (runId: string) => {
    await loadRunDetail(runId)
    navigate(`/run/${runId}`)
  }

  return (
    <section class="screen history-screen" data-gsap="panel" data-view-panel>
      <div class="page-scroll">
        <header class="page-head">
          <h1 class="page-title">History</h1>
          <p class="page-sub">Every run, kept on this computer. Open one to see what was filled and sent.</p>
        </header>

        <div class="history-tools">
          <Segmented label="Show" options={filterOptions()} value={filter()} onChange={chooseFilter} />
          <label class="history-search">
            <Search size={15} aria-hidden="true" />
            <input
              type="search"
              value={query()}
              placeholder="Search company, role or portal"
              onInput={(event) => {
                setQuery(event.currentTarget.value)
                setShown(PAGE)
              }}
              aria-label="Search history"
            />
          </label>
        </div>

        <Show
          when={matching().length > 0}
          fallback={
            <div class="card empty-card">
              <Show
                when={!stored.loading}
                fallback={<span>Loading your history…</span>}
              >
                <strong>{runs().length === 0 ? 'No runs yet' : 'Nothing matches'}</strong>
                <span>
                  {runs().length === 0
                    ? 'Every application you start is kept here, with what was filled and what was sent.'
                    : 'Try another filter or search.'}
                </span>
              </Show>
            </div>
          }
        >
          <For each={groups()}>
            {(group) => (
              <section class="history-day">
                <h2 class="history-day-head">
                  {group.heading}
                  <span>{group.runs.length}</span>
                </h2>
                <div class="card history-list">
                  <For each={group.runs}>
                    {(run) => {
                      const target = () => targets()[run.jobTargetId]
                      const name = () => target()?.company ?? jobLabel(target(), run.id)
                      return (
                        <button class="history-row" type="button" onClick={() => void open(run.id)}>
                          <span class="history-logo" aria-hidden="true">{name().charAt(0).toUpperCase()}</span>
                          <span class="history-main">
                            <strong>{name()}</strong>
                            <span>{target()?.role ?? 'Role not read yet'}</span>
                          </span>
                          <span class="history-portal">{target()?.portal ?? ''}</span>
                          <span class={`status-pill tone-${runTone(run.status)}`}>{statusLabel(run.status)}</span>
                          <span class="history-time">
                            {when(run).toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' })}
                          </span>
                        </button>
                      )
                    }}
                  </For>
                </div>
              </section>
            )}
          </For>
          <Show when={matching().length > shown()}>
            <button class="btn-quiet history-more" type="button" onClick={() => setShown(shown() + PAGE)}>
              Show {Math.min(PAGE, matching().length - shown())} more
            </button>
          </Show>
        </Show>

        <footer class="page-foot">
          <span>Kept on this computer. None of it leaves.</span>
          <span>{counts().all} runs in total</span>
        </footer>
      </div>
    </section>
  )
}
