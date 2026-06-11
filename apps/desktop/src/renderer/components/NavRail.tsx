import { For } from 'solid-js'
import { useNavigate, useLocation } from '@solidjs/router'
import {
  ChevronRight, FileText, History, Inbox, LayoutDashboard,
  ListTodo, MessageSquare, Settings, Terminal, User
} from 'lucide-solid'

const navItems = [
  { path: '/',          label: 'Chat',         helper: 'Job intake',    Icon: MessageSquare },
  { path: '/overview',  label: 'Overview',     helper: 'Control plane', Icon: LayoutDashboard },
  { path: '/intake',    label: 'Intake',       helper: 'Add jobs',      Icon: Inbox },
  { path: '/profile',   label: 'Profile',      helper: 'Identity',      Icon: User },
  { path: '/queue',     label: 'Queue',        helper: 'Worklist',      Icon: ListTodo },
  { path: '/run',       label: 'Run Console',  helper: 'Live run',      Icon: Terminal },
  { path: '/documents', label: 'Documents',    helper: 'Sources',       Icon: FileText },
  { path: '/history',   label: 'History',      helper: 'Audit trail',   Icon: History },
  { path: '/settings',  label: 'Settings',     helper: 'Providers',     Icon: Settings },
] as const

export const NavRail = () => {
  const navigate = useNavigate()
  const location = useLocation()

  const isActive = (path: string) => {
    if (path === '/') return location.pathname === '/'
    return location.pathname.startsWith(path)
  }

  return (
    <aside class="nav-rail" aria-label="Applyocalypse navigation">
      <button
        class="brand-mark"
        data-gsap="nav-item"
        data-motion
        type="button"
        onClick={() => navigate('/')}
        aria-label="Open overview"
      >
        <span class="brand-core">A</span>
        <span class="brand-name">Applyocalypse</span>
      </button>
      <nav class="nav-list">
        <For each={navItems}>
          {(item) => (
            <button
              class="nav-item"
              classList={{ active: isActive(item.path) }}
              data-gsap="nav-item"
              data-motion
              type="button"
              aria-current={isActive(item.path) ? 'page' : undefined}
              onClick={() => navigate(item.path)}
            >
              <item.Icon size={15} class="nav-icon" aria-hidden="true" />
              <span class="nav-text" style={{ flex: '1' }}>
                <strong>{item.label}</strong>
                <small>{item.helper}</small>
              </span>
              <ChevronRight size={12} aria-hidden="true" style={{ opacity: isActive(item.path) ? '0.7' : '0.3' }} />
            </button>
          )}
        </For>
      </nav>
      <div class="nav-footer">
        <span class="nav-version">v0.1</span>
      </div>
    </aside>
  )
}
