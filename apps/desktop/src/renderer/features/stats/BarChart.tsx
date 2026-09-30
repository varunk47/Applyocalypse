import { createMemo, createSignal, For, onCleanup, onMount, Show } from 'solid-js'

export type BarDatum = { label: string; full: string; count: number }

type BarChartProps = { data: BarDatum[]; labelEvery: number; title: string; unit: string }

const HEIGHT = 230
const MARGIN = { top: 24, right: 6, bottom: 26, left: 34 }

const niceStep = (max: number): number => {
  for (const step of [1, 2, 5, 10, 20, 25, 50, 100, 200, 250, 500, 1000]) if (max / step <= 4) return step
  return 2000
}

/** A column with a 4px rounded top and a square foot on the baseline. */
const columnPath = (x: number, y: number, width: number, height: number): string => {
  const r = Math.min(4, height, width / 2)
  return `M${x},${y + height}V${y + r}Q${x},${y} ${x + r},${y}H${x + width - r}Q${x + width},${y} ${x + width},${y + r}V${y + height}Z`
}

/** One series of columns: hover or focus a period for its count, the peak is labelled. */
export const BarChart = (props: BarChartProps) => {
  let box: HTMLDivElement | undefined
  const [width, setWidth] = createSignal(600)
  const [active, setActive] = createSignal<number | null>(null)

  onMount(() => {
    if (!box) return
    const observer = new ResizeObserver(([entry]) => entry && setWidth(entry.contentRect.width))
    observer.observe(box)
    onCleanup(() => observer.disconnect())
  })

  const geometry = createMemo(() => {
    const max = Math.max(1, ...props.data.map((d) => d.count))
    const step = niceStep(max)
    const top = Math.ceil(max / step) * step
    const plotWidth = width() - MARGIN.left - MARGIN.right
    const plotHeight = HEIGHT - MARGIN.top - MARGIN.bottom
    const band = plotWidth / Math.max(1, props.data.length)
    const barWidth = Math.min(24, band * 0.62)
    const y = (value: number) => MARGIN.top + plotHeight - (value / top) * plotHeight
    const ticks = Array.from({ length: top / step + 1 }, (_, i) => i * step)
    let peak = 0
    for (let i = 1; i < props.data.length; i++) {
      if ((props.data[i]?.count ?? 0) > (props.data[peak]?.count ?? 0)) peak = i
    }
    return { band, barWidth, y, ticks, plotHeight, peak }
  })

  const x = (index: number) => MARGIN.left + index * geometry().band + (geometry().band - geometry().barWidth) / 2

  return (
    <div class="bar-chart" ref={box}>
      <svg viewBox={`0 0 ${width()} ${HEIGHT}`} height={HEIGHT} role="img" aria-label={props.title}>
        <For each={geometry().ticks}>
          {(tick) => (
            <>
              <line class={tick === 0 ? 'chart-base' : 'chart-grid'} x1={MARGIN.left} x2={width() - MARGIN.right} y1={geometry().y(tick)} y2={geometry().y(tick)} />
              <text class="chart-tick" x={MARGIN.left - 8} y={geometry().y(tick) + 4} text-anchor="end">
                {tick}
              </text>
            </>
          )}
        </For>
        <For each={props.data}>
          {(datum, index) => {
            const height = () => Math.max(0, geometry().y(0) - geometry().y(datum.count))
            return (
              <g>
                <rect
                  class="chart-hit"
                  x={MARGIN.left + index() * geometry().band}
                  y={MARGIN.top}
                  width={geometry().band}
                  height={geometry().plotHeight}
                  tabindex="0"
                  aria-label={`${datum.full}: ${datum.count} ${props.unit}`}
                  onPointerEnter={() => setActive(index())}
                  onPointerLeave={() => setActive(null)}
                  onFocus={() => setActive(index())}
                  onBlur={() => setActive(null)}
                />
                <path
                  class="chart-bar"
                  classList={{ on: active() === index() }}
                  style={{ 'animation-delay': `${index() * Math.min(40, 520 / props.data.length)}ms` }}
                  d={columnPath(x(index()), geometry().y(datum.count), geometry().barWidth, height())}
                />
                <Show when={index() % props.labelEvery === 0 || index() === props.data.length - 1}>
                  <text class="chart-tick" x={x(index()) + geometry().barWidth / 2} y={HEIGHT - 6} text-anchor="middle">
                    {datum.label}
                  </text>
                </Show>
                <Show when={index() === geometry().peak && datum.count > 0}>
                  <text class="chart-peak" x={x(index()) + geometry().barWidth / 2} y={geometry().y(datum.count) - 7} text-anchor="middle">
                    {datum.count}
                  </text>
                </Show>
              </g>
            )
          }}
        </For>
      </svg>
      <Show when={active() !== null ? props.data[active() as number] : undefined}>
        {(datum) => (
          <div
            class="chart-tip"
            role="status"
            style={{
              left: `${x(active() as number) + geometry().barWidth / 2}px`,
              top: `${geometry().y(datum().count) - 6}px`,
            }}
          >
            <strong>
              {datum().count} {props.unit}
            </strong>
            <span>{datum().full}</span>
          </div>
        )}
      </Show>
    </div>
  )
}
