import { createMemo, For, Show } from 'solid-js'
import { useLocation, useNavigate } from '@solidjs/router'
import { useQueueStore } from '../contexts/QueueStore'
import { useSettingsStore } from '../contexts/SettingsStore'

export const NEEDS_SIGNATURE_STATUSES = new Set([
  'READY_FOR_REVIEW',
  'PAUSED',
  'BLOCKED_CAPTCHA',
  'BLOCKED_MFA',
  'BLOCKED_OTP',
  'BLOCKED_AMBIGUOUS_QUESTION',
  'WAITING_FOR_USER_EDIT',
  'READY_TO_SUBMIT',
])

const navItems = [
  { path: '/', label: 'Missions' },
  { path: '/documents', label: 'Documents' },
  { path: '/profile', label: 'Profile' },
  { path: '/history', label: 'History' },
  { path: '/settings', label: 'Settings' },
] as const

export const NavRail = () => {
  const navigate = useNavigate()
  const location = useLocation()
  const { state: queueState } = useQueueStore()
  const { state: settingsState } = useSettingsStore()

  const isActive = (path: string) => {
    if (path === '/') return location.pathname === '/' || location.pathname.startsWith('/run')
    return location.pathname.startsWith(path)
  }

  const missionCount = createMemo(
    () => queueState.applicationRuns.filter((run) => NEEDS_SIGNATURE_STATUSES.has(run.status)).length
  )

  const engineName = createMemo(() => {
    const connected = settingsState.providerConnections.find(
      (connection) => connection.status === 'CONNECTED' && connection.provider !== 'gmail'
    )
    if (!connected) return 'No engine connected'
    return connected.displayName || connected.provider.charAt(0).toUpperCase() + connected.provider.slice(1)
  })

  const concurrencyNote = createMemo(() => {
    const raw = settingsState.settings['automation.maxConcurrentApplications']
    const cap = typeof raw === 'number' && Number.isInteger(raw) ? raw : 2
    return `${cap} at a time, on-device`
  })

  return (
    <aside class="nav-rail" aria-label="Applyocalypse navigation">
      <nav class="nav-list">
        <For each={navItems}>
          {(item) => (
            <button
              class="nav-item"
              classList={{ active: isActive(item.path) }}
              data-gsap="nav-item"
              type="button"
              aria-current={isActive(item.path) ? 'page' : undefined}
              onClick={() => navigate(item.path)}
            >
              <span class="nav-dot" aria-hidden="true" />
              <span>{item.label}</span>
              <Show when={item.path === '/' && missionCount() > 0}>
                <span class="nav-count">{missionCount()}</span>
              </Show>
            </button>
          )}
        </For>
      </nav>
      <div class="engine-card">
        <div class="kicker" style={{ 'letter-spacing': '.08em', 'margin-bottom': '6px' }}>
          ENGINE
        </div>
        <div class="engine-model">{engineName()}</div>
        <div class="engine-sub">{concurrencyNote()}</div>
      </div>
    </aside>
  )
}
