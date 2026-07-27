import { For, Show } from 'solid-js'
import { KeyRound, ShieldCheck, Sparkles } from 'lucide-solid'
import { PROVIDER_OPTIONS } from '../../utils/providerOptions'
import { EqualEmploymentStep, type EeoFields } from './EqualEmploymentStep'

export type CredentialFields = {
  applicationEmail: string
  applicationPassword: string
  gmailOtpEnabled: boolean
}

export type ProviderFields = {
  provider: string
  providerDisplayName: string
  providerApiKey: string
  providerModel: string
}

type Props = {
  workAuthSummary: string
  setWorkAuthSummary: (value: string) => void
  sponsorshipRequired: boolean
  setSponsorshipRequired: (value: boolean) => void
  eeo: EeoFields
  setEeoField: <K extends keyof EeoFields>(key: K, value: EeoFields[K]) => void
  credentials: CredentialFields
  setCredential: <K extends keyof CredentialFields>(key: K, value: CredentialFields[K]) => void
  passwordIsValid: boolean
  provider: ProviderFields
  setProviderField: (key: keyof ProviderFields, value: string) => void
  error: string | null
  isSaving: boolean
  onFinish: () => void
}

/**
 * The short tail: only what a resume cannot tell us. Three cards on one screen
 * rather than three steps, because none of them depends on the others.
 */
export function FinalDetails(props: Props) {
  const canFinish = () =>
    props.credentials.applicationEmail.trim().length > 0 && props.passwordIsValid && !props.isSaving

  return (
    <div class="ob-tail">
      <header>
        <h2 class="ob-tail-title">Three things your resume cannot say</h2>
        <p class="ob-hero-sub">Then you are done. All of it stays encrypted on this machine.</p>
      </header>

      {/* ── Work authorization + EEO defaults ──────────────────────────────── */}
      <section class="ob-detail-card">
        <h3 class="ob-group-head">
          <ShieldCheck size={14} aria-hidden="true" />
          <span>Work authorization</span>
        </h3>
        <label class="form-field">
          <span>Summary used to fill portal fields</span>
          <input
            value={props.workAuthSummary}
            placeholder="Authorized to work in the US without sponsorship"
            onInput={(event) => props.setWorkAuthSummary(event.currentTarget.value)}
          />
        </label>
        <label class="toggle-row">
          <input
            type="checkbox"
            checked={props.sponsorshipRequired}
            onChange={(event) => props.setSponsorshipRequired(event.currentTarget.checked)}
          />
          <span>I require visa sponsorship</span>
        </label>

        <details class="ob-disclosure">
          <summary>Equal employment defaults</summary>
          <p class="review-always">
            These are defaults, not answers. EEO, criminal-history and previous-employer questions
            are always held for your review before anything is submitted.
          </p>
          <EqualEmploymentStep fields={props.eeo} setField={props.setEeoField} />
        </details>
      </section>

      {/* ── Portal credentials ─────────────────────────────────────────────── */}
      <section class="ob-detail-card">
        <h3 class="ob-group-head">
          <KeyRound size={14} aria-hidden="true" />
          <span>Portal sign-in</span>
        </h3>
        <p class="fine-print">The account used to log in to job portals. Encrypted by Electron safeStorage.</p>
        <label class="form-field">
          <span>Email</span>
          <input
            type="email"
            autocomplete="username"
            value={props.credentials.applicationEmail}
            onInput={(event) => props.setCredential('applicationEmail', event.currentTarget.value)}
          />
        </label>
        <label class="form-field">
          <span>Password</span>
          <input
            type="password"
            autocomplete="new-password"
            value={props.credentials.applicationPassword}
            onInput={(event) => props.setCredential('applicationPassword', event.currentTarget.value)}
          />
        </label>
        <p class="fine-print">12+ characters, with upper, lower, a number and a symbol.</p>
        <label class="toggle-row">
          <input
            type="checkbox"
            checked={props.credentials.gmailOtpEnabled}
            onChange={(event) => props.setCredential('gmailOtpEnabled', event.currentTarget.checked)}
          />
          <span>Pull one-time codes from Gmail</span>
        </label>
      </section>

      {/* ── LLM provider ───────────────────────────────────────────────────── */}
      <section class="ob-detail-card">
        <h3 class="ob-group-head">
          <Sparkles size={14} aria-hidden="true" />
          <span>Tailoring engine</span>
          <span class="mono-chip">optional</span>
        </h3>
        <p class="fine-print">
          Drives resume tailoring and job-description analysis. Skip it and everything falls back to
          deterministic templates.
        </p>
        <label class="form-field">
          <span>Provider</span>
          <select
            value={props.provider.provider}
            onChange={(event) => {
              const value = event.currentTarget.value
              props.setProviderField('provider', value)
              props.setProviderField(
                'providerDisplayName',
                PROVIDER_OPTIONS.find((option) => option.value === value)?.label ?? value,
              )
            }}
          >
            <For each={PROVIDER_OPTIONS}>{(option) => <option value={option.value}>{option.label}</option>}</For>
          </select>
        </label>
        <label class="form-field">
          <span>API key</span>
          <input
            type="password"
            autocomplete="off"
            value={props.provider.providerApiKey}
            onInput={(event) => props.setProviderField('providerApiKey', event.currentTarget.value)}
          />
        </label>
        <label class="form-field">
          <span>Model</span>
          <input
            value={props.provider.providerModel}
            placeholder="leave blank for the provider default"
            onInput={(event) => props.setProviderField('providerModel', event.currentTarget.value)}
          />
        </label>
      </section>

      <Show when={props.error}>{(message) => <div class="error-box">{message()}</div>}</Show>

      <button class="primary-action ob-advance" type="button" disabled={!canFinish()} onClick={props.onFinish}>
        <ShieldCheck size={17} aria-hidden="true" />
        <span>{props.isSaving ? 'Saving…' : 'Create my profile'}</span>
      </button>
    </div>
  )
}
