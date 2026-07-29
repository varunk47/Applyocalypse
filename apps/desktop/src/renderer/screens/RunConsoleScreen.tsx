import { For, Show, createEffect, createMemo, createSignal, on } from 'solid-js'
import { useNavigate, useParams } from '@solidjs/router'
import type { ApplicationAnswer, ApplicationStep, Approval, ReviewRequest, SafeRendererRunEvent } from '@applyocalypse/shared-types'
import { useRunStore } from '../contexts/RunStore'
import { useProfileStore } from '../contexts/ProfileStore'
import { jobLabel, useQueueStore } from '../contexts/QueueStore'
import { buildPortalWorkflowSummary } from '../features/run-console/portalWorkflowView'
import { REVIEW_INSTRUCTIONS } from '../features/run-console/reviewInstructions'

const artifactUrlForPath = (p: string) => `applyocalypse://artifact?path=${encodeURIComponent(p)}`

const answerApplySummary = (answer: ApplicationAnswer): string => {
  const m = answer.applyMetadata ?? {}
  const action = typeof m['appliedAction'] === 'string' ? m['appliedAction'] : null
  const label = typeof m['selectedLabel'] === 'string' ? m['selectedLabel'] : null
  const checked = typeof m['checked'] === 'boolean' ? m['checked'] : null
  if (answer.status === 'APPLIED') {
    if (action === 'set_checkbox' && checked !== null) return checked ? 'Checked' : 'Unchecked'
    if (label) return `Selected ${label}`
    return 'Applied'
  }
  if (answer.status === 'EDITED') return 'User-edited'
  if (answer.status === 'APPROVED') return 'Approved'
  if (answer.status === 'REJECTED') return 'Rejected'
  return 'Pending review'
}

const isManualBlocker = (t: string) =>
  ['CAPTCHA', 'MFA', 'OTP', 'AMBIGUOUS_QUESTION', 'LOGIN', 'PORTAL_ENTRY', 'PORTAL_STEP'].includes(t)

const approvalTypeFor = (t: string): Approval['approvalType'] => {
  if (t === 'DOCUMENT') return 'DOCUMENT_APPROVAL'
  if (t === 'ANSWER')   return 'ANSWER_EDIT'
  if (t === 'OTP')      return 'OTP_READ'
  return 'FINAL_SUBMIT'
}

const reviewInstruction = (t: string) => REVIEW_INSTRUCTIONS[t] ?? 'Review the request before continuing.'

/**
 * An emailed confirmation link arrives as an OTP review, but the ask is the
 * opposite of the usual one: the app waits for permission to click, rather than
 * waiting for the user to type a code. The redacted target is what distinguishes
 * the two, so it drives the wording.
 */
const linkApprovalTarget = (r: ReviewRequest): string | null => {
  const target = r.payload['redacted_target']
  return typeof target === 'string' && target.length > 0 ? target : null
}

const reviewCandidateLabels = (r: ReviewRequest): string[] => {
  const arr = r.payload['candidate_labels'] ?? r.payload['attempted_labels']
  return Array.isArray(arr) ? arr.filter((l): l is string => typeof l === 'string').slice(0, 6) : []
}

const NEEDS_YOU_STATUSES = new Set([
  'READY_FOR_REVIEW',
  'PAUSED',
  'BLOCKED_CAPTCHA',
  'BLOCKED_MFA',
  'BLOCKED_OTP',
  'BLOCKED_AMBIGUOUS_QUESTION',
  'WAITING_FOR_USER_EDIT',
  'READY_TO_SUBMIT',
])

const TERMINAL_STATUSES = new Set(['SUBMITTED', 'COMPLETED', 'FAILED', 'CANCELLED'])

const prettyStep = (stepType: string): string => {
  const words = stepType.replace(/[_-]+/g, ' ').toLowerCase()
  return words.charAt(0).toUpperCase() + words.slice(1)
}

const stepRowState = (step: ApplicationStep, currentStepId: string | null): 'done' | 'active' | 'gate' | 'pending' => {
  if (step.status === 'COMPLETED' || step.status === 'SKIPPED') return 'done'
  if (step.status === 'WAITING_FOR_USER' || step.status === 'PAUSED') return 'gate'
  if (step.status === 'RUNNING' || step.status === 'RETRYING' || step.id === currentStepId) return 'active'
  return 'pending'
}

const clockTime = (iso: string): string => {
  const t = new Date(iso)
  return Number.isNaN(t.getTime()) ? '' : t.toTimeString().slice(0, 8)
}

const eventKindClass = (event: SafeRendererRunEvent): string => {
  if (event.severity === 'ERROR' || event.severity === 'CRITICAL' || event.severity === 'WARN') return 'warn'
  const type = String(event.eventType)
  if (type.includes('FILL') || type.includes('UPLOAD') || type.includes('COMPLETED')) return 'ok'
  return ''
}

