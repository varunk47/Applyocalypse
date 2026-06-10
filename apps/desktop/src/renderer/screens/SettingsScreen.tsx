import { For, Show } from 'solid-js'
import { createStore } from 'solid-js/store'
import { ShieldCheck } from 'lucide-solid'
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
  const outputDir = () => (state.settings['files.outputDir'] as string | undefined) ?? ''

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
        <button class="secondary-action" type="button" onClick={submitProviderKey}>
          <ShieldCheck size={17} aria-hidden="true" />
          <span>Save key reference</span>
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

      {/* Section 4: Output dir */}
      <div style={{ 'margin-top': '2rem' }}>
        <div class="panel-kicker">Output directory</div>
        <div style={{ display: 'flex', gap: '0.5rem', 'align-items': 'center' }}>
          <code style={{ flex: '1', 'font-size': '0.78rem', color: 'var(--text-secondary)' }}>
            {outputDir() || 'Default downloads folder'}
          </code>
          <button class="secondary-action" type="button" onClick={() => void chooseOutputDir()}>
            Change
          </button>
        </div>
      </div>
    </section>
  )
}
