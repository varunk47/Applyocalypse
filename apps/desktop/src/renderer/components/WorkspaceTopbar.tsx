import { createMemo } from 'solid-js'
import { useLocation } from '@solidjs/router'
import { useSettingsStore } from '../contexts/SettingsStore'
import { useRunStore } from '../contexts/RunStore'
import type { ThemePreference } from '@applyocalypse/shared-types'

const routeLabels: Record<string, string> = {
  '/':          'Overview',
  '/onboarding':'Setup',
  '/intake':    'Intake',
  '/profile':   'Profile',
  '/queue':     'Queue',
  '/run':       'Run Console',
  '/documents': 'Documents',
  '/history':   'History',
  '/settings':  'Settings',
}

export const WorkspaceTopbar = () => {
  const { state: settingsState, setThemePreference } = useSettingsStore()
  const { state: runState } = useRunStore()
  const location = useLocation()

  const screenLabel = createMemo(() => {
    const path = location.pathname
    for (const [prefix, label] of Object.entries(routeLabels)) {
      if (prefix === '/' ? path === '/' : path.startsWith(prefix)) return label
    }
    return 'Applyocalypse'
  })

  const surfaceStatus = createMemo(() => {
    if (runState.runDetail) return runState.runDetail.run.status
    if (runState.isLoading) return 'Syncing'
    return runState.error ? 'Needs attention' : 'Ready'
  })

  return (
    <header class="workspace-topbar" data-gsap="panel">
      <div class="workspace-title">
        <div class="eyebrow">Applyocalypse desktop</div>
        <h1>{screenLabel()}</h1>
      </div>
      <div class="topbar-cluster">
        <div class="run-status">
          <span class="pulse-dot" />
          {surfaceStatus()}
        </div>
        <div class="theme-switch" aria-label="Theme mode">
          {(['dark', 'light', 'system'] as ThemePreference[]).map((pref) => (
            <button
              classList={{ active: settingsState.theme.preference === pref }}
              data-motion
              type="button"
              onClick={() => void setThemePreference(pref)}
            >
              {pref.charAt(0).toUpperCase() + pref.slice(1)}
            </button>
          ))}
        </div>
      </div>
    </header>
  )
}
