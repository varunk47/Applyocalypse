import { createEffect, createMemo, createSignal, For, on, onCleanup, onMount, Show } from 'solid-js'
import { DEFAULT_MAX_CONCURRENT_APPLICATIONS } from '@applyocalypse/config'
import { useLocation, useNavigate } from '@solidjs/router'
import { ChartNoAxesColumn, FileText, History, House, MessageSquareText, Settings, UserRound } from 'lucide-solid'
import { useProfileStore } from '../contexts/ProfileStore'
import { useQueueStore } from '../contexts/QueueStore'
import { useSettingsStore } from '../contexts/SettingsStore'
import { setChatOpen } from '../features/preferences/chatDrawer'

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
  { path: '/', label: 'Missions', icon: House },
  { path: '/stats', label: 'Stats', icon: ChartNoAxesColumn },
  { path: '/documents', label: 'Documents', icon: FileText },
  { path: '/profile', label: 'Profile', icon: UserRound },
  { path: '/history', label: 'History', icon: History },
  { path: '/settings', label: 'Settings', icon: Settings },
] as const

export const NavRail = () => {
  const navigate = useNavigate()
  const location = useLocation()
  const { state: queueState } = useQueueStore()
  const { state: settingsState } = useSettingsStore()
  const { state: profileState } = useProfileStore()

  const isActive = (path: string) => {
    if (path === '/') return location.pathname === '/' || location.pathname.startsWith('/run')
    return location.pathname.startsWith(path)
  }

  // The highlight slides to the current item instead of jumping.
  let list: HTMLElement | undefined
  const [pill, setPill] = createSignal<{ y: number; height: number } | null>(null)
  const placePill = () => {
    const active = list?.querySelector<HTMLElement>('.nav-item.active')
    setPill(active ? { y: active.offsetTop, height: active.offsetHeight } : null)
  }
  createEffect(on(() => location.pathname, () => requestAnimationFrame(placePill)))
  onMount(() => {
    if (!list) return
    const observer = new ResizeObserver(placePill)
    observer.observe(list)
    onCleanup(() => observer.disconnect())
  })

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
    const cap =
      typeof raw === 'number' && Number.isInteger(raw) ? raw : DEFAULT_MAX_CONCURRENT_APPLICATIONS
    return `${cap} at a time, on-device`
  })

  return (
    <aside class="nav-rail">
      <div class="nav-brand">
        <span class="brand-seal" aria-hidden="true">A</span>
        <span class="brand-word">Applyocalypse</span>
      </div>
      <nav class="nav-list" aria-label="Applyocalypse navigation" ref={list}>
        <Show when={pill()}>
          {(place) => <span class="nav-pill" aria-hidden="true" style={{ height: `${place().height}px`, transform: `translateY(${place().y}px)` }} />}
        </Show>
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
              <item.icon size={17} aria-hidden="true" />
              <span>{item.label}</span>
              <Show when={item.path === '/' && missionCount() > 0}>
                <span class="nav-count" aria-label={`${missionCount()} need you`}>{missionCount()}</span>
              </Show>
            </button>
          )}
        </For>
      </nav>
      <div class="nav-foot">
        <Show when={profileState.profile}>
          <button class="nav-ask" type="button" onClick={() => setChatOpen(true)}>
            <MessageSquareText size={17} aria-hidden="true" />
            <span>
              Ask anything
              <small>Rules, filters, answers</small>
            </span>
          </button>
        </Show>
        <div class="engine-card">
          <div class="engine-model">{engineName()}</div>
          <div class="engine-sub">{concurrencyNote()}</div>
        </div>
      </div>
    </aside>
  )
}
