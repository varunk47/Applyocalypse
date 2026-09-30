import { createMemo, createResource, createSignal, For, Show } from 'solid-js'
import { Segmented } from '../components/Segmented'
import { BarChart } from '../features/stats/BarChart'
import { CalendarHeat } from '../features/stats/CalendarHeat'
import { CountUp } from '../features/stats/CountUp'
import { loadAllRuns } from '../features/stats/loadAllRuns'
import {
  bucketCounts,
  byPortal,
  dailyGrid,
  failureLabel,
  failureReasons,
  medianMinutes,
  outcomes,
  sentDates,
  streaks,
  weekdayTotals,
  type Granularity,
} from '../features/stats/stats'

const PERIODS: Record<Granularity, { count: number; noun: string; every: number }> = {
  day: { count: 30, noun: '30 days', every: 5 },
  week: { count: 12, noun: '12 weeks', every: 2 },
  month: { count: 12, noun: '12 months', every: 1 },
}

const GRANULARITIES = [
  { value: 'day', label: 'Per day' },
  { value: 'week', label: 'Per week' },
  { value: 'month', label: 'Per month' },
] as const

const WEEKDAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']

const periodLabel = (start: Date, granularity: Granularity): { label: string; full: string } => {
  if (granularity === 'day') {
    return {
      label: String(start.getDate()),
      full: start.toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric' }),
    }
  }
  if (granularity === 'week') {
    const label = start.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
    return { label, full: `Week of ${label}` }
  }
  return {
    label: start.toLocaleDateString('en-US', { month: 'short' }),
    full: start.toLocaleDateString('en-US', { month: 'long', year: 'numeric' }),
  }
}

const duration = (minutes: number | null): string => {
  if (minutes === null) return 'None yet'
  if (minutes < 60) return `${minutes} m`
  const hours = Math.floor(minutes / 60)
  if (hours < 48) return `${hours} h ${minutes % 60} m`
  return `${Math.round(hours / 24)} days`
}

