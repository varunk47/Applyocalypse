import { createMemo, For, Index } from 'solid-js'
import type { Bucket } from './stats'

type CalendarHeatProps = { days: Bucket[] }

/** Six steps of one hue, darker for more; an empty day sits just off the card. */
const step = (count: number): number => {
  if (count === 0) return 0
  if (count <= 1) return 1
  if (count <= 2) return 2
  if (count <= 4) return 3
  if (count <= 6) return 4
  if (count <= 8) return 5
  return 6
}

const dayLabel = (day: Bucket): string =>
  `${day.start.toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric' })}: ${day.count} sent`

/** A week per column, Monday on top, the way a wall calendar reads. */
export const CalendarHeat = (props: CalendarHeatProps) => {
  const columns = createMemo(() => {
    const weeks: Bucket[][] = []
    props.days.forEach((day, index) => {
      if (index % 7 === 0) weeks.push([])
      weeks[weeks.length - 1]?.push(day)
    })
    return weeks
  })

  const monthLabels = createMemo(() => {
    let last = -1
    return columns().map((week) => {
      const first = week.find((day) => day.start.getDate() <= 7)
      if (!first || first.start.getMonth() === last) return ''
      last = first.start.getMonth()
      return first.start.toLocaleDateString('en-US', { month: 'short' })
    })
  })

  return (
    <div class="heat">
      <div class="heat-months" aria-hidden="true">
        <Index each={monthLabels()}>{(label) => <span>{label()}</span>}</Index>
      </div>
      <div class="heat-grid" role="img" aria-label="Applications sent each day, one column per week">
        <For each={columns()}>
          {(week, column) => (
            <div class="heat-week">
              <For each={week}>
                {(day, row) => (
                  <i
                    class={`heat-cell h${step(day.count)}`}
                    style={{ 'animation-delay': `${(column() + row()) * 9 + 120}ms` }}
                    tabindex="0"
                    title={dayLabel(day)}
                    aria-label={dayLabel(day)}
                  />
                )}
              </For>
            </div>
          )}
        </For>
      </div>
      <div class="heat-scale" aria-hidden="true">
        Fewer
        <For each={[0, 1, 2, 3, 4, 5, 6]}>{(level) => <i class={`heat-cell h${level}`} />}</For>
        More
      </div>
    </div>
  )
}
