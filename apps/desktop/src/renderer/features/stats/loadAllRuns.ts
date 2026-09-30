import type { ApplicationRun, JobTarget } from '@applyocalypse/shared-types'

const PAGE_SIZE = 250
const MAX_RUNS = 10_000

/** Every stored run, page by page, with the job targets they point at. */
export const loadAllRuns = async (): Promise<{ runs: ApplicationRun[]; targets: Record<string, JobTarget> }> => {
  const runs: ApplicationRun[] = []
  const targets: Record<string, JobTarget> = {}
  while (runs.length < MAX_RUNS) {
    const page = await window.applyocalypse.runs.list(PAGE_SIZE, runs.length)
    runs.push(...page.items)
    for (const target of page.jobTargets) targets[target.id] = target
    if (page.items.length < PAGE_SIZE || runs.length >= page.total) break
  }
  return { runs, targets }
}
