import { gsap, dur, ease } from './gsap'
import { prefersReducedMotion } from './motion'

export const staggerEnterList = (container: Element, itemSelector = '[data-list-item]') => {
  if (prefersReducedMotion()) return
  const items = container.querySelectorAll(itemSelector)
  gsap.from(items, {
    y: 12,
    opacity: 0,
    duration: dur.normal,
    stagger: 0.04,
    ease: ease.out,
    clearProps: 'transform,opacity',
  })
}

export const enterSingleItem = (el: Element) => {
  if (prefersReducedMotion()) return
  gsap.from(el, {
    height: 0,
    opacity: 0,
    marginBottom: 0,
    duration: dur.normal,
    ease: ease.out,
    clearProps: 'height,marginBottom',
  })
}

export const exitSingleItem = (el: Element, done: () => void) => {
  if (prefersReducedMotion()) {
    done()
    return
  }
  gsap.to(el, {
    height: 0,
    opacity: 0,
    marginBottom: 0,
    duration: dur.fast,
    ease: ease.in,
    onComplete: done,
  })
}
