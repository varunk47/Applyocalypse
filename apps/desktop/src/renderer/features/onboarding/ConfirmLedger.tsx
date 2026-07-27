import { For, Show, onMount } from 'solid-js'
import { AlertTriangle, Check, Plus, X } from 'lucide-solid'
import { staggerEnterList } from '../../animations/listStagger'
import { countFacts, formatConfidence, lowConfidenceFacts, LOW_CONFIDENCE_THRESHOLD, type ParsedCanonical } from './parsedFacts'

export type IdentityFields = {
  firstName: string
  lastName: string
  email: string
  phone: string
  linkedinUrl: string
  githubUrl: string
  addressLine1: string
  addressLine2: string
  city: string
  state: string
  postalCode: string
  county: string
  country: string
}

export type EducationRow = {
  institution: string
  degree: string
  field: string
  gpa: string
  startDate: string
  endDate: string
}

export type ExperienceRow = {
  company: string
  title: string
  location: string
  startDate: string
  endDate: string
  bullets: string[]
}

type Props = {
  fileName: string | null
  isReading: boolean
  canonical: ParsedCanonical | null
  identity: IdentityFields
  setIdentity: (key: keyof IdentityFields, value: string) => void
  education: EducationRow[]
  setEducation: (index: number, key: keyof EducationRow, value: string) => void
  addEducation: () => void
  removeEducation: (index: number) => void
  experience: ExperienceRow[]
  setExperience: (index: number, key: Exclude<keyof ExperienceRow, 'bullets'>, value: string) => void
  addExperience: () => void
  removeExperience: (index: number) => void
  onConfirm: () => void
}

type FieldSpec = { key: keyof IdentityFields; label: string; placeholder?: string }

const IDENTITY_FIELDS: FieldSpec[] = [
  { key: 'firstName', label: 'First name' },
  { key: 'lastName', label: 'Last name' },
  { key: 'email', label: 'Email' },
  { key: 'phone', label: 'Phone' },
  { key: 'linkedinUrl', label: 'LinkedIn', placeholder: 'https://linkedin.com/in/…' },
  { key: 'githubUrl', label: 'GitHub', placeholder: 'https://github.com/…' },
]

/** Portals ask for a mailing address that a resume almost never carries. */
const ADDRESS_FIELDS: FieldSpec[] = [
  { key: 'addressLine1', label: 'Street' },
  { key: 'addressLine2', label: 'Apt / unit' },
  { key: 'city', label: 'City' },
  { key: 'state', label: 'State' },
  { key: 'postalCode', label: 'Postal code' },
  { key: 'county', label: 'County' },
  { key: 'country', label: 'Country' },
]

/** A parsed entry we are unsure about, so the row can wear a flag. */
const Flag = (props: { confidence: number | undefined }) => (
  <Show when={props.confidence !== undefined && props.confidence < LOW_CONFIDENCE_THRESHOLD}>
    <span class="ob-flag" title="Parsed with low confidence. Worth a second look.">
      <AlertTriangle size={11} aria-hidden="true" />
      <span>{formatConfidence(props.confidence ?? 0)}</span>
    </span>
  </Show>
)

/**
 * The confirm-and-correct surface: everything the parser pulled out of the
 * resume, grouped and inline-editable, with the entries it is least sure about
 * called out up front. This replaces the general-questions, education and
 * work-experience steps of the old wizard with one scannable page.
 */
