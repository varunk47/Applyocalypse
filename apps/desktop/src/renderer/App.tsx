import { onCleanup, onMount, type ParentProps } from 'solid-js'
import { useNavigate } from '@solidjs/router'
import { gsap } from './animations/gsap'
import { enterFromRight, exitToLeft } from './animations/screenTransition'
import { AppProviders } from './contexts/AppProviders'
import { useProfileStore } from './contexts/ProfileStore'
import { AppRouter } from './router'
import { NavRail } from './components/NavRail'
import { Titlebar } from './components/Titlebar'

// GSAP-powered screen transition used by the router outlet
export const screenEnter = (el: Element, done: () => void) => enterFromRight(el, done)
export const screenExit = (el: Element, done: () => void) => exitToLeft(el, done)

export const AppShell = (props: ParentProps) => {
  let rootRef: HTMLDivElement | undefined
  const { state: profileState } = useProfileStore()
  const navigate = useNavigate()

  onMount(() => {
    if (!profileState.isLoading && !profileState.profile) {
      navigate('/onboarding', { replace: true })
    }

    // Wire keyboard shortcuts from Electron Main → renderer navigation
    const unsubNav = window.applyocalypse.navigation.subscribe((msg) => {
      if (msg.type === 'navigate' && msg.route) navigate(msg.route)
    })
    onCleanup(unsubNav)

    const context = gsap.context(() => {
      gsap.from("[data-gsap='nav-item']", {
        opacity: 0, x: -12, duration: 0.7, stagger: 0.048, ease: 'expo.out', delay: 0.05
      })
      gsap.from("[data-gsap='panel']", {
        opacity: 0, y: 22, scale: 0.996, duration: 0.85, stagger: 0.07, ease: 'expo.out', delay: 0.1
      })
    }, rootRef)

    onCleanup(() => context.revert())
  })

  return (
    <div ref={rootRef} class="app-shell">
      <Titlebar />
      <div class="workspace">
        <NavRail />
        <main>{props.children}</main>
      </div>
    </div>
  )
}

export const App = () => (
  <AppProviders>
    <AppRouter />
  </AppProviders>
)
