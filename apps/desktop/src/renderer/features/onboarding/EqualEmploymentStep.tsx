import { For, Show } from 'solid-js'
import { ChevronRight } from 'lucide-solid'

export type EeoFields = {
  eeoAuthorizedToWorkUS: string | null
  eeoRequiresSponsorship: string | null
  eeoSponsorshipDetailText: string
  eeoDisability: string | null
  eeoGender: string
  eeoLgbtq: string | null
  eeoVeteran: string | null
  eeoRace: string
  eeoHispanicOrLatino: string | null
  eeoSexualOrientation: string[] | null
}

type Props = {
  fields: EeoFields
  setField: <K extends keyof EeoFields>(key: K, value: EeoFields[K]) => void
  /** Omitted when the fields are embedded in a larger screen that owns the advance. */
  onNext?: () => void
}

const YES_NO = ['Yes', 'No']
const YES_NO_PREFER = ['Yes', 'No', 'Prefer not to say']

/**
 * A three-way choice rendered as a segmented control rather than a select. These
 * are the answers most worth being able to read back at a glance later, and a
 * closed dropdown hides the one thing the user came here to check.
 */
const Choice = (props: {
  label: string
  hint?: string
  options: string[]
  value: string | null
  onChange: (value: string | null) => void
}) => (
  <div class="eeo-field">
    <span class="eeo-label">
      {props.label}
      <Show when={props.hint}>{(hint) => <em class="eeo-hint">{hint()}</em>}</Show>
    </span>
    <div class="eeo-choices" role="group" aria-label={props.label}>
      <For each={props.options}>
        {(option) => (
          <button
            class="eeo-choice"
            classList={{ picked: props.value === option }}
            type="button"
            aria-pressed={props.value === option}
            onClick={() => props.onChange(props.value === option ? null : option)}
          >
            {option}
          </button>
        )}
      </For>
      <Show when={props.value !== null}>
        <button class="eeo-clear" type="button" onClick={() => props.onChange(null)}>
          Clear
        </button>
      </Show>
    </div>
  </div>
)

export function EqualEmploymentStep(props: Props) {
  // Read through a function, never a hoisted alias: props are getters, and a
  // snapshot taken at setup time would freeze these answers on first render.
  const fields = () => props.fields

  return (
    <div class="eeo-grid">
      <Show when={props.onNext}>
        <header class="eeo-head">
          <h2>Equal employment defaults</h2>
          <p class="fine-print">
            These are your default answers for EEO questions on job portals. Every one of them is held
            for your review before it is ever submitted.
          </p>
        </header>
      </Show>

      <Choice
        label="Authorized to work in the US"
        options={YES_NO}
        value={fields().eeoAuthorizedToWorkUS}
        onChange={(value) => props.setField('eeoAuthorizedToWorkUS', value)}
      />
      <Choice
        label="Requires visa sponsorship"
        options={YES_NO}
        value={fields().eeoRequiresSponsorship}
        onChange={(value) => props.setField('eeoRequiresSponsorship', value)}
      />

      <label class="eeo-field">
        <span class="eeo-label">
          Work authorization detail
          <em class="eeo-hint">used verbatim when a portal asks in free text</em>
        </span>
        <textarea
          class="eeo-text"
          rows="3"
          value={fields().eeoSponsorshipDetailText}
          onInput={(event) => props.setField('eeoSponsorshipDetailText', event.currentTarget.value)}
        />
      </label>

      <div class="eeo-pair">
        <label class="eeo-field">
          <span class="eeo-label">Gender identity</span>
          <input
            value={fields().eeoGender}
            onInput={(event) => props.setField('eeoGender', event.currentTarget.value)}
          />
        </label>
        <label class="eeo-field">
          <span class="eeo-label">Race or ethnicity</span>
          <input
            value={fields().eeoRace}
            onInput={(event) => props.setField('eeoRace', event.currentTarget.value)}
          />
        </label>
      </div>

      <Choice
        label="Hispanic or Latino"
        options={YES_NO}
        value={fields().eeoHispanicOrLatino}
        onChange={(value) => props.setField('eeoHispanicOrLatino', value)}
      />
      <Choice
        label="Disability status"
        options={YES_NO_PREFER}
        value={fields().eeoDisability}
        onChange={(value) => props.setField('eeoDisability', value)}
      />
      <Choice
        label="Veteran status"
        options={YES_NO_PREFER}
        value={fields().eeoVeteran}
        onChange={(value) => props.setField('eeoVeteran', value)}
      />
      <Choice
        label="LGBTQ+ identity"
        options={YES_NO_PREFER}
        value={fields().eeoLgbtq}
        onChange={(value) => props.setField('eeoLgbtq', value)}
      />

      <p class="fine-print">Leaving any of these blank means the portal answer is left unanswered.</p>

      <Show when={props.onNext}>
        {(next) => (
          <button class="primary-action ob-advance" type="button" onClick={() => next()()}>
            <ChevronRight size={17} aria-hidden="true" />
            <span>Continue</span>
          </button>
        )}
      </Show>
    </div>
  )
}
