import { gsap } from 'gsap'
import { ScrollToPlugin } from 'gsap/ScrollToPlugin'
import { TextPlugin } from 'gsap/TextPlugin'

gsap.registerPlugin(ScrollToPlugin, TextPlugin)

export { gsap }

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
