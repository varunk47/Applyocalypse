import { createContext, onCleanup, useContext, type ParentProps } from 'solid-js'
import { createStore, reconcile } from 'solid-js/store'
import type { ApplicationRun, JobTarget, QueueItem } from '@applyocalypse/shared-types'
import { parseJobIntake } from '../features/intake/parseJobIntake'
import { sleep } from './storeUtils'
import { useToast } from '../components/Toast'

type QueueState = {
  queueItems: QueueItem[]
  applicationRuns: ApplicationRun[]
  jobTargetMap: Record<string, JobTarget>
  queueTotal: number
  runsTotal: number
  isLoading: boolean
  error: string | null
}

export const jobLabel = (target: JobTarget | undefined, fallbackId: string): string => {
  if (!target) return fallbackId.slice(0, 8)
  if (target.company && target.role) return `${target.company} / ${target.role}`
  if (target.company) return target.company
  if (target.role) return target.role
  if (target.sourceKind === 'URL') {
    try { return new URL(target.sourceValue).hostname } catch { /* ignore */ }
  }
  return target.sourceValue.slice(0, 48)
}

type QueueStoreValue = {
  state: QueueState
  enqueueJobText: (
    value: string,
    profileId: string,
    options?: { autoSubmitEnabled?: boolean; onRunReady?: (runId: string) => Promise<void> }
  ) => Promise<boolean>
  refreshQueue: () => Promise<void>
  refreshRuns: () => Promise<void>
  cancelPausedRuns: () => Promise<number>
}

const QueueContext = createContext<QueueStoreValue>()

export const QueueStoreProvider = (props: ParentProps) => {
  const toast = useToast()
  const [state, setState] = createStore<QueueState>({
    queueItems: [],
    applicationRuns: [],
    jobTargetMap: {},
    queueTotal: 0,
    runsTotal: 0,
    isLoading: false,
    error: null,
  })

  const mergeJobTargets = (targets: JobTarget[]): void => {
    if (targets.length === 0) return
    setState('jobTargetMap', (map) => {
      const next = { ...map }
      for (const target of targets) next[target.id] = target
      return next
    })
  }

  const init = async () => {
    setState('isLoading', true)
    try {
      const [queue, runs] = await Promise.all([
        window.applyocalypse.jobs.list(50, 0),
        window.applyocalypse.runs.list(50, 0),
      ])
      setState('queueItems', reconcile(queue.items, { key: 'id' }))
      setState('queueTotal', queue.total)
      setState('applicationRuns', reconcile(runs.items, { key: 'id' }))
      setState('runsTotal', runs.total)
      mergeJobTargets([...queue.jobTargets, ...runs.jobTargets])
      setState('error', null)
    } catch (error) {
      setState('error', error instanceof Error ? error.message : 'Unable to load queue')
    } finally {
      setState('isLoading', false)
    }
  }

  void init()

  const refreshQueue = async (): Promise<void> => {
    const queue = await window.applyocalypse.jobs.list(50, 0)
    setState('queueItems', reconcile(queue.items, { key: 'id' }))
    mergeJobTargets(queue.jobTargets)
    setState('queueTotal', queue.total)
  }

  const refreshRuns = async (): Promise<void> => {
    const runs = await window.applyocalypse.runs.list(50, 0)
    setState('applicationRuns', reconcile(runs.items, { key: 'id' }))
    mergeJobTargets(runs.jobTargets)
    setState('runsTotal', runs.total)
  }

  const waitForRunForQueueItems = async (queueItemIds: string[]): Promise<ApplicationRun | null> => {
    const expected = new Set(queueItemIds)
    for (let attempt = 0; attempt < 16; attempt++) {
      const runs = await window.applyocalypse.runs.list(50, 0)
      setState('applicationRuns', reconcile(runs.items, { key: 'id' }))
      setState('runsTotal', runs.total)
      const run = runs.items.find((r) => expected.has(r.queueItemId))
      if (run) return run
      await sleep(250)
    }
    return null
  }

  const enqueueJobText = async (
    value: string,
    profileId: string,
    options: { autoSubmitEnabled?: boolean; onRunReady?: (runId: string) => Promise<void> } = {}
  ): Promise<boolean> => {
    const items = parseJobIntake(value).map((item) => ({
      ...item,
      autoSubmitEnabled: options.autoSubmitEnabled === true,
    }))

    if (items.length === 0) {
      setState('error', 'Paste at least one job link or description.')
      return false
    }

    setState('isLoading', true)
    try {
      const enqueued = await window.applyocalypse.jobs.enqueue(profileId, items)
      // Store job target metadata for display in queue/history screens
      setState('jobTargetMap', (map) => {
        const next = { ...map }
        for (const jt of enqueued.jobTargets) next[jt.id] = jt
        return next
      })
      await refreshQueue()
      const firstRun = await waitForRunForQueueItems(enqueued.queueItems.map((i) => i.id))
      if (firstRun && options.onRunReady) {
        await options.onRunReady(firstRun.id)
      } else {
        await refreshRuns()
      }
      setState('error', null)
      toast.success(`${enqueued.queueItems.length} ${enqueued.queueItems.length === 1 ? 'job' : 'jobs'} queued`)
      return true
    } catch (error) {
      const msg = error instanceof Error ? error.message : 'Unable to enqueue jobs'
      setState('error', msg)
      toast.error(msg)
      return false
    } finally {
      setState('isLoading', false)
    }
  }

  const cancelPausedRuns = async (): Promise<number> => {
    try {
      const result = (await window.applyocalypse.runs.cancelAllPaused()) as { cancelled: number }
      await refreshRuns()
      await refreshQueue()
      if (result.cancelled > 0) {
        toast.success(`Cleared ${result.cancelled} paused ${result.cancelled === 1 ? 'run' : 'runs'}`)
      } else {
        toast.info('No paused runs to clear')
      }
      return result.cancelled
    } catch (error) {
      const msg = error instanceof Error ? error.message : 'Unable to clear paused runs'
      setState('error', msg)
      toast.error(msg)
      return 0
    }
  }

  const pollTimer = setInterval(() => {
    void refreshQueue()
    void refreshRuns()
  }, 5_000)
  onCleanup(() => clearInterval(pollTimer))

  return (
    <QueueContext.Provider value={{ state, enqueueJobText, refreshQueue, refreshRuns, cancelPausedRuns }}>
      {props.children}
    </QueueContext.Provider>
  )
}

export const useQueueStore = (): QueueStoreValue => {
  const ctx = useContext(QueueContext)
  if (!ctx) throw new Error('QueueStoreProvider is missing')
  return ctx
}
