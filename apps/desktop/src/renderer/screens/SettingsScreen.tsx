import { For, Show, createSignal, onMount } from 'solid-js'
import { createStore } from 'solid-js/store'
import { ShieldCheck, Mail, Wrench } from 'lucide-solid'
import { useSettingsStore } from '../contexts/SettingsStore'
import type { ThemePreference } from '@applyocalypse/shared-types'
import { PROVIDER_OPTIONS, type ProviderOptionValue } from '../utils/providerOptions'

const providerOptions = PROVIDER_OPTIONS

type ProviderValue = ProviderOptionValue

export default function SettingsScreen() {
  const {
    state,
    setThemePreference,
    setMaxConcurrentApplications,
    setAutofillApprovedDefaults,
    chooseOutputDir,
    saveProviderApiKey,
  } = useSettingsStore()

  const [form, setForm] = createStore({
    provider: 'openai' as ProviderValue,
    providerDisplayName: 'OpenAI',
    providerModel: '',
    providerStrongModel: '',
    providerFastModel: '',
    providerApiBase: '',
    providerApiVersion: '',
    providerAwsAccessKeyId: '',
    providerAwsRegion: '',
    providerApiKey: '',
  })

  const submitProviderKey = () => {
    const metadataEntries = {
      defaultModel: form.providerModel.trim(),
      strongModel: form.providerStrongModel.trim(),
      fastModel: form.providerFastModel.trim(),
      apiBase: form.providerApiBase.trim(),
      apiVersion: form.providerApiVersion.trim(),
      awsAccessKeyId: form.providerAwsAccessKeyId.trim(),
      awsRegion: form.providerAwsRegion.trim(),
    }
    void saveProviderApiKey({
      provider: form.provider,
      displayName: form.providerDisplayName || providerOptions.find((o) => o.value === form.provider)?.label || form.provider,
      apiKey: form.providerApiKey,
      metadata: Object.fromEntries(Object.entries(metadataEntries).filter(([, v]) => v.length > 0)),
    })
    setForm('providerApiKey', '')
  }

  const maxConcurrent = () => Number(state.settings['automation.maxConcurrentApplications'] ?? 2)
  const autofillDefaults = () => state.settings['automation.autofillApprovedDefaults'] === true
  const outputDir = () => (state.settings['files.outputDir'] as string | undefined) ?? ''

  type ConverterStatus = { available: boolean; version: string | null; path: string | null; installUrl: string }
  type ConverterMap = { libreoffice: ConverterStatus; word: ConverterStatus; tectonic: ConverterStatus }
  const [converters, setConverters] = createSignal<ConverterMap | null>(null)
  const [convertersLoading, setConvertersLoading] = createSignal(false)

  const checkConverters = async () => {
    setConvertersLoading(true)
    try {
      const result = await window.applyocalypse.system.checkConverters()
      setConverters(result.converters)
    } finally {
      setConvertersLoading(false)
    }
  }

  const [gmailStatus, setGmailStatus] = createSignal<{ connected: boolean; email: string | null }>({ connected: false, email: null })
  const [gmailStatusLoading, setGmailStatusLoading] = createSignal(true)
  const [gmailOAuthForm, setGmailOAuthForm] = createStore({ clientId: '', clientSecret: '' })
  const [gmailConnecting, setGmailConnecting] = createSignal(false)
  const [gmailError, setGmailError] = createSignal<string | null>(null)

  onMount(async () => {
    try {
      const status = await window.applyocalypse.gmail.getOAuthStatus()
      setGmailStatus(status)
    } finally {
      setGmailStatusLoading(false)
    }
  })

  const connectGmail = async () => {
    const clientId = gmailOAuthForm.clientId.trim()
    const clientSecret = gmailOAuthForm.clientSecret.trim()
    if (!clientId || !clientSecret) {
      setGmailError('Enter your Google OAuth client ID and secret.')
      return
    }
    setGmailError(null)
    setGmailConnecting(true)
    try {
      const result = await window.applyocalypse.gmail.startOAuth({ clientId, clientSecret })
      if (result.ok) {
        setGmailStatus({ connected: true, email: result.email })
        setGmailOAuthForm('clientId', '')
        setGmailOAuthForm('clientSecret', '')
      } else {
        setGmailError(result.message)
      }
    } finally {
      setGmailConnecting(false)
    }
  }

  const disconnectGmail = async () => {
    await window.applyocalypse.gmail.disconnectOAuth()
    setGmailStatus({ connected: false, email: null })
  }

  return (
    <section class="surface-panel surface-panel-active" data-gsap="panel" data-view-panel>
      {/* Section 1: LLM Providers */}
      <div class="section-header">
        <div>
          <div class="panel-kicker">Provider connections</div>
          <h2>BYOK model routing</h2>
        </div>
        <ShieldCheck size={20} aria-hidden="true" />
      </div>

      <div class="starter-profile">
        <label>
          <span>Provider</span>
          <select
            value={form.provider}
            onChange={(e) => {
              const provider = e.currentTarget.value as ProviderValue
              setForm('provider', provider)
              setForm('providerDisplayName', providerOptions.find((o) => o.value === provider)?.label ?? provider)
            }}
          >
            <For each={providerOptions}>
              {(p) => <option value={p.value}>{p.label}</option>}
            </For>
          </select>
        </label>
        <label>
          <span>Display name</span>
          <input value={form.providerDisplayName} onInput={(e) => setForm('providerDisplayName', e.currentTarget.value)} />
        </label>
        <label>
          <span>API key</span>
          <input
            type="password"
            value={form.providerApiKey}
            autocomplete="off"
            onInput={(e) => setForm('providerApiKey', e.currentTarget.value)}
          />
        </label>
        <label>
          <span>Model (default)</span>
          <input value={form.providerModel} placeholder="provider/model" onInput={(e) => setForm('providerModel', e.currentTarget.value)} />
        </label>
        <label>
          <span>Tailoring model</span>
          <input value={form.providerStrongModel} placeholder="strong model for resume/cover letter" onInput={(e) => setForm('providerStrongModel', e.currentTarget.value)} />
        </label>
        <label>
          <span>Analysis model</span>
          <input value={form.providerFastModel} placeholder="fast model for JD analysis" onInput={(e) => setForm('providerFastModel', e.currentTarget.value)} />
        </label>
        <label>
          <span>API base</span>
          <input value={form.providerApiBase} placeholder="https://" onInput={(e) => setForm('providerApiBase', e.currentTarget.value)} />
        </label>
        <Show when={form.provider === 'azure_openai'}>
          <label>
            <span>API version</span>
            <input value={form.providerApiVersion} placeholder="2025-01-01-preview" onInput={(e) => setForm('providerApiVersion', e.currentTarget.value)} />
          </label>
        </Show>
        <Show when={form.provider === 'aws_bedrock'}>
          <label>
            <span>AWS access key ID</span>
            <input value={form.providerAwsAccessKeyId} autocomplete="off" onInput={(e) => setForm('providerAwsAccessKeyId', e.currentTarget.value)} />
          </label>
          <label>
            <span>AWS region</span>
            <input value={form.providerAwsRegion} placeholder="us-east-1" onInput={(e) => setForm('providerAwsRegion', e.currentTarget.value)} />
          </label>
        </Show>
        <button class="secondary-action" type="button" disabled={state.isLoading} onClick={submitProviderKey}>
          <ShieldCheck size={17} aria-hidden="true" />
          <span>{state.isLoading ? 'Saving...' : 'Save key reference'}</span>
        </button>
      </div>

      <div class="queue-list">
        <For each={state.providerConnections}>
          {(conn) => (
            <div class="queue-row static-row">
              <span>{conn.status}</span>
              <strong>{conn.displayName}</strong>
            </div>
          )}
        </For>
      </div>

      {/* Section 2: Theme */}
      <div style={{ 'margin-top': '2rem' }}>
        <div class="panel-kicker">Native theme</div>
        <div class="segmented-control" aria-label="Theme mode">
          {(['dark', 'light', 'system'] as ThemePreference[]).map((pref) => (
            <button
              classList={{ active: state.theme.preference === pref }}
              type="button"
              onClick={() => void setThemePreference(pref)}
            >
              {pref.charAt(0).toUpperCase() + pref.slice(1)}
            </button>
          ))}
        </div>
        <p class="fine-print">Active: {state.theme.activeTheme}</p>
      </div>

      {/* Section 3: Automation */}
      <div style={{ 'margin-top': '2rem' }}>
        <div class="panel-kicker">Automation concurrency</div>
        <div class="segmented-control" aria-label="Maximum concurrent application runs">
          {([1, 2, 3] as const).map((n) => (
            <button
              classList={{ active: maxConcurrent() === n }}
              type="button"
              onClick={() => void setMaxConcurrentApplications(n)}
            >
              {n}
            </button>
          ))}
        </div>
      </div>

      {/* Section 3b: Autofill approved defaults */}
      <div style={{ 'margin-top': '2rem' }}>
        <div class="panel-kicker">Autofill approved defaults (name, address, links) without review</div>
        <div class="segmented-control" aria-label="Autofill approved defaults">
          {([false, true] as const).map((val) => (
            <button
              classList={{ active: autofillDefaults() === val }}
              type="button"
              onClick={() => void setAutofillApprovedDefaults(val)}
            >
              {val ? 'On' : 'Off'}
            </button>
          ))}
        </div>
        <p class="fine-print">EEO and sensitive questions always require review.</p>
      </div>

      {/* Section 4: Output dir */}
      <div style={{ 'margin-top': '2rem' }}>
        <div class="panel-kicker">Output directory</div>
        <div style={{ display: 'flex', gap: '0.5rem', 'align-items': 'center' }}>
          <code style={{ flex: '1', 'font-size': '0.78rem', color: 'var(--text-secondary)' }}>
            {outputDir() || 'Default downloads folder'}
          </code>
          <button class="secondary-action" type="button" disabled={state.isLoading} onClick={() => void chooseOutputDir()}>
            Change
          </button>
        </div>
      </div>

      {/* Section 6: Converter diagnostics */}
      <div style={{ 'margin-top': '2rem' }}>
        <div class="section-header">
          <div>
            <div class="panel-kicker">Document converters</div>
            <h3>Converter diagnostics</h3>
          </div>
          <Wrench size={20} aria-hidden="true" />
        </div>
        <Show
          when={converters() !== null}
          fallback={
            <button
              class="secondary-action"
              type="button"
              disabled={convertersLoading()}
              onClick={() => void checkConverters()}
            >
              <Wrench size={17} aria-hidden="true" />
              <span>{convertersLoading() ? 'Checking...' : 'Check converters'}</span>
            </button>
          }
        >
          {(['libreoffice', 'word', 'tectonic'] as const).map((key) => {
            const labels: Record<string, string> = { libreoffice: 'LibreOffice', word: 'Microsoft Word', tectonic: 'Tectonic (LaTeX)' }
            const status = converters()![key]
            return (
              <div class="queue-row static-row" style={{ 'margin-top': '0.4rem' }}>
                <span style={{ color: status.available ? 'var(--success)' : 'var(--danger)' }}>
                  {status.available ? 'OK' : 'MISSING'}
                </span>
                <strong>{labels[key]}</strong>
                <Show when={status.available && status.version}>
                  <span style={{ color: 'var(--text-secondary)', 'font-size': '0.78rem' }}>{status.version}</span>
                </Show>
                <Show when={!status.available}>
                  <a
                    href={status.installUrl}
                    target="_blank"
                    rel="noopener noreferrer"
                    class="secondary-action"
                    style={{ 'font-size': '0.78rem', padding: '2px 8px' }}
                  >
                    Install
                  </a>
                </Show>
              </div>
            )
          })}
          <button
            class="secondary-action"
            type="button"
            style={{ 'margin-top': '0.5rem' }}
            disabled={convertersLoading()}
            onClick={() => void checkConverters()}
          >
            <span>{convertersLoading() ? 'Checking...' : 'Re-check'}</span>
          </button>
        </Show>
      </div>

      {/* Section 5: Gmail OTP via OAuth */}
      <div style={{ 'margin-top': '2rem' }}>
        <div class="section-header">
          <div>
            <div class="panel-kicker">OTP extraction</div>
            <h3>Gmail OAuth</h3>
          </div>
          <Mail size={20} aria-hidden="true" />
        </div>
        <Show when={!gmailStatusLoading()} fallback={<p class="fine-print" style={{ 'margin-top': '0.5rem' }}>Checking Gmail connection...</p>}>
        <Show
          when={gmailStatus().connected}
          fallback={
            <div class="starter-profile">
              <p class="fine-print">Connect your Gmail account to automatically extract OTP codes during application runs. Requires a Google Cloud project with the Gmail API enabled.</p>
              <label>
                <span>OAuth client ID</span>
                <input
                  value={gmailOAuthForm.clientId}
                  onInput={(e) => setGmailOAuthForm('clientId', e.currentTarget.value)}
                  placeholder="*.apps.googleusercontent.com"
                  autocomplete="off"
                />
              </label>
              <label>
                <span>OAuth client secret</span>
                <input
                  type="password"
                  value={gmailOAuthForm.clientSecret}
                  onInput={(e) => setGmailOAuthForm('clientSecret', e.currentTarget.value)}
                  autocomplete="off"
                />
              </label>
              <Show when={gmailError()}>
                <p class="fine-print" style={{ color: 'var(--danger)' }}>{gmailError()}</p>
              </Show>
              <button
                class="secondary-action"
                type="button"
                disabled={gmailConnecting()}
                onClick={() => void connectGmail()}
              >
                <Mail size={17} aria-hidden="true" />
                <span>{gmailConnecting() ? 'Connecting...' : 'Connect Gmail'}</span>
              </button>
            </div>
          }
        >
          <div class="queue-row static-row" style={{ 'margin-top': '0.5rem' }}>
            <span style={{ color: 'var(--success)' }}>CONNECTED</span>
            <strong>{gmailStatus().email ?? 'Gmail account'}</strong>
            <button class="secondary-action" type="button" onClick={() => void disconnectGmail()}>
              Disconnect
            </button>
          </div>
        </Show>
        </Show>
      </div>
    </section>
  )
}
