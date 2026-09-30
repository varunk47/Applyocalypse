import { describe, expect, it } from 'vitest'
import type { ApplicationRun, JobTarget } from '@applyocalypse/shared-types'
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
} from './stats'

// Local-time dates so the tests do not depend on the machine's time zone.
const at = (month: number, day: number, hour = 12) => new Date(2026, month - 1, day, hour)
const NOW = at(9, 30, 18) // Wednesday 30 September 2026

let seq = 0
const run = (status: string, completed: Date | null, extra: Partial<ApplicationRun> = {}): ApplicationRun => {
  seq += 1
  const created = completed ? new Date(completed.getTime() - 90 * 60_000) : at(9, 1)
  return {
    id: `run-${seq}`,
    queueItemId: `q-${seq}`,
    profileId: 'p',
    jobTargetId: `t-${seq}`,
    tailoringRunId: null,
    status,
    currentStepId: null,
    autoSubmitEnabled: false,
    startedAt: created.toISOString(),
    completedAt: completed ? completed.toISOString() : null,
    failureCode: null,
    failureMessage: null,
    createdAt: created.toISOString(),
    updatedAt: (completed ?? created).toISOString(),
    ...extra,
  } as ApplicationRun
}

describe('sentDates', () => {
  it('keeps submitted and completed runs that have a completion time', () => {
    const dates = sentDates([
      run('SUBMITTED', at(9, 29)),
      run('COMPLETED', at(9, 28)),
      run('FAILED', at(9, 27)),
      run('SUBMITTED', null),
    ])
    expect(dates.map((d) => d.getDate())).toEqual([29, 28])
  })
})

describe('bucketCounts', () => {
  const dates = [at(9, 30), at(9, 30), at(9, 29), at(9, 1), at(8, 31), at(8, 15), at(7, 2)]

  it('counts the last N days, ending today, and totals the N days before', () => {
    const { current, previousTotal } = bucketCounts(dates, 'day', NOW, 30)
    expect(current).toHaveLength(30)
    expect(current[29]?.count).toBe(2)
    expect(current[28]?.count).toBe(1)
    expect(current[0]?.start.getDate()).toBe(1)
    expect(current.reduce((sum, bucket) => sum + bucket.count, 0)).toBe(4)
    expect(previousTotal).toBe(2)
  })

  it('starts weeks on Monday', () => {
    const { current } = bucketCounts(dates, 'week', NOW, 12)
    expect(current[11]?.start.getDay()).toBe(1)
    expect(current[11]?.start.getDate()).toBe(28)
    expect(current[11]?.count).toBe(3)
  })

  it('counts calendar months', () => {
    const { current, previousTotal } = bucketCounts(dates, 'month', NOW, 3)
    expect(current.map((b) => b.count)).toEqual([1, 2, 4])
    expect(current[0]?.start.getMonth()).toBe(6)
    expect(previousTotal).toBe(0)
  })
})

describe('dailyGrid and streaks', () => {
  it('lays out whole weeks from a Monday through today', () => {
    const grid = dailyGrid([at(9, 30)], NOW, 2)
    expect(grid[0]?.start.getDay()).toBe(1)
    expect(grid.at(-1)?.start.getDate()).toBe(30)
    expect(grid).toHaveLength(10)
  })

  it('counts active days, the longest run and the run ending today', () => {
    const grid = dailyGrid([at(9, 22), at(9, 23), at(9, 24), at(9, 29), at(9, 30)], NOW, 2)
    expect(streaks(grid)).toEqual({ activeDays: 5, longest: 3, current: 2 })
  })

  it('keeps a streak alive through today until the day is over', () => {
    const grid = dailyGrid([at(9, 28), at(9, 29)], NOW, 1)
    expect(streaks(grid).current).toBe(2)
  })

  it('totals by weekday, Monday first', () => {
    const grid = dailyGrid([at(9, 29), at(9, 30), at(9, 30)], NOW, 1)
    expect(weekdayTotals(grid)).toEqual([0, 1, 2, 0, 0, 0, 0])
  })
})

describe('outcomes, reasons, portals and timing', () => {
  const since = at(9, 1, 0)
  const targets: Record<string, JobTarget> = {
    g1: { portal: 'greenhouse' } as JobTarget,
    g2: { portal: 'greenhouse' } as JobTarget,
    l1: { portal: 'lever' } as JobTarget,
  }
  const runs = [
    run('SUBMITTED', at(9, 29), { jobTargetId: 'g1' }),
    run('SUBMITTED', at(9, 20), { jobTargetId: 'g2' }),
    run('COMPLETED', at(9, 10), { jobTargetId: 'l1' }),
    run('SUBMITTED', at(8, 10), { jobTargetId: 'g1' }),
    run('FAILED', at(9, 12), { failureCode: 'CAPTCHA_UNSOLVED' }),
    run('FAILED', at(9, 14), { failureCode: 'CAPTCHA_UNSOLVED' }),
    run('FAILED', at(9, 15), { failureCode: 'OTP_TIMEOUT' }),
    run('CANCELLED', null, { updatedAt: at(9, 16).toISOString() }),
    run('RUNNING_AUTOMATION', null),
  ]

  it('splits finished runs in the period into sent, failed and withdrawn', () => {
    expect(outcomes(runs, since)).toEqual({ sent: 3, failed: 3, withdrawn: 1 })
  })

  it('ranks why failed runs stopped', () => {
    expect(failureReasons(runs, since).map((r) => [r.code, r.count])).toEqual([
      ['CAPTCHA_UNSOLVED', 2],
      ['OTP_TIMEOUT', 1],
    ])
  })

  it('writes portal names the way the portals do', () => {
    const odd = { i1: { portal: 'icims' } as JobTarget, s1: { portal: 'smart_recruiters' } as JobTarget }
    const sent = [run('SUBMITTED', at(9, 29), { jobTargetId: 'i1' }), run('SUBMITTED', at(9, 28), { jobTargetId: 's1' })]
    expect(byPortal(sent, odd, since).map((entry) => entry.portal).sort()).toEqual(['SmartRecruiters', 'iCIMS'])
  })

  it('counts sent applications by portal', () => {
    expect(byPortal(runs, targets, since)).toEqual([
      { portal: 'Greenhouse', count: 2 },
      { portal: 'Lever', count: 1 },
    ])
  })

  it('takes the median minutes from link to sent', () => {
    expect(medianMinutes(runs, since)).toBe(90)
    expect(medianMinutes([], since)).toBeNull()
  })
})

describe('failureLabel', () => {
  it.each([
    ['WORKER_FAILED_TO_START', 'The worker could not start'],
    ['UNKNOWN', 'No reason recorded'],
    ['PORTAL_TIMED_OUT', 'Portal timed out'],
  ])('%s', (code, label) => {
    expect(failureLabel(code)).toBe(label)
  })
})