export function ConfirmLedger(props: Props) {
  let listRef: HTMLDivElement | undefined

  onMount(() => {
    if (listRef && !props.isReading) staggerEnterList(listRef)
  })

  const facts = () => (props.canonical ? countFacts(props.canonical) : 0)
  const flagged = () => (props.canonical ? lowConfidenceFacts(props.canonical) : [])
  const experienceConfidence = (index: number) => props.canonical?.experience[index]?.confidence
  const educationConfidence = (index: number) => props.canonical?.education[index]?.confidence

  return (
    <div class="ob-ledger">
      <Show
        when={!props.isReading}
        fallback={
          <div class="ob-reading">
            <span class="ob-reading-pulse" aria-hidden="true" />
            <div>
              <p class="ob-reading-title">Reading your resume</p>
              <p class="fine-print">{props.fileName ?? 'Parsing…'}</p>
            </div>
          </div>
        }
      >
        <header class="ob-ledger-head">
          <p class="ob-count">
            <strong>{facts()}</strong>
            <span>facts read from {props.fileName ?? 'your resume'}</span>
          </p>
          <Show
            when={flagged().length > 0}
            fallback={
              <p class="ob-allclear">
                <Check size={13} aria-hidden="true" />
                <span>Nothing looks doubtful. Skim it anyway.</span>
              </p>
            }
          >
            <p class="ob-flagbar">
              <AlertTriangle size={13} aria-hidden="true" />
              <span>
                <strong>{flagged().length}</strong> need a look:{' '}
                {flagged()
                  .slice(0, 3)
                  .map((flag) => flag.label)
                  .join(', ')}
                {flagged().length > 3 ? '…' : ''}
              </span>
            </p>
          </Show>
        </header>
      </Show>

      <div ref={listRef} class="ob-groups">
        {/* ── Identity ──────────────────────────────────────────────────────── */}
        <section class="ob-group" data-list-item>
          <h3 class="ob-group-head">Identity</h3>
          <div class="ob-identity-grid">
            <For each={IDENTITY_FIELDS}>
              {(field) => (
                <label class="form-field">
                  <span>{field.label}</span>
                  <input
                    value={props.identity[field.key]}
                    placeholder={field.placeholder ?? ''}
                    onInput={(event) => props.setIdentity(field.key, event.currentTarget.value)}
                  />
                </label>
              )}
            </For>
          </div>
        </section>

        {/* ── Address ───────────────────────────────────────────────────────── */}
        <section class="ob-group" data-list-item>
          <h3 class="ob-group-head">Address</h3>
          <p class="fine-print">Rarely on a resume, always asked for by portals.</p>
          <div class="ob-identity-grid">
            <For each={ADDRESS_FIELDS}>
              {(field) => (
                <label class="form-field">
                  <span>{field.label}</span>
                  <input
                    value={props.identity[field.key]}
                    placeholder={field.placeholder ?? ''}
                    onInput={(event) => props.setIdentity(field.key, event.currentTarget.value)}
                  />
                </label>
              )}
            </For>
          </div>
        </section>

        {/* ── Experience ────────────────────────────────────────────────────── */}
        <section class="ob-group" data-list-item>
          <h3 class="ob-group-head">
            Experience <span class="ob-group-count">{props.experience.length}</span>
          </h3>
          <For
            each={props.experience}
            fallback={<p class="fine-print">No roles found. Add the ones that matter.</p>}
          >
            {(entry, index) => (
              <article class="ob-entry">
                <div class="ob-entry-top">
                  <input
                    class="ob-entry-title"
                    value={entry.title}
                    placeholder="Title"
                    onInput={(event) => props.setExperience(index(), 'title', event.currentTarget.value)}
                  />
                  <Flag confidence={experienceConfidence(index())} />
                  <button
                    class="ob-row-remove"
                    type="button"
                    aria-label={`Remove ${entry.title || 'role'}`}
                    onClick={() => props.removeExperience(index())}
                  >
                    <X size={13} aria-hidden="true" />
                  </button>
                </div>
                <div class="ob-entry-grid">
                  <input
                    value={entry.company}
                    placeholder="Company"
                    onInput={(event) => props.setExperience(index(), 'company', event.currentTarget.value)}
                  />
                  <input
                    value={entry.location}
                    placeholder="Location"
                    onInput={(event) => props.setExperience(index(), 'location', event.currentTarget.value)}
                  />
                  <input
                    value={entry.startDate}
                    placeholder="MM/DD/YYYY"
                    onInput={(event) => props.setExperience(index(), 'startDate', event.currentTarget.value)}
                  />
                  <input
                    value={entry.endDate}
                    placeholder="MM/DD/YYYY or blank"
                    onInput={(event) => props.setExperience(index(), 'endDate', event.currentTarget.value)}
                  />
                </div>
                <p class="fine-print">
                  {entry.bullets.length} bullet{entry.bullets.length === 1 ? '' : 's'} kept for tailoring
                </p>
              </article>
            )}
          </For>
          <button class="ob-add" type="button" onClick={props.addExperience}>
            <Plus size={13} aria-hidden="true" />
            <span>Add a role</span>
          </button>
        </section>

        {/* ── Education ─────────────────────────────────────────────────────── */}
        <section class="ob-group" data-list-item>
          <h3 class="ob-group-head">
            Education <span class="ob-group-count">{props.education.length}</span>
          </h3>
          <For each={props.education} fallback={<p class="fine-print">No schools found.</p>}>
            {(entry, index) => (
              <article class="ob-entry">
                <div class="ob-entry-top">
                  <input
                    class="ob-entry-title"
                    value={entry.institution}
                    placeholder="Institution"
                    onInput={(event) => props.setEducation(index(), 'institution', event.currentTarget.value)}
                  />
                  <Flag confidence={educationConfidence(index())} />
                  <button
                    class="ob-row-remove"
                    type="button"
                    aria-label={`Remove ${entry.institution || 'school'}`}
                    onClick={() => props.removeEducation(index())}
                  >
                    <X size={13} aria-hidden="true" />
                  </button>
                </div>
                <div class="ob-entry-grid">
                  <input
                    value={entry.degree}
                    placeholder="Degree"
                    onInput={(event) => props.setEducation(index(), 'degree', event.currentTarget.value)}
                  />
                  <input
                    value={entry.field}
                    placeholder="Field"
                    onInput={(event) => props.setEducation(index(), 'field', event.currentTarget.value)}
                  />
                  <input
                    value={entry.startDate}
                    placeholder="MM/DD/YYYY"
                    onInput={(event) => props.setEducation(index(), 'startDate', event.currentTarget.value)}
                  />
                  <input
                    value={entry.endDate}
                    placeholder="MM/DD/YYYY"
                    onInput={(event) => props.setEducation(index(), 'endDate', event.currentTarget.value)}
                  />
                </div>
              </article>
            )}
          </For>
          <button class="ob-add" type="button" onClick={props.addEducation}>
            <Plus size={13} aria-hidden="true" />
            <span>Add a school</span>
          </button>
        </section>

        {/* ── Skills ────────────────────────────────────────────────────────── */}
        <Show when={props.canonical?.skillGroups.length}>
          <section class="ob-group" data-list-item>
            <h3 class="ob-group-head">Skills</h3>
            <For each={props.canonical?.skillGroups ?? []}>
              {(group) => (
                <div class="ob-skill-group">
                  <p class="ob-skill-label">
                    {group.label}
                    <Flag confidence={group.confidence} />
                  </p>
                  <div class="ob-chip-row">
                    <For each={group.skills}>{(skill) => <span class="mono-chip">{skill}</span>}</For>
                  </div>
                </div>
              )}
            </For>
          </section>
        </Show>

        {/* ── Certifications ────────────────────────────────────────────────── */}
        <Show when={props.canonical?.certifications.length}>
          <section class="ob-group" data-list-item>
            <h3 class="ob-group-head">Certifications</h3>
            <For each={props.canonical?.certifications ?? []}>
              {(entry) => (
                <p class="ob-fact-line">
                  <span>{entry.name}</span>
                  <span class="fine-print">{entry.issuer ?? entry.issuedAt ?? ''}</span>
                  <Flag confidence={entry.confidence} />
                </p>
              )}
            </For>
          </section>
        </Show>
      </div>

      <button class="primary-action ob-advance" type="button" onClick={props.onConfirm}>
        <Check size={17} aria-hidden="true" />
        <span>Looks right</span>
      </button>
    </div>
  )
}
