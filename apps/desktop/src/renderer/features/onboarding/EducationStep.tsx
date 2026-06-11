import { For, Show } from 'solid-js'
import { ChevronRight } from 'lucide-solid'

export type EducationFormEntry = {
  institution: string
  degree: string
  field: string
  gpa: string
  startDate: string  // MM/DD/YYYY in the form
  endDate: string    // MM/DD/YYYY in the form
}

type Props = {
  entries: EducationFormEntry[]
  setEntry: (idx: number, key: keyof EducationFormEntry, value: string) => void
  onNext: () => void
}

export function EducationStep(props: Props) {
  return (
    <div>
      <h2 style={{ 'margin-bottom': '0.5rem' }}>Education</h2>
      <p style={{ color: 'var(--text-secondary)', 'margin-bottom': '1.5rem' }}>
        Prefilled from your resume. Edit as needed. Dates are MM/DD/YYYY.
      </p>

      <For each={props.entries}>
        {(entry, i) => (
          <div class="queue-row static-row" style={{ display: 'block', 'margin-bottom': '1.25rem', padding: '1rem' }}>
            <label><span>Institution</span>
              <input value={entry.institution} onInput={(e) => props.setEntry(i(), 'institution', e.currentTarget.value)} />
            </label>
            <div style={{ display: 'grid', 'grid-template-columns': '1fr 1fr', gap: '0.75rem' }}>
              <label><span>Degree</span>
                <input value={entry.degree} onInput={(e) => props.setEntry(i(), 'degree', e.currentTarget.value)} />
              </label>
              <label><span>Field of study</span>
                <input value={entry.field} onInput={(e) => props.setEntry(i(), 'field', e.currentTarget.value)} />
              </label>
            </div>
            <label><span>GPA (optional)</span>
              <input value={entry.gpa} placeholder="e.g. 3.8/4.0" onInput={(e) => props.setEntry(i(), 'gpa', e.currentTarget.value)} />
            </label>
            <div style={{ display: 'grid', 'grid-template-columns': '1fr 1fr', gap: '0.75rem' }}>
              <label><span>Start (MM/DD/YYYY)</span>
                <input value={entry.startDate} placeholder="08/01/2018" onInput={(e) => props.setEntry(i(), 'startDate', e.currentTarget.value)} />
              </label>
              <label><span>End (MM/DD/YYYY)</span>
                <input value={entry.endDate} placeholder="05/15/2022" onInput={(e) => props.setEntry(i(), 'endDate', e.currentTarget.value)} />
              </label>
            </div>
          </div>
        )}
      </For>

      <Show when={props.entries.length === 0}>
        <p style={{ color: 'var(--text-secondary)' }}>No education entries found in your resume.</p>
      </Show>

      <button class="primary-action" type="button" style={{ 'margin-top': '1rem' }} onClick={props.onNext}>
        <ChevronRight size={17} aria-hidden="true" />
        <span>Continue</span>
      </button>
    </div>
  )
}
