import { createMemo, createSignal, For, onCleanup, Show } from 'solid-js'
import { useNavigate } from '@solidjs/router'
import type { ApplicationRun, JobTarget } from '@applyocalypse/shared-types'
import { useProfileStore } from '../contexts/ProfileStore'
import { jobLabel, useQueueStore } from '../contexts/QueueStore'
import { useRunStore } from '../contexts/RunStore'
import { parseJobIntake } from '../features/intake/parseJobIntake'

const WORKING_STATUSES = new Set([
  'CLAIMED',
  'PREPARING',
  'PARSING_JD',
  'ANALYZING',
  'TAILORING_RESUME',
  'GENERATING_COVER_LETTER',
  'RUNNING_AUTOMATION',
])

const NEEDS_SIGNATURE_STATUSES = new Set([
  'READY_FOR_REVIEW',
  'PAUSED',
  'BLOCKED_CAPTCHA',
  'BLOCKED_MFA',
  'BLOCKED_OTP',
  'BLOCKED_AMBIGUOUS_QUESTION',
  'WAITING_FOR_USER_EDIT',
  'READY_TO_SUBMIT',
])

const WORKING_LABELS: Record<string, { label: string; width: string }> = {
  CLAIMED: { label: 'Preparing the dossier', width: '8%' },
  PREPARING: { label: 'Preparing the dossier', width: '12%' },
  PARSING_JD: { label: 'Reading the posting', width: '22%' },
  ANALYZING: { label: 'Analyzing fit', width: '38%' },
  TAILORING_RESUME: { label: 'Tailoring résumé', width: '58%' },
  GENERATING_COVER_LETTER: { label: 'Writing cover letter, in your voice', width: '74%' },
  RUNNING_AUTOMATION: { label: 'Filling portal', width: '86%' },
}

type RailCopy = { sub: string; action: string; kind: 'ready' | 'outline' | 'mono' }

const DEFAULT_RAIL_COPY: RailCopy = {
  sub: 'Something needs your hand before this can continue.',
  action: 'Open run',
  kind: 'outline',
}

const RAIL_COPY: Record<string, RailCopy> = {
  READY_TO_SUBMIT: { sub: 'Filled and verified. One last look, then it ships.', action: 'Final review → Submit', kind: 'ready' },
  BLOCKED_OTP: { sub: 'Portal wants an email code. We paused and stepped back.', action: 'ENTER OTP', kind: 'mono' },
  BLOCKED_CAPTCHA: { sub: 'Portal raised a human check. We paused and stepped back.', action: 'OPEN PORTAL', kind: 'mono' },
  BLOCKED_MFA: { sub: 'Portal wants a sign-in approval. We paused and stepped back.', action: 'OPEN PORTAL', kind: 'mono' },
  BLOCKED_AMBIGUOUS_QUESTION: { sub: 'A question needs a human answer before we continue.', action: 'Review question', kind: 'outline' },
  READY_FOR_REVIEW: { sub: 'Résumé + cover letter drafted. Flagged items need a human.', action: 'Review documents', kind: 'outline' },
  WAITING_FOR_USER_EDIT: { sub: 'Something needs your hand before this can continue.', action: 'Review documents', kind: 'outline' },
  PAUSED: { sub: 'Paused mid-run and parked safely. Pick it back up any time.', action: 'Open run', kind: 'outline' },
}

const portalChip = (target: JobTarget | undefined): string | null => {
  if (!target) return null
  if (target.portal) return target.portal
  if (target.sourceKind === 'URL') {
    try {
      return new URL(target.sourceValue).hostname.replace(/^www\./, '')
    } catch {
      return null
    }
  }
  return null
}

const dateKicker = (): string => {
  const now = new Date()
  const day = now.toLocaleDateString('en-US', { weekday: 'long', month: 'long', day: 'numeric' })
  const time = now.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', hour12: false })
  return `${day} · ${time}`.toUpperCase()
}

