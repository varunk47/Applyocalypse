const noop = () => ({})
const chainable = () => ({ then: noop, kill: noop })

export const gsap = {
  from: chainable,
  to: chainable,
  fromTo: chainable,
  set: noop,
  registerPlugin: noop,
  context: () => ({ revert: noop }),
  killTweensOf: noop,
  ticker: { add: noop, remove: noop },
}

export const ScrollToPlugin = {}
export const TextPlugin = {}

export const ease = {
  out: 'expo.out',
  in: 'expo.in',
  inOut: 'power3.inOut',
  spring: 'elastic.out(0.4, 0.4)',
  snap: 'power4.out',
}

export const dur = {
  instant: 0.08,
  fast: 0.18,
  normal: 0.35,
  slow: 0.55,
  cinematic: 0.85,
}
