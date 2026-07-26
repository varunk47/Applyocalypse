import { onMount, type JSX } from 'solid-js'
import { gsap } from '../animations/gsap'
import { prefersReducedMotion } from '../animations/motion'

interface EmptyStateProps {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  icon: (props: any) => JSX.Element
  title: string
  description: string
  action?: { label: string; onClick: () => void }
}

export const EmptyState = (props: EmptyStateProps) => {
  let ref: HTMLDivElement | undefined

  onMount(() => {
    if (ref && !prefersReducedMotion()) {
      gsap.from(ref, { scale: 0.95, opacity: 0, duration: 0.4, ease: 'expo.out' })
    }
  })

  return (
    <div ref={ref} class="empty-state">
      <props.icon size={24} aria-hidden="true" />
      <strong>{props.title}</strong>
      <span>{props.description}</span>
      {props.action && (
        <button class="secondary-action" type="button" onClick={props.action.onClick}>
          {props.action.label}
        </button>
      )}
    </div>
  )
}
