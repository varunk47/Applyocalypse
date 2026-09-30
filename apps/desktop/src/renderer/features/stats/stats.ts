import type { ApplicationRun, JobTarget } from '@applyocalypse/shared-types'

/**
 * Everything on the Stats screen is counted from the runs stored on this
 * computer. All periods use local time: days start at midnight, weeks start on
 * Monday, months on the first.
 */
export type Granularity = 'day' | 'week' | 'month'
export type Bucket = { start: Date; count: number }

const SENT = new Set(['SUBMITTED', 'COMPLETED'])
const DAY_MS = 24 * 60 * 60 * 1000

const isSent = (run: ApplicationRun): boolean => SENT.has(run.status) && run.completedAt !== null

const finishedAt = (run: ApplicationRun): Date => new Date(run.completedAt ?? run.updatedAt)

export const sentDates = (runs: readonly ApplicationRun[]): Date[] =>
  runs.filter(isSent).map((run) => new Date(run.completedAt as string))

const startOfDay = (date: Date): Date => new Date(date.getFullYear(), date.getMonth(), date.getDate())

const startOfWeek = (date: Date): Date => {
  const day = startOfDay(date)
  return new Date(day.getFullYear(), day.getMonth(), day.getDate() - ((day.getDay() + 6) % 7))
}

const startOfPeriod = (date: Date, granularity: Granularity): Date => {
  if (granularity === 'day') return startOfDay(date)
  if (granularity === 'week') return startOfWeek(date)
  return new Date(date.getFullYear(), date.getMonth(), 1)
}

const shift = (start: Date, granularity: Granularity, steps: number): Date => {
  if (granularity === 'month') return new Date(start.getFullYear(), start.getMonth() + steps, 1)
  const days = granularity === 'week' ? steps * 7 : steps
  return new Date(start.getFullYear(), start.getMonth(), start.getDate() + days)
}

/** The last `count` periods ending with the one containing `now`, and the total of the `count` before them. */
export const bucketCounts = (
  dates: readonly Date[],
  granularity: Granularity,
  now: Date,
  count: number
): { current: Bucket[]; previousTotal: number } => {
  const last = startOfPeriod(now, granularity)
  const first = shift(last, granularity, -(count - 1))
  const previousFirst = shift(first, granularity, -count)
  const end = shift(last, granularity, 1)
  const current = Array.from({ length: count }, (_, index) => ({ start: shift(first, granularity, index), count: 0 }))
  let previousTotal = 0
  for (const date of dates) {
    if (date >= first && date < end) {
      const period = startOfPeriod(date, granularity).getTime()
      const bucket = current.find((candidate) => candidate.start.getTime() === period)
      if (bucket) bucket.count += 1
    } else if (date >= previousFirst && date < first) {
      previousTotal += 1
    }
  }
  return { current, previousTotal }
}

/** One bucket per day, from the Monday `weeks - 1` weeks back through today. */
export const dailyGrid = (dates: readonly Date[], now: Date, weeks: number): Bucket[] => {
  const today = startOfDay(now)
  const first = new Date(startOfWeek(today).getTime() - (weeks - 1) * 7 * DAY_MS)
  const days = Math.round((today.getTime() - first.getTime()) / DAY_MS) + 1
  const grid = Array.from({ length: days }, (_, index) => ({
    start: new Date(first.getFullYear(), first.getMonth(), first.getDate() + index),
    count: 0,
  }))
  for (const date of dates) {
    const index = Math.round((startOfDay(date).getTime() - first.getTime()) / DAY_MS)
    const bucket = grid[index]
    if (bucket) bucket.count += 1
  }
  return grid
}

/** A streak counts back from today, or from yesterday while today is still empty. */
export const streaks = (grid: readonly Bucket[]): { activeDays: number; longest: number; current: number } => {
  let longest = 0
  let run = 0
  for (const day of grid) {
    run = day.count > 0 ? run + 1 : 0
    longest = Math.max(longest, run)
  }
  let index = grid.length - 1
  if (grid[index]?.count === 0) index -= 1
  let current = 0
  while (index >= 0 && (grid[index]?.count ?? 0) > 0) {
    current += 1
    index -= 1
  }
  return { activeDays: grid.filter((day) => day.count > 0).length, longest, current }
}

/** Totals per weekday, Monday first. */
export const weekdayTotals = (grid: readonly Bucket[]): number[] => {
  const totals = [0, 0, 0, 0, 0, 0, 0]
  for (const day of grid) {
    const weekday = (day.start.getDay() + 6) % 7
    totals[weekday] = (totals[weekday] ?? 0) + day.count
  }
  return totals
}

