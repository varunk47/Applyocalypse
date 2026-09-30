import { createEffect, createSignal, For, on, onCleanup, onMount } from 'solid-js'

type SegmentedProps<T extends string> = {
  label: string
  options: ReadonlyArray<{ value: T; label: string }>
  value: T
  onChange: (value: T) => void
}

/** A pill switch whose white knob slides to the chosen option. */
export const Segmented = <T extends string>(props: SegmentedProps<T>) => {
  let track: HTMLDivElement | undefined
  const [knob, setKnob] = createSignal({ x: 0, width: 0 })

  const measure = () => {
    const active = track?.querySelector<HTMLButtonElement>('[aria-pressed="true"]')
    if (active) setKnob({ x: active.offsetLeft, width: active.offsetWidth })
  }

  createEffect(on(() => props.value, () => requestAnimationFrame(measure)))

  onMount(() => {
    if (!track) return
    const observer = new ResizeObserver(measure)
    observer.observe(track)
    onCleanup(() => observer.disconnect())
  })

  return (
    <div class="seg" role="group" aria-label={props.label} ref={track}>
      <span class="seg-knob" style={{ width: `${knob().width}px`, transform: `translateX(${knob().x}px)` }} />
      <For each={props.options}>
        {(option) => (
          <button type="button" aria-pressed={option.value === props.value} onClick={() => props.onChange(option.value)}>
            {option.label}
          </button>
        )}
      </For>
    </div>
  )
}
