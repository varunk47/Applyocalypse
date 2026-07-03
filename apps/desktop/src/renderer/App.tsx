import { createEffect, onCleanup, onMount, type ParentProps } from 'solid-js'
import { useNavigate } from '@solidjs/router'
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
  const { state: profileState } = useProfileStore()
  const navigate = useNavigate()

  // First run: once the profile load settles with no profile, route to onboarding.
  createEffect(() => {
    if (!profileState.isLoading && !profileState.profile) {
      navigate('/onboarding', { replace: true })
    }
  })

  onMount(() => {
    // Wire keyboard shortcuts from Electron Main → renderer navigation
    const unsubNav = window.applyocalypse.navigation.subscribe((msg) => {
      if (msg.type === 'navigate' && msg.route) navigate(msg.route)
    })
    onCleanup(unsubNav)
  })

  return (
    <div class="app-shell">
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
