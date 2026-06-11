import { For, Show } from 'solid-js'
import { ChevronRight } from 'lucide-solid'

export type ExperienceFormEntry = {
  company: string
  title: string
  location: string
  startDate: string  // MM/DD/YYYY in the form
  endDate: string    // MM/DD/YYYY in the form
  bullets: string[]
}

type Props = {
  entries: ExperienceFormEntry[]
  setEntry: (idx: number, key: keyof ExperienceFormEntry, value: ExperienceFormEntry[keyof ExperienceFormEntry]) => void
  onNext: () => void
}

export function WorkExperienceStep(props: Props) {
  return (
    <div>
      <h2 style={{ 'margin-bottom': '0.5rem' }}>Work experience</h2>
      <p style={{ color: 'var(--text-secondary)', 'margin-bottom': '1.5rem' }}>
        Prefilled from your resume. Edit titles and dates. Bullets are saved as-is.
      </p>

      <For each={props.entries}>
        {(entry, i) => (
          <div class="queue-row static-row" style={{ display: 'block', 'margin-bottom': '1.25rem', padding: '1rem' }}>
            <div style={{ display: 'grid', 'grid-template-columns': '1fr 1fr', gap: '0.75rem' }}>
              <label><span>Company</span>
                <input value={entry.company} onInput={(e) => props.setEntry(i(), 'company', e.currentTarget.value)} />
              </label>
              <label><span>Title</span>
                <input value={entry.title} onInput={(e) => props.setEntry(i(), 'title', e.currentTarget.value)} />
              </label>
            </div>
            <label><span>Location (optional)</span>
              <input value={entry.location} onInput={(e) => props.setEntry(i(), 'location', e.currentTarget.value)} />
            </label>
            <div style={{ display: 'grid', 'grid-template-columns': '1fr 1fr', gap: '0.75rem' }}>
              <label><span>Start (MM/DD/YYYY)</span>
                <input value={entry.startDate} placeholder="01/15/2020" onInput={(e) => props.setEntry(i(), 'startDate', e.currentTarget.value)} />
              </label>
              <label><span>End (MM/DD/YYYY)</span>
                <input value={entry.endDate} placeholder="12/01/2023" onInput={(e) => props.setEntry(i(), 'endDate', e.currentTarget.value)} />
              </label>
            </div>
          </div>
        )}
      </For>

      <Show when={props.entries.length === 0}>
        <p style={{ color: 'var(--text-secondary)' }}>No experience entries found in your resume.</p>
      </Show>

      <button class="primary-action" type="button" style={{ 'margin-top': '1rem' }} onClick={props.onNext}>
        <ChevronRight size={17} aria-hidden="true" />
        <span>Continue</span>
      </button>
    </div>
  )
}
