import { ChevronRight } from 'lucide-solid'

export type GeneralQuestionsFields = {
  firstName: string
  lastName: string
  email: string
  phone: string
  country: string
  city: string
  state: string
  addressLine1: string
  addressLine2: string
  postalCode: string
  county: string
  linkedinUrl: string
  githubUrl: string
}

type Props = {
  fields: GeneralQuestionsFields
  setField: <K extends keyof GeneralQuestionsFields>(key: K, value: GeneralQuestionsFields[K]) => void
  onNext: () => void
}

const inp = (
  label: string,
  value: string,
  onInput: (v: string) => void,
  opts?: { type?: string; placeholder?: string }
) => (
  <label>
    <span>{label}</span>
    <input
      type={opts?.type ?? 'text'}
      value={value}
      placeholder={opts?.placeholder}
      onInput={(e) => onInput(e.currentTarget.value)}
    />
  </label>
)

export function GeneralQuestionsStep(props: Props) {
  const f = props.fields
  const set = <K extends keyof GeneralQuestionsFields>(k: K) =>
    (v: GeneralQuestionsFields[K]) => props.setField(k, v)

  return (
    <div>
      <h2 style={{ 'margin-bottom': '0.5rem' }}>About you</h2>
      <p style={{ color: 'var(--text-secondary)', 'margin-bottom': '1.5rem' }}>
        Used to fill name, address, and contact fields on job portals.
      </p>

      <div style={{ display: 'grid', 'grid-template-columns': '1fr 1fr', gap: '0.75rem' }}>
        {inp('First name', f.firstName, set('firstName'))}
        {inp('Last name', f.lastName, set('lastName'))}
      </div>
      {inp('Personal email', f.email, set('email'), { type: 'email' })}
      {inp('Phone', f.phone, set('phone'), { type: 'tel' })}
      {inp('Country', f.country, set('country'))}
      <div style={{ display: 'grid', 'grid-template-columns': '1fr 1fr', gap: '0.75rem' }}>
        {inp('City', f.city, set('city'))}
        {inp('State', f.state, set('state'))}
      </div>
      {inp('Address line 1', f.addressLine1, set('addressLine1'))}
      {inp('Address line 2', f.addressLine2, set('addressLine2'))}
      <div style={{ display: 'grid', 'grid-template-columns': '1fr 1fr', gap: '0.75rem' }}>
        {inp('Postal code', f.postalCode, set('postalCode'))}
        {inp('County', f.county, set('county'))}
      </div>
      {inp('LinkedIn URL (optional)', f.linkedinUrl, set('linkedinUrl'), { type: 'url', placeholder: 'https://linkedin.com/in/...' })}
      {inp('GitHub URL (optional)', f.githubUrl, set('githubUrl'), { type: 'url', placeholder: 'https://github.com/...' })}

      <button
        class="primary-action"
        type="button"
        style={{ 'margin-top': '1.5rem' }}
        disabled={!f.firstName.trim()}
        onClick={props.onNext}
      >
        <ChevronRight size={17} aria-hidden="true" />
        <span>Continue</span>
      </button>
    </div>
  )
}