export const outcomes = (
  runs: readonly ApplicationRun[],
  since: Date
): { sent: number; failed: number; withdrawn: number } => {
  const counts = { sent: 0, failed: 0, withdrawn: 0 }
  for (const run of runs) {
    if (finishedAt(run) < since) continue
    if (isSent(run)) counts.sent += 1
    else if (run.status === 'FAILED') counts.failed += 1
    else if (run.status === 'CANCELLED') counts.withdrawn += 1
  }
  return counts
}

export const failureReasons = (
  runs: readonly ApplicationRun[],
  since: Date,
  limit = 3
): Array<{ code: string; count: number }> => {
  const counts = new Map<string, number>()
  for (const run of runs) {
    if (run.status !== 'FAILED' || finishedAt(run) < since) continue
    const code = run.failureCode ?? 'UNKNOWN'
    counts.set(code, (counts.get(code) ?? 0) + 1)
  }
  return [...counts.entries()]
    .map(([code, count]) => ({ code, count }))
    .sort((a, b) => b.count - a.count || a.code.localeCompare(b.code))
    .slice(0, limit)
}

const FAILURE_LABELS: Record<string, string> = {
  WORKER_FAILED: 'The worker stopped unexpectedly',
  WORKER_FAILED_TO_START: 'The worker could not start',
  SCHEDULER_PREPARE_FAILED: 'The run could not be prepared',
  LOCAL_CREDENTIAL_UNAVAILABLE: 'A saved login was not available',
  FILTERED_OUT: 'Skipped by your job filters',
  RESUME_OVERFLOWS_ONE_PAGE: 'The resume ran past one page',
  INSUFFICIENT_VERIFIED_EVIDENCE: 'Not enough verified experience to tailor',
  JEV_UNRESOLVED: 'The page could not be worked out',
  TEX_COMPILE_FAILED: 'The resume file could not be built',
  MISSING_TEX_ANCHORS: 'The resume file could not be edited',
  MISSING_DOCX_ANCHORS: 'The resume file could not be edited',
  UNKNOWN: 'No reason recorded',
}

/** Plain words for a failure code; unknown codes read as a sentence. */
export const failureLabel = (code: string): string => {
  const known = FAILURE_LABELS[code]
  if (known) return known
  const words = code.replace(/_+/g, ' ').trim().toLowerCase()
  return words ? words.charAt(0).toUpperCase() + words.slice(1) : 'No reason recorded'
}

const PORTAL_NAMES: Record<string, string> = {
  icims: 'iCIMS',
  smartrecruiters: 'SmartRecruiters',
  bamboohr: 'BambooHR',
  successfactors: 'SuccessFactors',
}

const portalName = (portal: string | null | undefined): string => {
  if (!portal) return 'Other'
  const known = PORTAL_NAMES[portal.toLowerCase().replace(/[\s_-]+/g, '')]
  if (known) return known
  const words = portal.replace(/[_-]+/g, ' ').trim()
  return words.charAt(0).toUpperCase() + words.slice(1).toLowerCase()
}

/** Sent applications per portal, largest first, with the tail folded into Other. */
export const byPortal = (
  runs: readonly ApplicationRun[],
  targets: Readonly<Record<string, JobTarget | undefined>>,
  since: Date,
  limit = 5
): Array<{ portal: string; count: number }> => {
  const counts = new Map<string, number>()
  for (const run of runs) {
    if (!isSent(run) || finishedAt(run) < since) continue
    const name = portalName(targets[run.jobTargetId]?.portal)
    counts.set(name, (counts.get(name) ?? 0) + 1)
  }
  const ranked = [...counts.entries()]
    .map(([portal, count]) => ({ portal, count }))
    .sort((a, b) => (a.portal === 'Other' ? 1 : b.portal === 'Other' ? -1 : b.count - a.count || a.portal.localeCompare(b.portal)))
  if (ranked.length <= limit) return ranked
  const kept = ranked.filter((entry) => entry.portal !== 'Other').slice(0, limit - 1)
  const rest = ranked.filter((entry) => !kept.includes(entry)).reduce((sum, entry) => sum + entry.count, 0)
  return [...kept, { portal: 'Other', count: rest }]
}

/** Median minutes from adding a job to sending it, or null when nothing was sent. */
export const medianMinutes = (runs: readonly ApplicationRun[], since: Date): number | null => {
  const minutes = runs
    .filter((run) => isSent(run) && finishedAt(run) >= since)
    .map((run) => (Date.parse(run.completedAt as string) - Date.parse(run.createdAt)) / 60_000)
    .filter((value) => Number.isFinite(value) && value >= 0)
    .sort((a, b) => a - b)
  if (minutes.length === 0) return null
  const middle = Math.floor(minutes.length / 2)
  const median = minutes.length % 2 ? minutes[middle] : ((minutes[middle - 1] ?? 0) + (minutes[middle] ?? 0)) / 2
  return Math.round(median ?? 0)
}
