import { MemoryRouter, Route } from '@solidjs/router'
import { lazy, Suspense } from 'solid-js'
import { Transition } from 'solid-transition-group'
import { AppShell, screenEnter, screenExit } from './App'

const HomeScreen        = lazy(() => import('./screens/HomeScreen'))
const OnboardingScreen  = lazy(() => import('./screens/OnboardingScreen'))
const ProfileScreen     = lazy(() => import('./screens/ProfileScreen'))
const RunConsoleScreen  = lazy(() => import('./screens/RunConsoleScreen'))
const DocumentsScreen   = lazy(() => import('./screens/DocumentsScreen'))
const HistoryScreen     = lazy(() => import('./screens/HistoryScreen'))
const SettingsScreen    = lazy(() => import('./screens/SettingsScreen'))

const TransitionedShell = (props: Parameters<typeof AppShell>[0]) => (
  <AppShell {...props}>
    <Transition onEnter={screenEnter} onExit={screenExit} mode="outin">
      <Suspense>{props.children}</Suspense>
    </Transition>
  </AppShell>
)

export const AppRouter = () => (
  <MemoryRouter root={TransitionedShell}>
    <Route path="/"            component={HomeScreen} />
    <Route path="/onboarding"  component={OnboardingScreen} />
    <Route path="/run/:runId?" component={RunConsoleScreen} />
    <Route path="/documents"   component={DocumentsScreen} />
    <Route path="/profile"     component={ProfileScreen} />
    <Route path="/history"     component={HistoryScreen} />
    <Route path="/settings"    component={SettingsScreen} />
  </MemoryRouter>
)
