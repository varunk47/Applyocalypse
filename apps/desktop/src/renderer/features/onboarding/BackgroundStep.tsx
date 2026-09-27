import { For, Show } from 'solid-js'
import { ArrowRight, Plus, X } from 'lucide-solid'
import { Choice, EqualEmploymentStep, type EeoFields } from './EqualEmploymentStep'

// Mirrors MAX_PROFILE_REFERENCES in shared-schemas; imported by value it would
// pull zod into the renderer bundle.
export const MAX_PROFILE_REFERENCES = 3

export type ReferenceRow = {
  name: string
  relationship: string
  company: string
  title: string
  email: string
  phone: string
}

export type LegalFields = {
  criminalRecordDefault: 'Yes' | 'No'
  previouslyEmployedDefault: 'Yes' | 'No'
}

type Props = {
  eeo: EeoFields
  setEeoField: <K extends keyof EeoFields>(key: K, value: EeoFields[K]) => void
  legal: LegalFields
  setLegalField: (key: keyof LegalFields, value: 'Yes' | 'No') => void
  references: ReferenceRow[]
  setReference: (index: number, key: keyof ReferenceRow, value: string) => void
  addReference: () => void
  removeReference: (index: number) => void
  onContinue: () => void
}

const REFERENCE_FIELDS: { key: keyof ReferenceRow; label: string; type?: string }[] = [
  { key: 'name', label: 'Full name' },
  { key: 'relationship', label: 'Relationship' },
  { key: 'company', label: 'Company' },
  { key: 'title', label: 'Their title' },
  { key: 'email', label: 'Email', type: 'email' },
  { key: 'phone', label: 'Phone', type: 'tel' },
]

/**
 * Everything a portal asks about the person rather than the resume: demographics,
 * the two legal history questions, and references. All of it is optional except
 * the legal answers, which default to "No" and can be changed here.
 */
export function BackgroundStep(props: Props) {
  return (
    <div class="ob-tail">
      <header>
        <h2 class="ob-tail-title">About you</h2>
        <p class="ob-hero-sub">
          The questions portals ask that a resume never answers. Demographic, legal and
          reason-for-leaving answers are always held for your review before anything is sent.
        </p>
      </header>

      <section class="ob-detail-card">
        <h3 class="ob-group-head">Demographics</h3>
        <p class="fine-print">Voluntary. Leave any of these blank and the portal question stays unanswered.</p>
        <EqualEmploymentStep fields={props.eeo} setField={props.setEeoField} />
      </section>

      <section class="ob-detail-card">
        <h3 class="ob-group-head">Legal</h3>
        <Choice
          label="Have you ever been convicted of a crime?"
          options={['Yes', 'No']}
          value={props.legal.criminalRecordDefault}
          onChange={(value) => props.setLegalField('criminalRecordDefault', value === 'Yes' ? 'Yes' : 'No')}
        />
        <Choice
          label="Have you worked for the employer you are applying to before?"
          hint="the usual answer; you can change it per application"
          options={['Yes', 'No']}
          value={props.legal.previouslyEmployedDefault}
          onChange={(value) => props.setLegalField('previouslyEmployedDefault', value === 'Yes' ? 'Yes' : 'No')}
        />
      </section>

      <section class="ob-detail-card">
        <h3 class="ob-group-head">
          References <span class="ob-group-count">{props.references.length} of {MAX_PROFILE_REFERENCES}</span>
        </h3>
        <p class="fine-print">Some applications ask for up to three. Add them once and they are filled in for you.</p>
        <For each={props.references}>
          {(reference, index) => (
            <article class="ob-entry">
              <div class="ob-entry-top">
                <span class="ob-entry-label">Reference {index() + 1}</span>
                <button
                  class="ob-row-remove"
                  type="button"
                  aria-label={`Remove reference ${index() + 1}`}
                  onClick={() => props.removeReference(index())}
                >
                  <X size={13} aria-hidden="true" />
                </button>
              </div>
              <div class="ob-identity-grid">
                <For each={REFERENCE_FIELDS}>
                  {(field) => (
                    <label class="form-field">
                      <span>{field.label}</span>
                      <input
                        type={field.type ?? 'text'}
                        value={reference[field.key]}
                        onInput={(event) => props.setReference(index(), field.key, event.currentTarget.value)}
                      />
                    </label>
                  )}
                </For>
              </div>
            </article>
          )}
        </For>
        <Show when={props.references.length < MAX_PROFILE_REFERENCES}>
          <button class="ob-add" type="button" onClick={() => props.addReference()}>
            <Plus size={13} aria-hidden="true" />
            <span>Add a reference</span>
          </button>
        </Show>
      </section>

      <div class="ob-confirm-bar">
        <p class="fine-print">
          Signature fields are filled with your legal name and the date, and shown to you before submit.
        </p>
        <button class="primary-action ob-advance" type="button" onClick={() => props.onContinue()}>
          <ArrowRight size={17} aria-hidden="true" />
          <span>Continue</span>
        </button>
      </div>
    </div>
  )
}
