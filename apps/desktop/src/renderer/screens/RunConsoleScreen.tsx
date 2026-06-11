import { For, Show, createEffect, createMemo, onMount } from 'solid-js'
import { FileText, FolderOpen, Pause, Play, RefreshCcw, ShieldCheck, SkipForward, Square } from 'lucide-solid'
import type { ApplicationAnswer, Approval, ReviewRequest } from '@applyocalypse/shared-types'
import { useRunStore } from '../contexts/RunStore'
import { useProfileStore } from '../contexts/ProfileStore'
import { buildCoverLetterRequirementSummary } from '../features/run-console/materialRequirementsView'
import { buildPortalWorkflowSummary, formatWorkflowKind } from '../features/run-console/portalWorkflowView'
import { gsap } from '../animations/gsap'

const artifactUrlForPath = (p: string) => `applyocalypse://artifact?path=${encodeURIComponent(p)}`

const answerApplySummary = (answer: ApplicationAnswer): string => {
  const m = answer.applyMetadata ?? {}
  const action = typeof m['appliedAction'] === 'string' ? m['appliedAction'] : null
  const label  = typeof m['selectedLabel'] === 'string' ? m['selectedLabel'] : null
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

const REVIEW_INSTRUCTIONS: Record<string, string> = {
  OTP:                'Enter the code in the portal, then mark handled.',
  CAPTCHA:            'Complete the challenge in the portal, then resume.',
  MFA:                'Approve the sign-in challenge, then resume.',
  LOGIN:              'Sign in to the portal, then resume.',
  PORTAL_ENTRY:       'Click the apply action in the browser, then resume.',
  PORTAL_STEP:        'Click the Next/Continue action in the browser, then resume.',
  AMBIGUOUS_QUESTION: 'Review and edit the detected answer before continuing.',
  ANSWER:             'Review all field answers, then approve before continuing.',
  DOCUMENT:           'Review generated documents, then approve to continue.',
  FINAL_SUBMIT:       'Final submission is blocked until approved.',
}

const reviewInstruction = (t: string) => REVIEW_INSTRUCTIONS[t] ?? 'Review the request before continuing.'

const reviewCandidateLabels = (r: ReviewRequest): string[] => {
  const arr = r.payload['candidate_labels'] ?? r.payload['attempted_labels']
  return Array.isArray(arr) ? arr.filter((l): l is string => typeof l === 'string').slice(0, 6) : []
}

export default function RunConsoleScreen() {
  const {
    state,
    updateAnswer,
    pauseActiveRun, resumeActiveRun, cancelActiveRun,
    retryCurrentStep, skipCurrentStep,
    resolveReviewRequest, approveFinalSubmit, rejectFinalSubmit,
  } = useRunStore()
  const { openLocalPath } = useProfileStore()

  let imgRef: HTMLImageElement | undefined
  let approvalRef: HTMLButtonElement | undefined
  let prevSrc = ''
  const rejectReason = 'Final submit rejected by local user.'

  const portalWorkflow     = createMemo(() => buildPortalWorkflowSummary(state.runDetail?.events ?? state.events))
  const coverLetter        = createMemo(() => buildCoverLetterRequirementSummary(state.runDetail?.events ?? state.events))
  const latestScreenshot   = createMemo(() => state.screenshots[state.screenshots.length - 1])

  // Cross-fade when screenshot changes
  createEffect(() => {
    const shot = latestScreenshot()
    if (!shot || !imgRef) return
    const newSrc = artifactUrlForPath(shot.localPath)
    if (newSrc === prevSrc) return
    prevSrc = newSrc
    gsap.to(imgRef, {
      opacity: 0, duration: 0.15, ease: 'power2.in',
      onComplete: () => {
        if (imgRef) { imgRef.src = newSrc; gsap.to(imgRef, { opacity: 1, duration: 0.25, ease: 'power2.out' }) }
      },
    })
  })

  // Breathing glow on READY_TO_SUBMIT
  createEffect(() => {
    if (state.runDetail?.run.status === 'READY_TO_SUBMIT' && approvalRef) {
      gsap.to(approvalRef, {
        boxShadow: '0 0 32px rgba(52,211,153,0.6), 0 0 64px rgba(52,211,153,0.2)',
        duration: 1.4, repeat: -1, yoyo: true, ease: 'sine.inOut',
      })
    }
  })

  onMount(() => {
    gsap.from('.run-console', { opacity: 0, y: 14, scale: 0.992, duration: 0.5, ease: 'power3.out' })
  })

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

  const openReviews = createMemo(() => state.runDetail?.reviewRequests.filter((r) => r.status === 'OPEN') ?? [])

  return (
    <section class="run-console surface-panel surface-panel-active" data-gsap="panel" data-view-panel>
      {/* ── Top status bar ── */}
      <div class="section-header">
        <div>
          <div class="panel-kicker">Complete Control</div>
          <h2>Live run console</h2>
        </div>
        <div class="run-status">
          <span class="pulse-dot" />
          {state.runDetail ? state.runDetail.run.status : 'Waiting for queue'}
        </div>
      </div>

      {/* ── 3-column body ── */}
      <div class="console-columns">

        {/* Left: step timeline */}
        <div class="console-left">
          <div class="panel-kicker">Steps</div>
          <Show
            when={state.runDetail?.steps.length}
            fallback={<p class="fine-print" style={{ color: 'var(--muted)' }}>No steps yet</p>}
          >
            <div class="step-timeline">
              <For each={state.runDetail?.steps ?? []}>
                {(step) => (
                  <div
                    class="step-row"
                    classList={{ active: step.id === state.runDetail?.run.currentStepId }}
                    data-list-item
                  >
                    <div class={`step-dot step-dot-${step.status.toLowerCase()}`} />
                    <div class="step-info">
                      <span class="step-type">{step.stepType}</span>
                      <small class="step-status">{step.status}</small>
                    </div>
                  </div>
                )}
              </For>
            </div>
          </Show>
        </div>

        {/* Center: browser preview */}
        <div class="console-center">
          <Show
            when={latestScreenshot()}
            fallback={
              <div class="screenshot-placeholder">
                <span style={{ color: 'var(--muted)', 'font-size': '0.82rem' }}>Browser not active</span>
              </div>
            }
          >
            <img
              ref={imgRef}
              src={latestScreenshot() ? artifactUrlForPath(latestScreenshot()!.localPath) : ''}
              alt="Latest browser screenshot"
              class="browser-screenshot"
            />
          </Show>
          <Show when={state.runDetail}>
            <div class="browser-meta" style={{ 'font-size': '0.72rem', color: 'var(--muted)', 'margin-top': '0.5rem' }}>
              {state.runDetail?.run.status} · run {state.runDetail?.run.id.slice(0, 8)}
            </div>
          </Show>

          {/* Event stream */}
          <div class="event-stream" style={{ 'margin-top': '1rem', 'max-height': '220px', overflow: 'auto' }}>
            <div class="panel-kicker">Raw event stream</div>
            <For each={state.runDetail?.events ?? state.events}>
              {(event) => (
                <div class="event-line">
                  <span>{event.severity}</span>
                  <p>{event.message}</p>
                </div>
              )}
            </For>
          </div>
        </div>

        {/* Right: controls + answers */}
        <div class="console-right">
          {/* Control buttons */}
          <div class="control-row">
            <button class="icon-button" type="button" aria-label="Pause" disabled={!state.runDetail} onClick={() => void pauseActiveRun()}>
              <Pause size={17} aria-hidden="true" />
            </button>
            <button class="icon-button" type="button" aria-label="Resume" disabled={!state.runDetail} onClick={() => void resumeActiveRun()}>
              <Play size={17} aria-hidden="true" />
            </button>
            <button class="icon-button" type="button" aria-label="Retry" disabled={!state.runDetail} onClick={() => void retryCurrentStep()}>
              <RefreshCcw size={17} aria-hidden="true" />
            </button>
            <button class="icon-button" type="button" aria-label="Skip" disabled={!state.runDetail} onClick={() => void skipCurrentStep()}>
              <SkipForward size={17} aria-hidden="true" />
            </button>
            <button class="icon-button danger" type="button" aria-label="Cancel" disabled={!state.runDetail} onClick={() => void cancelActiveRun()}>
              <Square size={15} aria-hidden="true" />
            </button>
          </div>

          {/* Review cards */}
          <Show when={openReviews().length > 0}>
            <div class="review-actions">
              <div class="panel-kicker">Open review</div>
              <For each={openReviews()}>
                {(request) => (
                  <div class="review-card">
                    <strong>{request.reviewType}</strong>
                    <p>{request.prompt}</p>
                    <small>{reviewInstruction(request.reviewType)}</small>
                    <Show when={reviewCandidateLabels(request).length > 0}>
                      <div class="workflow-chip-row">
                        <For each={reviewCandidateLabels(request)}>{(l) => <span>{l}</span>}</For>
                      </div>
                    </Show>
                    <div class="review-card-actions">
                      <button class="secondary-action" type="button" onClick={() => void approveReview(request)}>
                        <ShieldCheck size={17} aria-hidden="true" />
                        <span>{isManualBlocker(request.reviewType) ? 'Handled' : 'Approve'}</span>
                      </button>
                      <button class="secondary-action danger-text" type="button" onClick={() => void rejectReview(request)}>
                        <Square size={14} aria-hidden="true" />
                        <span>Reject</span>
                      </button>
                    </div>
                  </div>
                )}
              </For>
            </div>
          </Show>

          {/* Final submit approval gate */}
          <Show when={state.runDetail?.run.status === 'READY_TO_SUBMIT'}>
            <div style={{ display: 'flex', gap: '0.5rem', 'margin-top': '1rem' }}>
              <button
                ref={approvalRef}
                class="primary-action"
                type="button"
                style={{ flex: '1', background: 'var(--success-soft)', color: 'var(--success)', border: '1px solid var(--success)' }}
                onClick={() => void approveFinalSubmit()}
              >
                <ShieldCheck size={17} aria-hidden="true" />
                <span>Approve Final Submit</span>
              </button>
              <button class="secondary-action danger-text" type="button" onClick={() => void rejectFinalSubmit(rejectReason)}>
                <Square size={14} aria-hidden="true" />
                <span>Reject</span>
              </button>
            </div>
          </Show>

          {/* Generated artifacts */}
          <Show when={(state.runDetail?.generatedFiles.length ?? 0) > 0}>
            <div class="generated-files">
              <div class="panel-kicker">Generated artifacts</div>
              <For each={state.runDetail?.generatedFiles ?? []}>
                {(file) => (
                  <button class="artifact-row" type="button" onClick={() => void openLocalPath(file.localPath)}>
                    <FileText size={16} aria-hidden="true" />
                    <span>
                      <strong>{file.filename}</strong>
                      <small>{file.fileKind} / {file.format}</small>
                    </span>
                    <FolderOpen size={15} aria-hidden="true" />
                  </button>
                )}
              </For>
            </div>
          </Show>

          {/* Field answers */}
          <div class="answer-drawer">
            <div class="panel-kicker">Detected fields</div>
            <Show
              when={state.runDetail?.answers.length}
              fallback={
                <p class="fine-print" style={{ color: 'var(--muted)' }}>
                  Fields will appear when the form is reached.
                </p>
              }
            >
              <For each={state.runDetail?.answers ?? []}>
                {(answer) => (
                  <label class="field-row editable-answer">
                    <span class="answer-heading">
                      <span>{answer.fieldLabel}</span>
                      <strong>{answer.status}</strong>
                    </span>
                    <input
                      aria-label={`Answer for ${answer.fieldLabel}`}
                      value={answer.userValue ?? answer.proposedValue ?? ''}
                      onChange={(e) => void updateAnswer(answer.id, e.currentTarget.value, 'EDITED')}
                    />
                    <small class="answer-apply-meta">
                      {answer.fieldType} / {answerApplySummary(answer)}
                    </small>
                  </label>
                )}
              </For>
            </Show>
          </div>
        </div>
      </div>
    </section>
  )
}
