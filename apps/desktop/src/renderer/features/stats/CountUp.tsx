import { createEffect, createSignal, on, onCleanup } from 'solid-js'
import { prefersReducedMotion } from '../../animations/motion'

type CountUpProps = { value: number; suffix?: string; duration?: number }

/** A number that eases to its new value instead of jumping. */
export const CountUp = (props: CountUpProps) => {
  const [shown, setShown] = createSignal(0)
  let frame = 0

  createEffect(
    on(
      () => props.value,
      (to) => {
        cancelAnimationFrame(frame)
        if (prefersReducedMotion()) {
          setShown(to)
          return
        }
        const from = shown()
        const start = performance.now()
        const duration = props.duration ?? 900
        const tick = (now: number) => {
          const progress = Math.min(1, (now - start) / duration)
          const eased = progress === 1 ? 1 : 1 - Math.pow(2, -10 * progress)
          setShown(from + (to - from) * eased)
          if (progress < 1) frame = requestAnimationFrame(tick)
        }
        frame = requestAnimationFrame(tick)
      }
    )
  )
  onCleanup(() => cancelAnimationFrame(frame))

  return (
    <>
      {Math.round(shown()).toLocaleString()}
      {props.suffix ?? ''}
    </>
  )
}
