import { createMemo, createSignal, For, onCleanup, Show } from 'solid-js'
import { DEFAULT_MAX_CONCURRENT_APPLICATIONS } from '@applyocalypse/config'
import { useNavigate } from '@solidjs/router'
import type { ApplicationRun } from '@applyocalypse/shared-types'
import { useProfileStore } from '../contexts/ProfileStore'
import { jobLabel, useQueueStore } from '../contexts/QueueStore'
import { MissionTile } from '../features/missions/MissionTile'
import { useRunStore } from '../contexts/RunStore'
import { useSettingsStore } from '../contexts/SettingsStore'
import { parseJobIntake } from '../features/intake/parseJobIntake'
import { profileReadiness } from '@applyocalypse/shared-types'

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

const dateKicker = (): string => {
  const now = new Date()
  const day = now.toLocaleDateString('en-US', { weekday: 'long', month: 'long', day: 'numeric' })
  const time = now.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', hour12: false })
  return `${day} · ${time}`
}

export default function HomeScreen() {
  const { state: profileState } = useProfileStore()
  const { state: queueState, enqueueJobText, cancelPausedRuns } = useQueueStore()
  const { loadRunDetail } = useRunStore()
  const { state: settingsState } = useSettingsStore()
  const navigate = useNavigate()

  const [jobInput, setJobInput] = createSignal('')
  // Null until the user touches the checkbox; until then it follows the Settings default.
  const [autoSubmitChoice, setAutoSubmit] = createSignal<boolean | null>(null)
  const autoSubmit = () => autoSubmitChoice() ?? settingsState.settings['automation.autoSubmitByDefault'] === true
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
    if (waiting === 1) return 'One application is waiting for you.'
    if (waiting > 1) return `${waiting} applications are waiting for you.`
    if (workingRuns().length > 0) return 'The machines are hard at work.'
    return 'Paste a link. We do the drudgery.'
  })

  const recentSent = createMemo(() => {
    const cutoff = Date.now() - 24 * 60 * 60 * 1000
    return queueState.applicationRuns
      .filter(
        (run) =>
          (run.status === 'SUBMITTED' || run.status === 'COMPLETED') &&
          run.completedAt !== null &&
          Date.parse(run.completedAt) >= cutoff
      )
      .slice(0, 4)
  })

  const TILE_LIMIT = 12
  const activeRuns = createMemo(() => [...signatureRuns(), ...workingRuns()])
  const hasPaused = createMemo(() => signatureRuns().some((run) => run.status === 'PAUSED'))

  const intakeCount = createMemo(() => parseJobIntake(jobInput()).length)
  const hasIntake = createMemo(() => intakeCount() > 0)

  /**
   * Queueing a job the profile cannot carry produces a run that stops partway or
   * fills blanks, and the user only finds out once it is running. The gaps are
   * knowable here, before anything is queued, so this is where they are said.
   */
  const readiness = createMemo(() => profileReadiness(profileState.canonicalProfile))

  /**
   * The scheduler runs at most this many applications at once, and everything
   * else waits. Pasting twenty links looks like twenty parallel runs until the
   * dashboard fills with queued rows, so say it at the point of paste.
   */
  const concurrencyCap = createMemo(() => {
    const raw = settingsState.settings['automation.maxConcurrentApplications']
    return typeof raw === 'number' && Number.isInteger(raw) ? raw : DEFAULT_MAX_CONCURRENT_APPLICATIONS
  })

  const handleSubmit = async () => {
    const profileId = profileState.profile?.id
    if (!profileId) {
      setError('Create a profile before adding job targets.')
      return
    }
    if (!readiness().isReady) {
      setError('Finish setting up before queueing jobs. The list above says what is left.')
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
    <section class="screen missions" data-gsap="panel" data-view-panel>
      <div class="page-scroll">
        <header class="page-head">
          <div class="page-kicker">{nowKicker()}</div>
          <h1 class="page-title">{headline()}</h1>
        </header>

        <div class="card intake-card">
          <Show when={!readiness().isReady}>
            <div class="setup-gaps" role="status">
              <div class="setup-gaps-head">Before this can apply for you</div>
              <For each={readiness().gaps}>
                {(gap) => (
                  <button class="setup-gap" type="button" onClick={() => navigate(gap.route)}>
                    <strong>{gap.label}</strong>
                    <span>{gap.fix}</span>
                  </button>
                )}
              </For>
            </div>
          </Show>
          <div class="intake-row">
            <textarea
              rows={1}
              spellcheck={false}
              value={jobInput()}
              onInput={(e) => setJobInput(e.currentTarget.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault()
                  if (hasIntake() && readiness().isReady && !isSubmitting()) void handleSubmit()
                }
              }}
              placeholder="Paste job links, one or five at a time…"
              aria-label="Job intake"
            />
            <button
              class="btn-wax"
              type="button"
              disabled={!hasIntake() || !readiness().isReady || isSubmitting()}
              onClick={() => void handleSubmit()}
            >
              {isSubmitting() ? 'Preparing…' : 'Prepare'}
            </button>
          </div>
          <div class="intake-foot">
            <label class="automation-option">
              <input type="checkbox" checked={autoSubmit()} onChange={(e) => setAutoSubmit(e.currentTarget.checked)} />
              <span>
                <strong>Submit on its own after I approve</strong>
                You still review the tailored documents and any held answers. After that, this run sends itself
                with no second click.
              </span>
            </label>
            <span class="intake-portals">Greenhouse, Lever, Ashby, Workday, iCIMS, Taleo</span>
          </div>
          <Show when={intakeCount() > concurrencyCap()}>
            <p class="intake-pace" role="status">
              {intakeCount()} links. {concurrencyCap()} run at a time; the rest wait their turn.
              <button type="button" onClick={() => navigate('/settings')}>
                Change the pace
              </button>
            </p>
          </Show>
          <Show when={error() ?? queueState.error}>
            {(message) => <div class="error-box">{message()}</div>}
          </Show>
        </div>

        <div class="section-head">
          <h2>Your queue</h2>
          <span class="section-count">{activeRuns().length + queuedItems().length}</span>
          <Show when={hasPaused()}>
            <button class="btn-quiet" type="button" title="Cancel all paused runs" onClick={() => void cancelPausedRuns()}>
              Clear paused
            </button>
          </Show>
        </div>

        <Show
          when={activeRuns().length + queuedItems().length + recentSent().length > 0}
          fallback={
            <Show when={!queueState.isLoading}>
              <div class="card empty-card">
                <strong>Nothing in the queue</strong>
                <span>
                  Paste a job link above. It gets read, tailored and filled here, and waits for you before anything is
                  sent.
                </span>
              </div>
            </Show>
          }
        >
          <div class="tiles">
            <For each={activeRuns().slice(0, TILE_LIMIT)}>
              {(run, index) => (
                <MissionTile
                  status={run.status}
                  target={targetFor(run)}
                  fallbackName={jobLabel(targetFor(run), run.id)}
                  hero={index() === 0 && run.status === 'READY_TO_SUBMIT'}
                  delay={Math.min(index() * 60, 480)}
                  onOpen={() => void openRun(run)}
                />
              )}
            </For>
            <For each={queuedItems().slice(0, Math.max(0, TILE_LIMIT - activeRuns().length))}>
              {(item, index) => (
                <MissionTile
                  status="PENDING"
                  target={queueState.jobTargetMap[item.jobTargetId]}
                  fallbackName={jobLabel(queueState.jobTargetMap[item.jobTargetId], item.id)}
                  delay={Math.min((activeRuns().length + index()) * 60, 480)}
                />
              )}
            </For>
            <For each={recentSent()}>
              {(run, index) => (
                <MissionTile
                  status={run.status}
                  target={targetFor(run)}
                  fallbackName={jobLabel(targetFor(run), run.id)}
                  completedAt={run.completedAt}
                  delay={Math.min((activeRuns().length + index()) * 60 + 60, 540)}
                  onOpen={() => navigate('/history')}
                />
              )}
            </For>
          </div>
          <Show when={activeRuns().length + queuedItems().length > TILE_LIMIT}>
            <button class="link-button" type="button" onClick={() => navigate('/history')}>
              {activeRuns().length + queuedItems().length - TILE_LIMIT} more in History
            </button>
          </Show>
        </Show>

        <footer class="page-foot">
          <span>Everything stays encrypted on this computer.</span>
          <span>{submittedThisWeek()} sent this week</span>
        </footer>
      </div>
    </section>
  )
}