export default function StatsScreen() {
  const [data] = createResource(loadAllRuns)
  const [granularity, setGranularity] = createSignal<Granularity>('day')
  const [asTable, setAsTable] = createSignal(false)
  const now = new Date()

  const runs = () => data()?.runs ?? []
  const dates = createMemo(() => sentDates(runs()))
  const period = () => PERIODS[granularity()]

  const buckets = createMemo(() => bucketCounts(dates(), granularity(), now, period().count))
  const since = () => buckets().current[0]?.start ?? now
  const bars = createMemo(() =>
    buckets().current.map((bucket) => ({ ...periodLabel(bucket.start, granularity()), count: bucket.count }))
  )
  const total = createMemo(() => buckets().current.reduce((sum, bucket) => sum + bucket.count, 0))
  const change = createMemo(() => {
    const before = buckets().previousTotal
    if (before === 0) return null
    return Math.round(((total() - before) / before) * 100)
  })

  const grid = createMemo(() => dailyGrid(dates(), now, 26))
  const streak = createMemo(() => streaks(grid()))
  const weekdays = createMemo(() => weekdayTotals(grid()))
  const busiest = createMemo(() => {
    const max = Math.max(...weekdays())
    return max > 0 ? WEEKDAYS[weekdays().indexOf(max)] : null
  })

  const ended = createMemo(() => outcomes(runs(), since()))
  const finished = () => ended().sent + ended().failed + ended().withdrawn
  const cleanRate = createMemo(() => (finished() > 0 ? Math.round((ended().sent / finished()) * 100) : null))
  const reasons = createMemo(() => failureReasons(runs(), since()))
  const portals = createMemo(() => byPortal(runs(), data()?.targets ?? {}, since()))
  const portalMax = () => Math.max(1, ...portals().map((p) => p.count))
  const median = createMemo(() => medianMinutes(runs(), since()))

  return (
    <section class="screen stats-screen" data-view-panel>
      <div class="stats-scroll">
        <header class="page-head">
          <h1 class="page-title">Stats</h1>
          <p class="page-sub">Counted from the runs on this computer. Nothing here is estimated.</p>
        </header>

        <Show when={!data.loading} fallback={<p class="stats-note">Counting your runs…</p>}>
          <Show
            when={dates().length > 0}
            fallback={
              <div class="card stats-empty">
                <strong>Nothing sent yet</strong>
                <span>Your charts fill in as applications go out. Paste a job link on Missions to start.</span>
              </div>
            }
          >
            <div class="card heat-card">
              <div>
                <h2 class="card-title">Every day, last six months</h2>
                <CalendarHeat days={grid()} />
              </div>
              <dl class="streaks">
                <div>
                  <dt>Days you applied</dt>
                  <dd><CountUp value={streak().activeDays} /></dd>
                  <span>of the last {grid().length}</span>
                </div>
                <div>
                  <dt>Longest streak</dt>
                  <dd><CountUp value={streak().longest} /></dd>
                  <span>days in a row</span>
                </div>
                <div>
                  <dt>Current streak</dt>
                  <dd><CountUp value={streak().current} /></dd>
                  <span>days in a row</span>
                </div>
              </dl>
            </div>

            <div class="stats-filters">
              <Segmented label="Group by" options={GRANULARITIES} value={granularity()} onChange={setGranularity} />
              <button class="link-button" type="button" onClick={() => setAsTable(!asTable())}>
                {asTable() ? 'Show as chart' : 'Show as table'}
              </button>
            </div>

            <div class="stat-row">
              <div class="card stat hero">
                <span class="stat-label">Sent in the last {period().noun}</span>
                <span class="stat-value"><CountUp value={total()} /></span>
                <Show when={change()} fallback={<span class="stat-note">Nothing to compare with yet</span>}>
                  {(pct) => (
                    <span class="stat-delta" classList={{ down: pct() < 0 }}>
                      {pct() >= 0 ? '▲' : '▼'} {Math.abs(pct())}% vs the {period().noun} before
                    </span>
                  )}
                </Show>
              </div>
              <div class="card stat">
                <span class="stat-label">Sent without a hitch</span>
                <span class="stat-value">
                  <Show when={cleanRate() !== null} fallback="None yet">
                    <CountUp value={cleanRate() ?? 0} suffix="%" />
                  </Show>
                </span>
                <span class="meter"><i style={{ width: `${cleanRate() ?? 0}%` }} /></span>
              </div>
              <div class="card stat">
                <span class="stat-label">Link to sent, median</span>
                <span class="stat-value">{duration(median())}</span>
                <span class="stat-note">From adding a job to sending it</span>
              </div>
              <div class="card stat">
                <span class="stat-label">Busiest day</span>
                <span class="stat-value small">{busiest() ?? 'None yet'}</span>
                <div class="weekday-bars" aria-hidden="true">
                  <For each={weekdays()}>
                    {(value, index) => (
                      <span>
                        <i
                          classList={{ top: value > 0 && value === Math.max(...weekdays()) }}
                          style={{ height: `${Math.max(6, (value / Math.max(1, ...weekdays())) * 100)}%`, 'animation-delay': `${index() * 40 + 200}ms` }}
                        />
                        <b>{WEEKDAYS[index()]?.charAt(0)}</b>
                      </span>
                    )}
                  </For>
                </div>
              </div>
            </div>

            <div class="card chart-card">
              <h2 class="card-title">Applications sent {GRANULARITIES.find((g) => g.value === granularity())?.label.toLowerCase()}</h2>
              <p class="card-sub">Last {period().noun}</p>
              <Show
                when={!asTable()}
                fallback={
                  <table class="stats-table">
                    <thead>
                      <tr>
                        <th scope="col">Period</th>
                        <th scope="col">Sent</th>
                      </tr>
                    </thead>
                    <tbody>
                      <For each={bars()}>
                        {(bar) => (
                          <tr>
                            <td>{bar.full}</td>
                            <td>{bar.count}</td>
                          </tr>
                        )}
                      </For>
                    </tbody>
                  </table>
                }
              >
                <BarChart data={bars()} labelEvery={period().every} unit="sent" title={`Applications sent, last ${period().noun}`} />
              </Show>
            </div>

            <div class="stat-pair">
              <div class="card">
                <h2 class="card-title">How runs ended</h2>
                <p class="card-sub">Finished runs, last {period().noun}</p>
                <div class="split-bar" aria-hidden="true">
                  <i class="sent" style={{ 'flex-grow': ended().sent }} />
                  <i class="failed" style={{ 'flex-grow': ended().failed }} />
                  <i class="withdrawn" style={{ 'flex-grow': ended().withdrawn }} />
                </div>
                <ul class="split-legend">
                  <li><span class="mark sent" aria-hidden="true">✓</span>Sent<b>{ended().sent}</b></li>
                  <li><span class="mark failed" aria-hidden="true">✕</span>Failed<b>{ended().failed}</b></li>
                  <li><span class="mark withdrawn" aria-hidden="true">–</span>Withdrawn<b>{ended().withdrawn}</b></li>
                </ul>
                <Show when={reasons().length > 0}>
                  <ul class="reasons">
                    <li class="reasons-head">Why the failed ones stopped</li>
                    <For each={reasons()}>
                      {(reason) => (
                        <li>
                          {failureLabel(reason.code)}
                          <b>{reason.count}</b>
                        </li>
                      )}
                    </For>
                  </ul>
                </Show>
              </div>
              <div class="card">
                <h2 class="card-title">Sent by portal</h2>
                <p class="card-sub">Last {period().noun}</p>
                <Show when={portals().length > 0} fallback={<p class="stats-note">Nothing sent in this period.</p>}>
                  <ul class="portal-bars">
                    <For each={portals()}>
                      {(entry, index) => (
                        <li>
                          <span>{entry.portal}</span>
                          <span class="portal-track">
                            <i style={{ width: `${(entry.count / portalMax()) * 100}%`, 'animation-delay': `${index() * 60 + 150}ms` }} />
                            <b>{entry.count}</b>
                          </span>
                        </li>
                      )}
                    </For>
                  </ul>
                </Show>
              </div>
            </div>
          </Show>
        </Show>
      </div>
    </section>
  )
}
