import { MemoryRouter, Route } from '@solidjs/router'
import { ErrorBoundary, lazy, Suspense } from 'solid-js'
import { Transition } from 'solid-transition-group'
import { AppShell, screenEnter, screenExit } from './App'

const HomeScreen        = lazy(() => import('./screens/HomeScreen'))
const OnboardingScreen  = lazy(() => import('./screens/OnboardingScreen'))
const ProfileScreen     = lazy(() => import('./screens/ProfileScreen'))
const RunConsoleScreen  = lazy(() => import('./screens/RunConsoleScreen'))
const DocumentsScreen   = lazy(() => import('./screens/DocumentsScreen'))
const HistoryScreen     = lazy(() => import('./screens/HistoryScreen'))
const SettingsScreen    = lazy(() => import('./screens/SettingsScreen'))

const ScreenFault = (props: { error: unknown; reset: () => void }) => (
  <div class="screen-fault" role="alert">
    <strong>This screen hit an unexpected error.</strong>
    <span class="screen-fault-detail">
      {props.error instanceof Error ? props.error.message : String(props.error)}
    </span>
    <button class="secondary-action" type="button" onClick={props.reset}>
      Try again
    </button>
  </div>
)

const TransitionedShell = (props: Parameters<typeof AppShell>[0]) => (
  <AppShell {...props}>
    <ErrorBoundary fallback={(error, reset) => <ScreenFault error={error} reset={reset} />}>
      <Transition onEnter={screenEnter} onExit={screenExit} mode="outin">
        <Suspense fallback={<div class="screen-loading" aria-busy="true" />}>{props.children}</Suspense>
      </Transition>
    </ErrorBoundary>
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
