import { createEffect, onCleanup, onMount, Show, type ParentProps } from 'solid-js'
import { useNavigate } from '@solidjs/router'
import { dropCardBack, pullCardForward } from './animations/screenTransition'
import { AppProviders } from './contexts/AppProviders'
import { useProfileStore } from './contexts/ProfileStore'
import { AppRouter } from './router'
import { AuthScreen } from './features/account/AuthScreen'
import { account, loadAccount } from './features/account/accountState'
import { NavRail } from './components/NavRail'
import { PreferenceChat } from './features/preferences/PreferenceChat'
import { SystemHealthBanner } from './components/SystemHealthBanner'
import { Titlebar } from './components/Titlebar'

// GSAP-powered screen transition used by the router outlet
export const screenEnter = (el: Element, done: () => void) => pullCardForward(el, done)
export const screenExit = (el: Element, done: () => void) => dropCardBack(el, done)

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
    void loadAccount()
    // Wire keyboard shortcuts from Electron Main → renderer navigation
    const unsubNav = window.applyocalypse.navigation.subscribe((msg) => {
      if (msg.type === 'navigate' && msg.route) navigate(msg.route)
    })
    onCleanup(unsubNav)
  })

  return (
    <div class="app-shell">
      <Titlebar />
      <Show when={account()}>
        {(current) => (
          <Show when={current().signedIn} fallback={<AuthScreen />}>
            <SystemHealthBanner />
            <div class="shell-body">
              <Show when={profileState.profile}>
                <PreferenceChat />
              </Show>
              <div class="workspace">
                <NavRail />
                <main>{props.children}</main>
              </div>
            </div>
          </Show>
        )}
      </Show>
    </div>
  )
}

export const App = () => (
  <AppProviders>
    <AppRouter />
  </AppProviders>
)