export default function RunConsoleScreen() {
  const {
    state,
    loadRunDetail,
    updateAnswer,
    pauseActiveRun, resumeActiveRun, cancelActiveRun,
    retryCurrentStep, skipCurrentStep,
    resolveReviewRequest, approveFinalSubmit, rejectFinalSubmit,
  } = useRunStore()
  const { openLocalPath } = useProfileStore()
  const { state: queueState } = useQueueStore()
  const params = useParams<{ runId?: string }>()
  const navigate = useNavigate()

  const rejectReason = 'Final submit rejected by local user.'

  const [controlBusy, setControlBusy] = createSignal(false)
  const [gateBusy, setGateBusy] = createSignal(false)

  const runControl = (action: () => Promise<void>) => {
    if (controlBusy()) return
    setControlBusy(true)
    void action().finally(() => setControlBusy(false))
  }

  // Reactive, not onMount: the router reuses this component instance across
  // /run/:runId param changes, so a mount-only guard would show a stale run.
  createEffect(on(() => params.runId, (runId) => {
    if (runId && runId !== state.activeRunId) {
      void loadRunDetail(runId)
    }
  }))

  const run = () => state.runDetail?.run ?? null
  const events = createMemo(() => state.runDetail?.events ?? state.events)
  const portalWorkflow = createMemo(() => buildPortalWorkflowSummary(events()))
  const latestScreenshot = createMemo(() => state.screenshots[state.screenshots.length - 1])
  // The dedicated READY_TO_SUBMIT gate card below owns FINAL_SUBMIT reviews; including
  // them here rendered two approve-final-submit cards for the same decision.
  const openReviews = createMemo(() => state.runDetail?.reviewRequests.filter((r) => r.status === 'OPEN' && r.reviewType !== 'FINAL_SUBMIT') ?? [])

  const jobTitle = createMemo(() => {
    const detail = run()
    if (!detail) return 'No run selected'
    return jobLabel(queueState.jobTargetMap[detail.jobTargetId], detail.id)
  })

  const addressBarText = createMemo(() => {
    const fromEvents = portalWorkflow()?.currentUrl
    if (fromEvents) return fromEvents
    const detail = run()
    const target = detail ? queueState.jobTargetMap[detail.jobTargetId] : undefined
    return target?.sourceKind === 'URL' ? target.sourceValue : 'about:blank'
  })

  const statusPill = createMemo(() => {
    const detail = run()
    if (!detail) return { text: 'WAITING FOR QUEUE', kind: 'terminal' as const }
    if (NEEDS_YOU_STATUSES.has(detail.status)) return { text: 'PAUSED / NEEDS YOU', kind: 'paused' as const }
    if (TERMINAL_STATUSES.has(detail.status)) return { text: detail.status, kind: 'terminal' as const }
    return { text: detail.status.replace(/_/g, ' '), kind: 'working' as const }
  })

  const nextPendingStep = createMemo(() => state.runDetail?.steps.find((s) => s.status === 'PENDING'))

  const approveReview = async (r: { id: string; reviewType: string }) => {
    if (isManualBlocker(r.reviewType))
      await resolveReviewRequest(r.id, 'APPROVED', `${r.reviewType} handled by local user.`)
    else
      await approveFinalSubmit(approvalTypeFor(r.reviewType))
  }

  const rejectReview = async (r: { id: string; reviewType: string }) => {
    if (isManualBlocker(r.reviewType))
      await resolveReviewRequest(r.id, 'REJECTED', `${r.reviewType} rejected by local user.`)
    else
      await rejectFinalSubmit(rejectReason, approvalTypeFor(r.reviewType))
  }

  const answerStateClass = (answer: ApplicationAnswer): 'applied' | 'edited' | 'yours' => {
    if (answer.status === 'APPLIED' || answer.status === 'APPROVED') return 'applied'
    if (answer.status === 'EDITED') return 'edited'
    return 'yours'
  }

  return (
    <section class="screen run-console" data-gsap="panel" data-view-panel>
      <div class="console-header">
        <button class="btn-mono" type="button" onClick={() => navigate('/')}>← MISSIONS</button>
        <span class="console-title">{jobTitle()}</span>
        <Show when={run()}>
          {(detail) => (
            <span class="console-runid">
              RUN {detail().id.slice(0, 6).toUpperCase()}
              {portalWorkflow()?.displayName ? ` · ${portalWorkflow()!.displayName.toUpperCase()}` : ''}
            </span>
          )}
        </Show>
        <div class="console-actions">
          <span class="status-pill" classList={{
            paused: statusPill().kind === 'paused',
            working: statusPill().kind === 'working',
            terminal: statusPill().kind === 'terminal',
          }}>
            {statusPill().text}
          </span>
          <button class="btn-mono" type="button" disabled={!state.runDetail || controlBusy()} onClick={() => runControl(pauseActiveRun)}>PAUSE</button>
          <button class="btn-mono" type="button" disabled={!state.runDetail || controlBusy()} onClick={() => runControl(resumeActiveRun)}>RESUME</button>
          <button class="btn-mono" type="button" disabled={!state.runDetail || controlBusy()} onClick={() => runControl(retryCurrentStep)}>RETRY</button>
          <button class="btn-mono" type="button" disabled={!state.runDetail || controlBusy()} onClick={() => runControl(skipCurrentStep)}>SKIP</button>
          <button class="btn-mono" type="button" disabled={!state.runDetail || controlBusy()} onClick={() => runControl(cancelActiveRun)}>CANCEL</button>
        </div>
      </div>

      <div class="console-grid">
        {/* Left: run steps */}
        <div class="steps-rail">
          <div class="kicker">RUN STEPS</div>
          <Show
            when={(state.runDetail?.steps.length ?? 0) > 0}
            fallback={<div class="empty-state"><span>No steps yet.</span></div>}
          >
            <div class="steps-track">
              <For each={state.runDetail?.steps ?? []}>
                {(step) => {
                  const rowState = () => stepRowState(step, run()?.currentStepId ?? null)
                  return (
                    <div class="step-row" classList={{
                      done: rowState() === 'done',
                      active: rowState() === 'active',
                      gate: rowState() === 'gate',
                      pending: rowState() === 'pending',
                    }}>
                      <span class="step-marker">{rowState() === 'done' ? '✓' : ''}</span>
                      <span class="step-name">{prettyStep(step.stepType)}</span>
                      <span class="step-meta">
                        {rowState() === 'gate' ? 'GATE' : rowState() === 'done' ? clockTime(step.updatedAt).slice(0, 5) : ''}
                      </span>
                    </div>
                  )
                }}
              </For>
            </div>
          </Show>
          <div class="worker-note">
            <div class="kicker">WHAT THE WORKER MAY DO NEXT</div>
            <div class="note-body">
              <Show when={nextPendingStep()} fallback={<>Nothing yet. This run is waiting on you or finished.</>}>
                {(step) => <><strong>{prettyStep(step().stepType)}</strong>. Nothing submit-shaped. Ever.</>}
              </Show>
            </div>
          </div>
        </div>

        {/* Center: viewport + event ledger */}
        <div class="console-center">
          <div class="viewport-frame">
            <div class="viewport-chrome">
              <span class="browser-dot" />
              <span class="browser-dot" />
              <span class="address-bar">{addressBarText()}</span>
              <Show when={run()?.status === 'RUNNING_AUTOMATION'}>
                <span class="watch-tag"><span class="dot" />WATCHING</span>
              </Show>
            </div>
            <div class="viewport-body">
              <Show
                when={latestScreenshot()}
                fallback={<span>[ LIVE PORTAL VIEWPORT ]<br />SCREENSHOTS APPEAR AS THE WORKER MOVES</span>}
              >
                {(shot) => <img src={artifactUrlForPath(shot().localPath)} alt="Latest browser screenshot" />}
              </Show>
            </div>
          </div>

          <div class="rule-row ledger-title-row">
            <span class="kicker">EVENT LEDGER</span>
            <span class="rule" />
            <span class="kicker">{events().length} EVENTS</span>
          </div>
          <div class="event-ledger">
            <For each={events()}>
              {(event) => (
                <div class="event-row" classList={{ paused: String(event.eventType) === 'PAUSED' }}>
                  <span class="event-time">{clockTime(event.timestamp)}</span>
                  <span class="event-kind" classList={{
                    ok: eventKindClass(event) === 'ok',
                    warn: eventKindClass(event) === 'warn',
                  }}>
                    {String(event.eventType).slice(0, 10)}
                  </span>
                  <span class="event-text">{event.message}</span>
                </div>
              )}
            </For>
            <Show when={events().length === 0}>
              <div class="empty-state"><span>Events will appear as the worker reports in.</span></div>
            </Show>
          </div>
        </div>

        {/* Right: the gate */}
        <div class="gate-rail">
          <div class="rail-head">
            <span class="kicker kicker-wax">
              THE GATE{openReviews().length > 0 ? ` / ${openReviews().length} OPEN` : ''}
            </span>
          </div>

          <For each={openReviews()}>
            {(request) => (
              <div class="gate-card">
                <div class="gate-question">
                  "{request.prompt}" <span class="quiet">({request.reviewType.replace(/_/g, ' ').toLowerCase()})</span>
                </div>
                <div class="house-rule">HOUSE RULE: SENSITIVE ANSWERS ARE NEVER AUTO-FILLED</div>
                <Show when={reviewCandidateLabels(request).length > 0}>
                  <div style={{ display: 'flex', 'flex-wrap': 'wrap', gap: '5px', margin: '0 0 8px' }}>
                    <For each={reviewCandidateLabels(request)}>{(l) => <span class="mono-chip">{l}</span>}</For>
                  </div>
                </Show>
                <Show when={linkApprovalTarget(request)}>
                  {(target) => (
                    <div class="mono-chip" style={{ display: 'block', margin: '0 0 8px', 'word-break': 'break-all' }}>
                      {target()}
                    </div>
                  )}
                </Show>
                <div class="gate-actions">
                  <button class="btn-wax" type="button" onClick={() => void approveReview(request)}>
                    {linkApprovalTarget(request)
                      ? 'Open this link'
                      : isManualBlocker(request.reviewType)
                        ? 'I handled it myself'
                        : 'Approve'}
                  </button>
                  <button class="btn-quiet" type="button" onClick={() => void rejectReview(request)}>
                    Reject
                  </button>
                </div>
                <div class="provenance-tag" style={{ 'margin-top': '8px' }}>
                  {linkApprovalTarget(request)
                    ? 'The token is hidden. Approving lets the automation browser open this destination.'
                    : reviewInstruction(request.reviewType)}
                </div>
              </div>
            )}
          </For>

          <Show when={run()?.status === 'READY_TO_SUBMIT'}>
            <div class="gate-card armed">
              <div class="gate-question">Ready to submit. <span class="quiet">One last look, then it ships.</span></div>
              <div class="house-rule">NOTHING SHIPS WITHOUT YOUR SIGNATURE</div>
              <div class="gate-actions">
                <button
                  class="btn-wax"
                  type="button"
                  disabled={gateBusy()}
                  onClick={() => {
                    if (gateBusy()) return
                    setGateBusy(true)
                    void approveFinalSubmit().finally(() => setGateBusy(false))
                  }}
                >
                  {gateBusy() ? 'Working...' : 'Approve final submit'}
                </button>
                <button
                  class="btn-quiet"
                  type="button"
                  disabled={gateBusy()}
                  onClick={() => {
                    if (gateBusy()) return
                    setGateBusy(true)
                    void rejectFinalSubmit(rejectReason).finally(() => setGateBusy(false))
                  }}
                >
                  Reject
                </button>
              </div>
            </div>
          </Show>

          <div class="rule-row">
            <span class="kicker">DETECTED FIELDS</span>
            <span class="rule" />
          </div>
          <Show
            when={(state.runDetail?.answers.length ?? 0) > 0}
            fallback={<div class="empty-state"><span>Fields appear when the form is reached.</span></div>}
          >
            <div style={{ display: 'flex', 'flex-direction': 'column', gap: '6px' }}>
              <For each={state.runDetail?.answers ?? []}>
                {(answer) => (
                  <label class="field-card" classList={{ yours: answerStateClass(answer) === 'yours' }}>
                    <span class="field-body">
                      <span class="field-label">{answer.fieldLabel}</span>
                      <input
                        aria-label={`Answer for ${answer.fieldLabel}`}
                        class="answer-inline-input"
                        value={answer.userValue ?? answer.proposedValue ?? ''}
                        onChange={(e) => void updateAnswer(answer.id, e.currentTarget.value, 'EDITED')}
                        title={`${answer.fieldType} / ${answerApplySummary(answer)}`}
                      />
                    </span>
                    <span class="field-state" classList={{
                      applied: answerStateClass(answer) === 'applied',
                      edited: answerStateClass(answer) === 'edited',
                      yours: answerStateClass(answer) === 'yours',
                    }}>
                      {answerStateClass(answer) === 'applied' ? 'APPLIED' : answerStateClass(answer) === 'edited' ? 'EDITED' : 'YOURS'}
                    </span>
                  </label>
                )}
              </For>
            </div>
          </Show>

          <Show when={(state.runDetail?.generatedFiles.length ?? 0) > 0}>
            <div style={{ 'margin-top': 'auto', display: 'flex', 'flex-direction': 'column', gap: '6px' }}>
              <div class="kicker">ARTIFACTS</div>
              <For each={state.runDetail?.generatedFiles ?? []}>
                {(file) => (
                  <button class="artifact-row" type="button" onClick={() => void openLocalPath(file.localPath)}>
                    <span class="doc-glyph" aria-hidden="true" />
                    <span class="artifact-name">{file.filename}</span>
                    <span class="artifact-check">{file.fileKind === 'RESUME' ? '1 PAGE ✓' : 'VOICE ✓'}</span>
                  </button>
                )}
              </For>
            </div>
          </Show>
        </div>
      </div>

      <div class="console-foot">
        <span>Nothing is sent until you say go.</span>
        <span class="foot-note">EVERY ACTION AUDIT LOGGED · RUN ARCHIVED LOCALLY</span>
      </div>
    </section>
  )
}
