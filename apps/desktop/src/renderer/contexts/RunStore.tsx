import { createContext, onCleanup, untrack, useContext, type ParentProps } from 'solid-js'
import { createStore } from 'solid-js/store'
import { useToast } from '../components/Toast'
import type {
  ApplicationAnswer,
  ApplicationRun,
  ApplicationStep,
  Approval,
  BrowserArtifact,
  GeneratedFile,
  ReviewRequest,
  RunEvent,
  SafeRendererRunEvent,
  Screenshot,
} from '@applyocalypse/shared-types'
import { runControlAccepted, runControlMessage } from './storeUtils'

type RunDetailType = {
  run: ApplicationRun
  steps: ApplicationStep[]
  answers: ApplicationAnswer[]
  reviewRequests: ReviewRequest[]
  generatedFiles: GeneratedFile[]
  browserArtifacts: BrowserArtifact[]
  events: RunEvent[]
}

type RunState = {
  activeRunId: string
  runDetail: RunDetailType | null
  screenshots: Screenshot[]
  events: SafeRendererRunEvent[]
  isLoading: boolean
  error: string | null
}

export type { RunDetailType }

type RunStoreValue = {
  state: RunState
  loadRunDetail: (runId: string) => Promise<void>
  updateAnswer: (answerId: string, userValue: string | null, status: 'EDITED' | 'REJECTED') => Promise<void>
  pauseActiveRun: () => Promise<void>
  resumeActiveRun: () => Promise<void>
  cancelActiveRun: () => Promise<void>
  retryCurrentStep: () => Promise<void>
  skipCurrentStep: () => Promise<void>
  resolveReviewRequest: (reviewRequestId: string, status: 'APPROVED' | 'REJECTED', reason?: string) => Promise<void>
  approveFinalSubmit: (approvalType?: Approval['approvalType']) => Promise<void>
  rejectFinalSubmit: (reason: string, approvalType?: Approval['approvalType']) => Promise<void>
  pushEvent: (event: SafeRendererRunEvent) => void
}

const RunContext = createContext<RunStoreValue>()

