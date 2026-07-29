import { gsap, dur, ease } from './gsap'
import { prefersReducedMotion } from './motion'

const settle = (el: Element, done: () => void, props: Record<string, unknown>) => {
  gsap.set(el, props)
  done()
}

export const enterFromRight = (el: Element, done: () => void) => {
  if (prefersReducedMotion()) return settle(el, done, { x: 0, opacity: 1, scale: 1 })
  gsap.fromTo(el,
    { x: 32, opacity: 0, scale: 0.994 },
    { x: 0, opacity: 1, scale: 1, duration: dur.slow, ease: ease.out, onComplete: done }
  )
}

export const exitToLeft = (el: Element, done: () => void) => {
  if (prefersReducedMotion()) return done()
  gsap.to(el,
    { x: -24, opacity: 0, scale: 0.994, duration: dur.fast, ease: ease.in, onComplete: done }
  )
}

export const enterFromBottom = (el: Element, done: () => void) => {
  if (prefersReducedMotion()) return settle(el, done, { y: 0, opacity: 1 })
  gsap.fromTo(el,
    { y: 24, opacity: 0 },
    { y: 0, opacity: 1, duration: dur.slow, ease: ease.out, onComplete: done }
  )
}

export const exitToBottom = (el: Element, done: () => void) => {
  if (prefersReducedMotion()) return done()
  gsap.to(el,
    { y: 20, opacity: 0, duration: dur.fast, ease: ease.in, onComplete: done }
  )
}

export const enterStepFromRight = (el: Element, done: () => void) => {
  if (prefersReducedMotion()) return settle(el, done, { x: 0, opacity: 1 })
  gsap.fromTo(el,
    { x: 60, opacity: 0 },
    { x: 0, opacity: 1, duration: dur.normal, ease: ease.out, onComplete: done }
  )
}

export const exitStepToLeft = (el: Element, done: () => void) => {
  if (prefersReducedMotion()) return done()
  gsap.to(el,
    { x: -60, opacity: 0, duration: dur.fast, ease: ease.in, onComplete: done }
  )
}
