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
  onNext: () => void
}

const YesNo = (props: { label: string; value: string | null; onChange: (v: string) => void }) => (
  <label>
    <span>{props.label}</span>
    <select value={props.value ?? ''} onChange={(e) => props.onChange(e.currentTarget.value)}>
      <option value="">-- prefer not to say --</option>
      <option value="Yes">Yes</option>
      <option value="No">No</option>
    </select>
  </label>
)

const YesNoPrefer = (props: { label: string; value: string | null; onChange: (v: string) => void }) => (
  <label>
    <span>{props.label}</span>
    <select value={props.value ?? ''} onChange={(e) => props.onChange(e.currentTarget.value)}>
      <option value="">-- prefer not to say --</option>
      <option value="Yes">Yes</option>
      <option value="No">No</option>
      <option value="Prefer not to say">Prefer not to say</option>
    </select>
  </label>
)

export function EqualEmploymentStep(props: Props) {
  const f = props.fields
  const set = <K extends keyof EeoFields>(k: K) => (v: EeoFields[K]) => props.setField(k, v)

  return (
    <div>
      <h2 style={{ 'margin-bottom': '0.5rem' }}>Equal employment defaults</h2>
      <p style={{ color: 'var(--text-secondary)', 'margin-bottom': '1.5rem' }}>
        These are your default answers for EEO questions on job portals. You will always review them before submission.
      </p>

      <YesNo
        label="Authorized to work in the US?"
        value={f.eeoAuthorizedToWorkUS}
        onChange={(v) => set('eeoAuthorizedToWorkUS')(v || null)}
      />
      <YesNo
        label="Requires visa sponsorship?"
        value={f.eeoRequiresSponsorship}
        onChange={(v) => set('eeoRequiresSponsorship')(v || null)}
      />
      <label>
        <span>Work authorization detail (used in text boxes)</span>
        <textarea
          style={{ width: '100%', 'min-height': '4rem', resize: 'vertical' }}
          value={f.eeoSponsorshipDetailText}
          onInput={(e) => set('eeoSponsorshipDetailText')(e.currentTarget.value)}
        />
      </label>

      <label>
        <span>Gender identity</span>
        <input value={f.eeoGender} onInput={(e) => set('eeoGender')(e.currentTarget.value)} />
      </label>
      <label>
        <span>Race / ethnicity</span>
        <input value={f.eeoRace} onInput={(e) => set('eeoRace')(e.currentTarget.value)} />
      </label>

      <YesNo
        label="Hispanic or Latino?"
        value={f.eeoHispanicOrLatino}
        onChange={(v) => set('eeoHispanicOrLatino')(v || null)}
      />
      <YesNoPrefer
        label="Disability status"
        value={f.eeoDisability}
        onChange={(v) => set('eeoDisability')(v || null)}
      />
      <YesNoPrefer
        label="Veteran status"
        value={f.eeoVeteran}
        onChange={(v) => set('eeoVeteran')(v || null)}
      />
      <YesNoPrefer
        label="LGBTQ+ identity"
        value={f.eeoLgbtq}
        onChange={(v) => set('eeoLgbtq')(v || null)}
      />

      <button class="primary-action" type="button" style={{ 'margin-top': '1.5rem' }} onClick={props.onNext}>
        <ChevronRight size={17} aria-hidden="true" />
        <span>Continue</span>
      </button>
    </div>
  )
}