export const RunStoreProvider = (props: ParentProps) => {
  const toast = useToast()
  let runEventUnsubscribe: (() => void) | null = null

  const [state, setState] = createStore<RunState>({
    activeRunId: '',
    runDetail: null,
    screenshots: [],
    events: [],
    isLoading: false,
    error: null,
  })

  onCleanup(() => {
    runEventUnsubscribe?.()
  })

  const pushEvent = (event: SafeRendererRunEvent): void => {
    setState('events', (events) => [event, ...events].slice(0, 200))
  }

  const getActiveRunId = (): string | null =>
    (state.runDetail?.run.id ?? state.activeRunId) || null

  const refreshActiveRunDetail = async (runId = state.activeRunId): Promise<void> => {
    if (!runId) return
    try {
      const [runDetail, screenshots] = await Promise.all([
        window.applyocalypse.runs.getDetail(runId),
        window.applyocalypse.screenshots.list(runId),
      ])
      setState('runDetail', runDetail)
      setState('screenshots', screenshots.items)
      setState('error', null)
    } catch (error) {
      setState('error', error instanceof Error ? error.message : 'Unable to refresh run detail')
    }
  }

  const loadRunDetail = async (runId: string): Promise<void> => {
    setState('isLoading', true)
    try {
      const runDetail = await window.applyocalypse.runs.getDetail(runId)
      setState('activeRunId', runId)
      setState('runDetail', runDetail)
      runEventUnsubscribe?.()
      // The main-process log feed is an external push source, not a Solid signal.
      // untrack keeps it from ever registering as a dependency of whatever
      // computation happened to be running when the subscription was opened.
      runEventUnsubscribe = window.applyocalypse.logs.subscribe(runId, (event) =>
        untrack(() => {
          pushEvent(event)
          void refreshActiveRunDetail(runId)
        })
      )
      setState('error', null)
    } catch (error) {
      setState('error', error instanceof Error ? error.message : 'Unable to load run detail')
    } finally {
      setState('isLoading', false)
    }
  }

  const updateAnswer = async (answerId: string, userValue: string | null, status: 'EDITED' | 'REJECTED'): Promise<void> => {
    const runId = state.runDetail?.run.id
    if (!runId) {
      setState('error', 'No active run detail loaded.')
      return
    }
    try {
      const answer = await window.applyocalypse.runs.updateAnswer(runId, answerId, userValue, status)
      setState('runDetail', 'answers', (answers) => answers.map((item) => (item.id === answer.id ? answer : item)))
      setState('error', null)
    } catch (error) {
      setState('error', error instanceof Error ? error.message : 'Unable to update answer')
    }
  }

  const pauseActiveRun = async (): Promise<void> => {
    const runId = getActiveRunId()
    if (!runId) { setState('error', 'Select a run before pausing.'); return }
    try {
      const result = await window.applyocalypse.runs.pause(runId)
      if (!runControlAccepted(result)) {
        const msg = runControlMessage(result, 'Unable to pause this run.')
        setState('error', msg); toast.error(msg)
      } else {
        setState('error', null); toast.info('Run paused')
      }
      await refreshActiveRunDetail(runId)
    } catch (error) {
      const msg = error instanceof Error ? error.message : 'Unable to pause this run.'
      setState('error', msg); toast.error(msg)
    }
  }

  const resumeActiveRun = async (): Promise<void> => {
    const runId = getActiveRunId()
    if (!runId) { setState('error', 'Select a run before resuming.'); return }
    try {
      const result = await window.applyocalypse.runs.resume(runId)
      if (!runControlAccepted(result)) {
        setState('error', runControlMessage(result, 'Unable to resume this run.'))
        await refreshActiveRunDetail(runId)
        return
      }
      await refreshActiveRunDetail(runId)
      setState('error', null)
    } catch (error) {
      setState('error', error instanceof Error ? error.message : 'Unable to resume this run.')
    }
  }

  const cancelActiveRun = async (): Promise<void> => {
    const runId = getActiveRunId()
    if (!runId) { setState('error', 'Select a run before cancelling.'); return }
    try {
      const result = await window.applyocalypse.runs.cancel(runId)
      if (!runControlAccepted(result)) {
        const msg = runControlMessage(result, 'Unable to cancel this run.')
        setState('error', msg); toast.error(msg)
      } else {
        setState('error', null); toast.info('Run cancelled')
      }
      await refreshActiveRunDetail(runId)
    } catch (error) {
      const msg = error instanceof Error ? error.message : 'Unable to cancel this run.'
      setState('error', msg); toast.error(msg)
    }
  }

  const retryCurrentStep = async (): Promise<void> => {
    const runId = getActiveRunId()
    const stepId =
      state.runDetail?.run.currentStepId ??
      state.runDetail?.steps.find((s) => s.status === 'FAILED')?.id
    if (!runId || !stepId) { setState('error', 'Select a run with a retryable step.'); return }
    try {
      const result = await window.applyocalypse.runs.retryStep(runId, stepId)
      if (!runControlAccepted(result)) {
        setState('error', runControlMessage(result, 'Unable to retry this step.'))
        await refreshActiveRunDetail(runId)
        return
      }
      await refreshActiveRunDetail(runId)
      setState('error', null)
    } catch (error) {
      setState('error', error instanceof Error ? error.message : 'Unable to retry this step.')
    }
  }

  const skipCurrentStep = async (): Promise<void> => {
    const runId = getActiveRunId()
    const stepId =
      state.runDetail?.run.currentStepId ??
      state.runDetail?.steps.find((s) => ['PENDING', 'WAITING_FOR_USER', 'PAUSED', 'FAILED'].includes(s.status))?.id
    if (!runId || !stepId) { setState('error', 'Select a run with a safe step to skip.'); return }
    try {
      const result = await window.applyocalypse.runs.skipStep(runId, stepId)
      if (!runControlAccepted(result)) {
        setState('error', runControlMessage(result, 'Unable to skip this step.'))
        await refreshActiveRunDetail(runId)
        return
      }
      await refreshActiveRunDetail(runId)
      setState('error', null)
    } catch (error) {
      setState('error', error instanceof Error ? error.message : 'Unable to skip this step.')
    }
  }

  const resolveReviewRequest = async (reviewRequestId: string, status: 'APPROVED' | 'REJECTED', reason?: string): Promise<void> => {
    const runId = getActiveRunId()
    if (!runId) { setState('error', 'Select a run before resolving review.'); return }
    try {
      const result = await window.applyocalypse.runs.resolveReview(runId, reviewRequestId, status, reason)
      if (!runControlAccepted(result)) {
        setState('error', runControlMessage(result, 'Unable to resolve review'))
        await refreshActiveRunDetail(runId)
        return
      }
      await refreshActiveRunDetail(runId)
      setState('error', null)
    } catch (error) {
      setState('error', error instanceof Error ? error.message : 'Unable to resolve review')
    }
  }

  const approveFinalSubmit = async (requestedApprovalType?: Approval['approvalType']): Promise<void> => {
    const runId = getActiveRunId()
    if (!runId) { setState('error', 'Select a run before approving final submit.'); return }
    const openReview = state.runDetail?.reviewRequests.find((r) => r.status === 'OPEN')
    const approvalType: Approval['approvalType'] =
      requestedApprovalType ??
      (openReview?.reviewType === 'DOCUMENT'
        ? 'DOCUMENT_APPROVAL'
        : openReview?.reviewType === 'OTP'
          ? 'OTP_READ'
          : openReview?.reviewType === 'FINAL_SUBMIT'
            ? 'FINAL_SUBMIT'
            : 'ANSWER_EDIT')
    try {
      const result = await window.applyocalypse.runs.approve(runId, approvalType)
      if (!runControlAccepted(result)) {
        setState('error', runControlMessage(result, 'Unable to approve this run.'))
        await refreshActiveRunDetail(runId)
        return
      }
      await refreshActiveRunDetail(runId)
      setState('error', null)
    } catch (error) {
      setState('error', error instanceof Error ? error.message : 'Unable to approve this run.')
    }
  }

  const rejectFinalSubmit = async (reason: string, approvalType: Approval['approvalType'] = 'FINAL_SUBMIT'): Promise<void> => {
    const runId = getActiveRunId()
    if (!runId) { setState('error', 'Select a run before rejecting final submit.'); return }
    try {
      const result = await window.applyocalypse.runs.reject(runId, reason, approvalType)
      if (!runControlAccepted(result)) setState('error', runControlMessage(result, 'Unable to reject this run.'))
      else setState('error', null)
      await refreshActiveRunDetail(runId)
    } catch (error) {
      setState('error', error instanceof Error ? error.message : 'Unable to reject this run.')
    }
  }

  return (
    <RunContext.Provider
      value={{
        state,
        loadRunDetail,
        updateAnswer,
        pauseActiveRun,
        resumeActiveRun,
        cancelActiveRun,
        retryCurrentStep,
        skipCurrentStep,
        resolveReviewRequest,
        approveFinalSubmit,
        rejectFinalSubmit,
        pushEvent,
      }}
    >
      {props.children}
    </RunContext.Provider>
  )
}

export const useRunStore = (): RunStoreValue => {
  const ctx = useContext(RunContext)
  if (!ctx) throw new Error('RunStoreProvider is missing')
  return ctx
}