export default function HomeScreen() {
  const { state: profileState } = useProfileStore()
  const { state: queueState, enqueueJobText } = useQueueStore()
  const { loadRunDetail } = useRunStore()
  const navigate = useNavigate()

  const [jobInput, setJobInput] = createSignal('')
  const [autoSubmit, setAutoSubmit] = createSignal(false)
  const [error, setError] = createSignal<string | null>(null)
  const [isSubmitting, setIsSubmitting] = createSignal(false)
  const [nowKicker, setNowKicker] = createSignal(dateKicker())
  const kickerTimer = setInterval(() => setNowKicker(dateKicker()), 30_000)
  onCleanup(() => clearInterval(kickerTimer))

  const targetFor = (run: { jobTargetId: string }) => queueState.jobTargetMap[run.jobTargetId]

  const workingRuns = createMemo(() => queueState.applicationRuns.filter((run) => WORKING_STATUSES.has(run.status)))

  const queuedItems = createMemo(() =>
    queueState.queueItems.filter(
      (item) => item.status === 'PENDING' && !queueState.applicationRuns.some((run) => run.queueItemId === item.id)
    )
  )

  const signatureRuns = createMemo(() =>
    queueState.applicationRuns.filter((run) => NEEDS_SIGNATURE_STATUSES.has(run.status))
  )

  const submittedThisWeek = createMemo(() => {
    const cutoff = Date.now() - 7 * 24 * 60 * 60 * 1000
    return queueState.applicationRuns.filter(
      (run) =>
        (run.status === 'SUBMITTED' || run.status === 'COMPLETED') &&
        run.completedAt !== null &&
        Date.parse(run.completedAt) >= cutoff
    ).length
  })

  const headline = createMemo(() => {
    const waiting = signatureRuns().length
    if (waiting > 0) {
      const noun = waiting === 1 ? 'application awaits' : 'applications await'
      return { lead: `${waiting === 1 ? 'One' : String(waiting)} ${noun} `, em: 'your signature.' }
    }
    if (workingRuns().length > 0) return { lead: 'The machines are ', em: 'hard at work.' }
    return { lead: 'Paste a link. We do ', em: 'the drudgery.' }
  })

  const hasIntake = createMemo(() => parseJobIntake(jobInput()).length > 0)

  const handleSubmit = async () => {
    const profileId = profileState.profile?.id
    if (!profileId) {
      setError('Create a profile before adding job targets.')
      return
    }
    if (isSubmitting()) return
    setError(null)
    setIsSubmitting(true)
    try {
      const queued = await enqueueJobText(jobInput(), profileId, {
        autoSubmitEnabled: autoSubmit(),
        onRunReady: async (runId) => {
          await loadRunDetail(runId)
          navigate(`/run/${runId}`)
        },
      })
      // Keep the pasted links in the box when enqueue fails so nothing is lost.
      if (queued) setJobInput('')
    } finally {
      setIsSubmitting(false)
    }
  }

  const openRun = async (run: ApplicationRun) => {
    await loadRunDetail(run.id)
    navigate(`/run/${run.id}`)
  }

  return (
    <section class="screen" data-gsap="panel" data-view-panel>
      <div class="home-grid">
        <div class="home-main">
          <div class="kicker">{nowKicker()}</div>
          <h1 class="screen-headline">
            <span class="headline-rise">
              <span>
                {headline().lead}
                <em>{headline().em}</em>
              </span>
            </span>
          </h1>
          <p class="screen-sub">
            Everything tailored, filled in, and parked at the submit button. Nothing ships without you.
          </p>

          <div class="paper-card intake-card">
            <textarea
              rows={2}
              spellcheck={false}
              value={jobInput()}
              onInput={(e) => setJobInput(e.currentTarget.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault()
                  if (hasIntake() && !isSubmitting()) void handleSubmit()
                }
              }}
              placeholder="Paste job links, one or five at a time…"
              aria-label="Job intake"
            />
            <div class="intake-foot">
              <span class="intake-portals">greenhouse · lever · ashby · workday · icims · taleo</span>
              <button class="btn-wax" type="button" disabled={!hasIntake() || isSubmitting()} onClick={() => void handleSubmit()}>
                Prepare applications <span class="return-hint">↵</span>
              </button>
            </div>
            <label class="automation-option">
              <input type="checkbox" checked={autoSubmit()} onChange={(e) => setAutoSubmit(e.currentTarget.checked)} />
              <span>
                <strong>Auto-submit after review</strong>
                You still review and approve the tailored documents. After that approval, this run
                submits on its own — no second confirmation click.
              </span>
            </label>
            <Show when={error() ?? queueState.error}>
              {(message) => <div class="error-box" style={{ 'margin-top': '10px' }}>{message()}</div>}
            </Show>
          </div>

          <div class="rule-row ledger-head">
            <span class="kicker">IN FLIGHT</span>
            <span class="rule" />
            <span class="ledger-count">{workingRuns().length} WORKING</span>
          </div>

          <div class="ledger">
            <For each={workingRuns()}>
              {(run, index) => {
                const target = () => targetFor(run)
                const stage = () => WORKING_LABELS[run.status] ?? { label: 'Working', width: '30%' }
                const live = () => run.status === 'RUNNING_AUTOMATION'
                return (
                  <button
                    class="ledger-row"
                    type="button"
                    style={{ 'animation-delay': `${index() * 0.12}s` }}
                    onClick={() => void openRun(run)}
                  >
                    <span class="row-initial">{jobLabel(target(), run.id).charAt(0).toUpperCase()}</span>
                    <span class="row-body">
                      <span class="row-title-line">
                        <span class="serif-title">{jobLabel(target(), run.id)}</span>
                        <Show when={portalChip(target())}>{(chip) => <span class="mono-chip">{chip()}</span>}</Show>
                      </span>
                      <span class="row-status-line">
                        <span class="row-status" classList={{ live: live() }}>
                          {stage().label}
                        </span>
                        <span class="progress-track">
                          <span
                            class="progress-fill"
                            classList={{ sweep: !live(), live: live() }}
                            style={{ display: 'block', width: stage().width }}
                          />
                        </span>
                        <Show when={live()}>
                          <span class="row-metric live">LIVE</span>
                        </Show>
                      </span>
                    </span>
                    <span class="pulse-dot" classList={{ live: live() }} />
                  </button>
                )
              }}
            </For>
            <For each={queuedItems()}>
              {(item) => {
                const target = () => queueState.jobTargetMap[item.jobTargetId]
                return (
                  <div class="ledger-row">
                    <span class="row-initial">{jobLabel(target(), item.id).charAt(0).toUpperCase()}</span>
                    <span class="row-body">
                      <span class="row-title-line">
                        <span class="serif-title">{jobLabel(target(), item.id)}</span>
                        <Show when={portalChip(target())}>{(chip) => <span class="mono-chip">{chip()}</span>}</Show>
                      </span>
                      <span class="row-status-line">
                        <span class="row-status muted">Queued · starts when a worker frees up</span>
                      </span>
                    </span>
                    <span class="pulse-dot idle" />
                  </div>
                )
              }}
            </For>
            <Show when={workingRuns().length === 0 && queuedItems().length === 0}>
              <div class="empty-state">
                <span>Nothing in flight. Paste a job link above and the machines get to work.</span>
              </div>
            </Show>
          </div>

          <div class="home-foot">
            <span>LOCAL VAULT ENCRYPTED · 0 BYTES LEAVE THIS MACHINE</span>
            <span class="foot-right">{submittedThisWeek()} SUBMITTED THIS WEEK</span>
          </div>
        </div>

        <aside class="signature-rail" aria-label="Awaiting your signature">
          <div class="rail-head">
            <span class="kicker kicker-wax">AWAITING YOUR SIGNATURE</span>
            <Show when={signatureRuns().length > 0}>
              <span class="rail-count">{signatureRuns().length}</span>
            </Show>
          </div>
          <For each={signatureRuns().slice(0, 8)}>
            {(run, index) => {
              const copy = () => RAIL_COPY[run.status] ?? DEFAULT_RAIL_COPY
              return (
                <div class="rail-card" classList={{ ready: copy().kind === 'ready' }} style={{ 'animation-delay': `${Math.min(0.3 + index() * 0.12, 1)}s` }}>
                  <Show when={copy().kind === 'ready'}>
                    <span class="ready-stamp">READY</span>
                  </Show>
                  <div class="rail-title">{jobLabel(targetFor(run), run.id)}</div>
                  <div class="rail-sub">{copy().sub}</div>
                  <button
                    type="button"
                    class="rail-action"
                    classList={{
                      'btn-wax': copy().kind === 'ready',
                      'btn-outline-wax': copy().kind === 'outline',
                      'btn-quiet': copy().kind === 'mono',
                    }}
                    onClick={() => void openRun(run)}
                  >
                    {copy().action}
                  </button>
                </div>
              )
            }}
          </For>
          <Show when={signatureRuns().length > 8}>
            <button class="btn-mono" type="button" onClick={() => navigate('/history')}>
              +{signatureRuns().length - 8} MORE IN HISTORY
            </button>
          </Show>
          <Show when={signatureRuns().length === 0}>
            <div class="empty-state">
              <span>Nothing needs you right now.</span>
            </div>
          </Show>
          <div class="rail-quote">"An evening of drudgery, reduced to ten minutes of signatures."</div>
        </aside>
      </div>
    </section>
  )
}
