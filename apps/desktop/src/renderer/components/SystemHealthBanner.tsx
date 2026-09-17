import { Show, createSignal, onMount } from 'solid-js'
import { useNavigate } from '@solidjs/router'
import { AlertTriangle } from 'lucide-solid'

type Finding = {
  id: string
  severity: 'BLOCKING' | 'DEGRADED'
  title: string
  consequence: string
  fix: string
  route: string | null
  link: string | null
}

/**
 * App-wide warning for anything the machine is missing.
 *
 * Every external dependency but the database used to be discovered inside a run
 * the user had already committed to: no model key produced documents built from
 * templates, no converter produced a DOCX where a PDF was expected. Settings
 * holds the detail, but nobody opens Settings before their first application,
 * so the warning has to find them.
 *
 * One at a time, worst first. This sits in a fixed grid row, and a stack of
 * banners would push the app out of it.
 */
export const SystemHealthBanner = () => {
  const navigate = useNavigate()
  const [finding, setFinding] = createSignal<Finding | null>(null)

  onMount(async () => {
    try {
      const { findings } = await window.applyocalypse.system.checkHealth()
      setFinding(findings[0] ?? null)
    } catch {
      // Best effort only. A failed probe must not take the shell down with it.
    }
  })

  return (
    // The slot is always rendered so .app-shell keeps a stable three-row grid.
    <div class="system-health-slot">
      <Show when={finding()}>
        {(current) => (
          <div
            class="system-health-banner"
            classList={{ 'is-blocking': current().severity === 'BLOCKING' }}
            role="alert"
          >
            <AlertTriangle size={15} aria-hidden="true" />
            <span>
              <strong>{current().title}.</strong> {current().consequence} {current().fix}
            </span>
            <Show when={current().route}>
              {(route) => (
                <button type="button" onClick={() => navigate(route())}>
                  Fix this
                </button>
              )}
            </Show>
            <Show when={current().link}>
              {(url) => (
                <a href={url()} target="_blank" rel="noopener noreferrer">
                  Download
                </a>
              )}
            </Show>
          </div>
        )}
      </Show>
    </div>
  )
}
