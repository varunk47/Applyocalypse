/** GSAP drives inline styles via rAF, so the CSS reduced-motion media query
 * cannot intercept it; every GSAP call site must consult this instead. */
export const prefersReducedMotion = (): boolean =>
  window.matchMedia('(prefers-reduced-motion: reduce)').matches
