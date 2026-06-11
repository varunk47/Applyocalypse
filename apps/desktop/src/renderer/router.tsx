import { MemoryRouter, Route } from '@solidjs/router'
import { lazy, Suspense } from 'solid-js'
import { Transition } from 'solid-transition-group'
import { AppShell, screenEnter, screenExit } from './App'

const ChatScreen        = lazy(() => import('./screens/ChatScreen'))
const OverviewScreen    = lazy(() => import('./screens/OverviewScreen'))
const OnboardingScreen  = lazy(() => import('./screens/OnboardingScreen'))
const IntakeScreen      = lazy(() => import('./screens/IntakeScreen'))
const ProfileScreen     = lazy(() => import('./screens/ProfileScreen'))
const QueueScreen       = lazy(() => import('./screens/QueueScreen'))
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
    <Route path="/"           component={ChatScreen} />
    <Route path="/overview"   component={OverviewScreen} />
    <Route path="/onboarding" component={OnboardingScreen} />
    <Route path="/intake"     component={IntakeScreen} />
    <Route path="/profile"    component={ProfileScreen} />
    <Route path="/queue"      component={QueueScreen} />
    <Route path="/run/:runId?" component={RunConsoleScreen} />
    <Route path="/documents"  component={DocumentsScreen} />
    <Route path="/history"    component={HistoryScreen} />
    <Route path="/settings"   component={SettingsScreen} />
  </MemoryRouter>
)
