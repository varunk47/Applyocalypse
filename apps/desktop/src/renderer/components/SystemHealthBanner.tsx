import { Show, createSignal, onMount } from 'solid-js'
import { AlertTriangle } from 'lucide-solid'

/**
 * App-wide warning for missing external tooling.
 *
 * The DOCX to PDF step shells out to LibreOffice, and falls back to docx2pdf
 * (which needs Microsoft Word). With neither installed, tailoring still runs and
 * still writes a DOCX, so the failure only shows up as a missing PDF at the end
 * of a run. Settings has the full diagnostic, but nobody opens Settings before
 * their first application, so the warning has to find them.
 */
export const SystemHealthBanner = () => {
  const [installUrl, setInstallUrl] = createSignal<string | null>(null)

  onMount(async () => {
    try {
      const { converters } = await window.applyocalypse.system.checkConverters()
      if (converters.libreoffice.available || converters.word.available) return
      setInstallUrl(converters.libreoffice.installUrl)
    } catch {
      // Best effort only. Settings holds the authoritative diagnostic, and a
      // failed probe must not take the shell down with it.
    }
  })

  // The slot is always rendered so .app-shell keeps a stable three-row grid.
  return (
    <div class="system-health-slot">
      <Show when={installUrl()}>
        {(url) => (
          <div class="system-health-banner" role="alert">
            <AlertTriangle size={15} aria-hidden="true" />
            <span>
              No PDF converter found. Tailored resumes will be written as DOCX only until you
              install LibreOffice or Microsoft Word.
            </span>
            <a href={url()} target="_blank" rel="noopener noreferrer">
              Install LibreOffice
            </a>
          </div>
        )}
      </Show>
    </div>
  )
}
