import { For, onMount } from 'solid-js'
import { useNavigate } from '@solidjs/router'
import { Inbox, ListTodo, Upload } from 'lucide-solid'
import { useQueueStore } from '../contexts/QueueStore'
import { useRunStore } from '../contexts/RunStore'
import { useProfileStore } from '../contexts/ProfileStore'
import { gsap } from '../animations/gsap'

export default function OverviewScreen() {
  const { state: queueState } = useQueueStore()
  const { state: runState } = useRunStore()
  const { pickAndRegisterResume } = useProfileStore()
  const navigate = useNavigate()

  let statsRef: HTMLDivElement | undefined

  const total = () => queueState.queueTotal + queueState.runsTotal
  const pending = () => queueState.queueItems.filter((i) => ['QUEUED', 'PREPARING'].includes(i.status)).length
  const completed = () => queueState.applicationRuns.filter((r) => r.status === 'COMPLETED').length
  const failed = () => queueState.applicationRuns.filter((r) => ['FAILED', 'CANCELLED'].includes(r.status)).length

  onMount(() => {
    if (statsRef) {
      const cards = statsRef.querySelectorAll('.stat-card')
      gsap.from(cards, { y: 20, opacity: 0, duration: 0.5, stagger: 0.06, ease: 'expo.out' })

      // Animate stat numbers
      cards.forEach((card) => {
        const el = card.querySelector('.stat-value') as HTMLElement | null
        if (!el) return
        const target = parseInt(el.textContent ?? '0', 10)
        if (isNaN(target) || target === 0) return
        const counter = { val: 0 }
        gsap.to(counter, {
          val: target,
          duration: 1.2,
          ease: 'power3.out',
          snap: { val: 1 },
          onUpdate: () => { el.textContent = String(Math.round(counter.val)) },
        })
      })
    }
  })

  const recentEvents = () => runState.events.slice(0, 8)

  return (
    <section class="hero-panel surface-panel surface-panel-active" data-gsap="panel" data-view-panel>
      <div class="panel-kicker">Control plane</div>
      <h2>Overview</h2>

      {/* Stat cards */}
      <div ref={statsRef} style={{ display: 'grid', 'grid-template-columns': 'repeat(4, 1fr)', gap: '1rem', 'margin-top': '1.5rem' }}>
        <div class="stat-card">
          <div class="stat-value">{total()}</div>
          <div class="stat-label">Total</div>
        </div>
        <div class="stat-card">
          <div class="stat-value">{pending()}</div>
          <div class="stat-label">Pending</div>
        </div>
        <div class="stat-card">
          <div class="stat-value">{completed()}</div>
          <div class="stat-label">Completed</div>
        </div>
        <div class="stat-card">
          <div class="stat-value">{failed()}</div>
          <div class="stat-label">Failed</div>
        </div>
      </div>

      {/* Recent activity */}
      <div style={{ 'margin-top': '2rem' }}>
        <div class="panel-kicker">Recent activity</div>
        <div class="event-stream" style={{ 'max-height': '180px', overflow: 'auto' }}>
          <For
            each={recentEvents()}
            fallback={<p class="fine-print">No events yet.</p>}
          >
            {(event) => (
              <div class="event-line">
                <span>{event.severity}</span>
                <p>{event.message}</p>
              </div>
            )}
          </For>
        </div>
      </div>

      {/* Quick actions */}
      <div class="hero-actions" style={{ 'margin-top': '2rem' }}>
        <button class="primary-action" type="button" onClick={() => void pickAndRegisterResume()}>
          <Upload size={18} aria-hidden="true" />
          <span>Add resume source</span>
        </button>
        <button class="secondary-action" type="button" onClick={() => navigate('/intake')}>
          <Inbox size={18} aria-hidden="true" />
          <span>Paste jobs</span>
        </button>
        <button class="secondary-action" type="button" onClick={() => navigate('/queue')}>
          <ListTodo size={18} aria-hidden="true" />
          <span>Open queue</span>
        </button>
      </div>
    </section>
  )
}
