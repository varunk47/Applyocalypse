import { For, Show, createSignal, onMount } from 'solid-js'
import {
  DEFAULT_MAX_CONCURRENT_APPLICATIONS,
  HARD_MAX_CONCURRENT_APPLICATIONS,
} from '@applyocalypse/config'
import { createStore } from 'solid-js/store'
import { BookmarkCheck, Cpu, FolderOpen, KeyRound, Mail, RefreshCw, ShieldCheck, SlidersHorizontal, UserRound } from 'lucide-solid'
import { Switch } from '../components/Switch'
import { useSettingsStore } from '../contexts/SettingsStore'
import type { ThemePreference } from '@applyocalypse/shared-types'
import { PROVIDER_OPTIONS, type ProviderOptionValue } from '../utils/providerOptions'
import { RememberedSettings } from '../features/preferences/RememberedSettings'
import { account, signOut } from '../features/account/accountState'

const providerOptions = PROVIDER_OPTIONS

type ProviderValue = ProviderOptionValue

// Hoisted so <For> sees a stable array identity and does not rebuild the
// segmented controls on every render pass.
const THEME_PREFERENCES: ThemePreference[] = ['dark', 'light', 'system']
// The only paces the scheduler will honour, so the control cannot offer one
// the machine then quietly clamps.
const CONCURRENCY_CHOICES = Array.from(
  { length: HARD_MAX_CONCURRENT_APPLICATIONS },
  (_, index) => index + 1
)
const SETTINGS_PANES = [
  { id: 'remembered', label: 'Remembered', icon: BookmarkCheck },
  { id: 'model', label: 'Model', icon: Cpu },
  { id: 'applying', label: 'Applying', icon: SlidersHorizontal },
  { id: 'accounts', label: 'Accounts', icon: UserRound },
] as const
type SettingsPane = (typeof SETTINGS_PANES)[number]['id']
const CONVERTER_KEYS = ['libreoffice', 'word', 'tectonic'] as const
const CONVERTER_LABELS: Record<(typeof CONVERTER_KEYS)[number], string> = {
  libreoffice: 'LibreOffice',
  word: 'Microsoft Word',
  tectonic: 'Tectonic (LaTeX)',
}

export default function SettingsScreen() {
  const {
    state,
    setThemePreference,
    setMaxConcurrentApplications,
    setAutofillApprovedDefaults,
    setAutoSubmitByDefault,
    chooseOutputDir,
    saveProviderApiKey,
  } = useSettingsStore()
  const [pane, setPane] = createSignal<SettingsPane>('remembered')

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

  const maxConcurrent = () => Number(
    state.settings['automation.maxConcurrentApplications'] ?? DEFAULT_MAX_CONCURRENT_APPLICATIONS
  )
  const autofillDefaults = () => state.settings['automation.autofillApprovedDefaults'] === true
  const autoSubmitByDefault = () => state.settings['automation.autoSubmitByDefault'] === true
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

  // Run unprompted: a missing converter is silent everywhere else.
  onMount(() => void checkConverters())

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

  const [jevConfigured, setJevConfigured] = createSignal(false)
  const [jevKeyInput, setJevKeyInput] = createSignal('')
  const [jevSaving, setJevSaving] = createSignal(false)
  const [jevError, setJevError] = createSignal<string | null>(null)

  onMount(async () => {
    const status = await window.applyocalypse.jev.getStatus()
    setJevConfigured(status.configured)
  })

  const saveJevKey = async () => {
    const key = jevKeyInput().trim()
    if (!key) {
      setJevError('Enter your Vercel AI Gateway key.')
      return
    }
    setJevError(null)
    setJevSaving(true)
    try {
      const status = await window.applyocalypse.jev.saveKey(key)
      setJevConfigured(status.configured)
      setJevKeyInput('')
    } catch {
      setJevError('The key could not be saved.')
    } finally {
      setJevSaving(false)
    }
  }

  const clearJevKey = async () => {
    const status = await window.applyocalypse.jev.clearKey()
    setJevConfigured(status.configured)
  }

  const connectionTone = (status: string) => (status === 'CONNECTED' ? 'sent' : status === 'ERROR' ? 'failed' : 'withdrawn')
  const connectionText = (status: string) => (status === 'CONNECTED' ? 'Connected' : status === 'ERROR' ? 'Error' : 'Not connected')
  const providerName = (value: string) => providerOptions.find((option) => option.value === value)?.label ?? value

  return (
    <section class="surface-panel surface-panel-active settings-screen" data-gsap="panel" data-view-panel>
      <header class="page-head">
        <h1 class="page-title">Settings</h1>
        <p class="page-sub">How it applies, which model it uses, and the accounts it signs in with.</p>
      </header>
      <div class="settings-layout">
        <nav class="settings-subnav" aria-label="Settings sections">
          <For each={SETTINGS_PANES}>
            {(item) => (
              <button
                type="button"
                classList={{ active: pane() === item.id }}
                aria-current={pane() === item.id ? 'page' : undefined}
                onClick={() => setPane(item.id)}
              >
                <item.icon size={16} aria-hidden="true" />
                <span>{item.label}</span>
              </button>
            )}
          </For>
        </nav>

        <div class="settings-pane">
          <Show when={pane() === 'remembered'}>
            <RememberedSettings />
          </Show>

          <Show when={pane() === 'model'}>
            <section class="set-card">
              <header class="set-card-head">
                <div>
                  <h2>Connected models</h2>
                  <p>Tailoring, answers and reading postings run on these. Keys are encrypted on this computer.</p>
                </div>
              </header>
              <Show when={state.providerConnections.length > 0} fallback={<p class="set-empty">No model connected yet. Add one below.</p>}>
                <ul class="set-list">
                  <For each={state.providerConnections}>
                    {(connection) => (
                      <li class="set-row">
                        <span class="set-avatar" aria-hidden="true">{(connection.displayName || connection.provider).charAt(0).toUpperCase()}</span>
                        <div class="set-row-text">
                          <strong>{connection.displayName || providerName(connection.provider)}</strong>
                          <span>{providerName(connection.provider)}</span>
                        </div>
                        <span class={`status-pill tone-${connectionTone(connection.status)}`}>{connectionText(connection.status)}</span>
                      </li>
                    )}
                  </For>
                </ul>
              </Show>
            </section>

            <section class="set-card">
              <header class="set-card-head">
                <div>
                  <h2>Add a provider</h2>
                  <p>Bring your own key. Leave a model blank to use the provider's default.</p>
                </div>
              </header>
              <div class="form-grid">
                <label class="field">
                  <span>Provider</span>
                  <select
                    value={form.provider}
                    onChange={(e) => {
                      const provider = e.currentTarget.value as ProviderValue
                      setForm('provider', provider)
                      setForm('providerDisplayName', providerOptions.find((o) => o.value === provider)?.label ?? provider)
                    }}
                  >
                    <For each={providerOptions}>{(p) => <option value={p.value}>{p.label}</option>}</For>
                  </select>
                </label>
                <label class="field">
                  <span>Display name</span>
                  <input value={form.providerDisplayName} onInput={(e) => setForm('providerDisplayName', e.currentTarget.value)} />
                </label>
                <label class="field span-2">
                  <span>API key</span>
                  <input
                    type="password"
                    value={form.providerApiKey}
                    autocomplete="off"
                    onInput={(e) => setForm('providerApiKey', e.currentTarget.value)}
                  />
                  <small>Encrypted on this computer and never shown again.</small>
                </label>
                <label class="field">
                  <span>Default model</span>
                  <input value={form.providerModel} placeholder="provider/model" onInput={(e) => setForm('providerModel', e.currentTarget.value)} />
                </label>
                <label class="field">
                  <span>Tailoring model</span>
                  <input value={form.providerStrongModel} placeholder="A strong model, for resumes and letters" onInput={(e) => setForm('providerStrongModel', e.currentTarget.value)} />
                </label>
                <label class="field">
                  <span>Analysis model</span>
                  <input value={form.providerFastModel} placeholder="A fast model, for reading postings" onInput={(e) => setForm('providerFastModel', e.currentTarget.value)} />
                </label>
                <label class="field">
                  <span>API base</span>
                  <input value={form.providerApiBase} placeholder="https://" onInput={(e) => setForm('providerApiBase', e.currentTarget.value)} />
                  <small>Only for a self-hosted or proxy endpoint.</small>
                </label>
                <Show when={form.provider === 'azure_openai'}>
                  <label class="field">
                    <span>API version</span>
                    <input value={form.providerApiVersion} placeholder="2025-01-01-preview" onInput={(e) => setForm('providerApiVersion', e.currentTarget.value)} />
                  </label>
                </Show>
                <Show when={form.provider === 'aws_bedrock'}>
                  <label class="field">
                    <span>AWS access key ID</span>
                    <input value={form.providerAwsAccessKeyId} autocomplete="off" onInput={(e) => setForm('providerAwsAccessKeyId', e.currentTarget.value)} />
                  </label>
                  <label class="field">
                    <span>AWS region</span>
                    <input value={form.providerAwsRegion} placeholder="us-east-1" onInput={(e) => setForm('providerAwsRegion', e.currentTarget.value)} />
                  </label>
                </Show>
              </div>
              <div class="set-actions">
                <button class="btn-wax" type="button" disabled={state.isLoading} onClick={submitProviderKey}>
                  <ShieldCheck size={16} aria-hidden="true" />
                  {state.isLoading ? 'Saving…' : 'Save provider'}
                </button>
              </div>
            </section>
          </Show>

          <Show when={pane() === 'applying'}>
            <section class="set-card">
              <header class="set-card-head">
                <div>
                  <h2>Appearance</h2>
                </div>
              </header>
              <div class="set-row">
                <div class="set-row-text">
                  <strong>Theme</strong>
                  <span>Currently {state.theme.activeTheme}.</span>
                </div>
                <div class="segmented-control" aria-label="Theme mode">
                  <For each={THEME_PREFERENCES}>
                    {(pref) => (
                      <button classList={{ active: state.theme.preference === pref }} type="button" onClick={() => void setThemePreference(pref)}>
                        {pref.charAt(0).toUpperCase() + pref.slice(1)}
                      </button>
                    )}
                  </For>
                </div>
              </div>
            </section>

            <section class="set-card">
              <header class="set-card-head">
                <div>
                  <h2>Runs</h2>
                  <p>How the app works through your queue.</p>
                </div>
              </header>
              <div class="set-row">
                <div class="set-row-text">
                  <strong>Applications at once</strong>
                  <span>How many run side by side on this computer. The rest wait their turn.</span>
                </div>
                <div class="segmented-control" aria-label="Maximum concurrent application runs">
                  <For each={CONCURRENCY_CHOICES}>
                    {(n) => (
                      <button classList={{ active: maxConcurrent() === n }} type="button" onClick={() => void setMaxConcurrentApplications(n)}>
                        {n}
                      </button>
                    )}
                  </For>
                </div>
              </div>
              <div class="set-row">
                <div class="set-row-text">
                  <strong>Fill approved details without stopping</strong>
                  <span>
                    Name, address and links go in without a review stop. EEO, criminal history and previous-employer
                    questions always stop, whatever this is set to.
                  </span>
                </div>
                <Switch label="Fill approved details without stopping" checked={autofillDefaults()} onChange={(value) => void setAutofillApprovedDefaults(value)} />
              </div>
              <div class="set-row">
                <div class="set-row-text">
                  <strong>Submit automatically</strong>
                  <span>
                    Ticks "Submit on its own after I approve" for every new job. Each run still stops for you to approve
                    the tailored documents and the answers, and EEO, criminal history and previous-employer questions
                    always wait for you. Once you approve, the application is sent without a second click.
                  </span>
                </div>
                <Switch label="Submit automatically" checked={autoSubmitByDefault()} onChange={(value) => void setAutoSubmitByDefault(value)} />
              </div>
            </section>

            <section class="set-card">
              <header class="set-card-head">
                <div>
                  <h2>Files</h2>
                </div>
              </header>
              <div class="set-row">
                <div class="set-row-text">
                  <strong>Output folder</strong>
                  <code class="settings-path" classList={{ unset: !outputDir() }}>{outputDir() || 'Your Downloads folder'}</code>
                </div>
                <button class="btn-quiet" type="button" disabled={state.isLoading} onClick={() => void chooseOutputDir()}>
                  <FolderOpen size={15} aria-hidden="true" />
                  Change
                </button>
              </div>
            </section>

            <section class="set-card">
              <header class="set-card-head">
                <div>
                  <h2>Document converters</h2>
                  <p>Used to turn tailored documents into PDFs. One is enough.</p>
                </div>
                <button class="btn-quiet" type="button" disabled={convertersLoading()} onClick={() => void checkConverters()}>
                  <RefreshCw size={14} aria-hidden="true" />
                  {convertersLoading() ? 'Checking…' : 'Check again'}
                </button>
              </header>
              <Show when={converters()} fallback={<p class="set-empty">Checking which converters are installed…</p>}>
                {(found) => (
                  <ul class="set-list">
                    <For each={CONVERTER_KEYS}>
                      {(key) => {
                        const status = () => found()[key]
                        return (
                          <li class="set-row">
                            <div class="set-row-text">
                              <strong>{CONVERTER_LABELS[key]}</strong>
                              <span>{status().available ? (status().version ?? 'Installed') : 'Not installed'}</span>
                            </div>
                            <Show
                              when={status().available}
                              fallback={
                                <a class="btn-quiet" href={status().installUrl} target="_blank" rel="noopener noreferrer">
                                  Install
                                </a>
                              }
                            >
                              <span class="status-pill tone-sent">Ready</span>
                            </Show>
                          </li>
                        )
                      }}
                    </For>
                  </ul>
                )}
              </Show>
            </section>
          </Show>

          <Show when={pane() === 'accounts'}>
            <section class="set-card">
              <header class="set-card-head">
                <div>
                  <h2>Your account</h2>
                  <p>It only signs you in. Your profile, documents and history stay on this computer.</p>
                </div>
              </header>
              <div class="set-row account-block">
                <span class="set-avatar" aria-hidden="true">{(account()?.email ?? 'A').charAt(0).toUpperCase()}</span>
                <div class="set-row-text">
                  <strong>{account()?.email ?? 'Signed in'}</strong>
                  <span>Signed in on this computer</span>
                </div>
                <button type="button" class="btn-quiet" onClick={() => void signOut()}>
                  Sign out
                </button>
              </div>
            </section>

            <section class="set-card">
              <header class="set-card-head">
                <div>
                  <h2>Gmail, for email codes</h2>
                  <p>
                    Reads verification codes and links from job emails while a run is going. Needs a Google Cloud project
                    with the Gmail API turned on.
                  </p>
                </div>
              </header>
              <Show when={!gmailStatusLoading()} fallback={<p class="set-empty">Checking the Gmail connection…</p>}>
                <Show
                  when={gmailStatus().connected}
                  fallback={
                    <>
                      <div class="form-grid">
                        <label class="field">
                          <span>OAuth client ID</span>
                          <input
                            value={gmailOAuthForm.clientId}
                            onInput={(e) => setGmailOAuthForm('clientId', e.currentTarget.value)}
                            placeholder="…apps.googleusercontent.com"
                            autocomplete="off"
                          />
                        </label>
                        <label class="field">
                          <span>OAuth client secret</span>
                          <input
                            type="password"
                            value={gmailOAuthForm.clientSecret}
                            onInput={(e) => setGmailOAuthForm('clientSecret', e.currentTarget.value)}
                            autocomplete="off"
                          />
                        </label>
                      </div>
                      <Show when={gmailError()}>
                        <p class="set-error" role="alert">{gmailError()}</p>
                      </Show>
                      <div class="set-actions">
                        <button class="btn-wax" type="button" disabled={gmailConnecting()} onClick={() => void connectGmail()}>
                          <Mail size={16} aria-hidden="true" />
                          {gmailConnecting() ? 'Connecting…' : 'Connect Gmail'}
                        </button>
                      </div>
                    </>
                  }
                >
                  <div class="set-row">
                    <span class="set-avatar" aria-hidden="true">G</span>
                    <div class="set-row-text">
                      <strong>{gmailStatus().email ?? 'Gmail account'}</strong>
                      <span class="status-pill tone-sent">Connected</span>
                    </div>
                    <button class="btn-quiet" type="button" onClick={() => void disconnectGmail()}>
                      Disconnect
                    </button>
                  </div>
                </Show>
              </Show>
            </section>

            <section class="set-card">
              <header class="set-card-head">
                <div>
                  <h2>Jev, the browser driver</h2>
                  <p>
                    With a key saved, Jev chooses each click on every portal. Your answers are still typed by the app,
                    personal details are hidden from Jev, and it never submits.
                  </p>
                </div>
              </header>
              <Show
                when={jevConfigured()}
                fallback={
                  <>
                    <div class="form-grid">
                      <label class="field span-2">
                        <span>Vercel AI Gateway key</span>
                        <input type="password" value={jevKeyInput()} onInput={(e) => setJevKeyInput(e.currentTarget.value)} autocomplete="off" />
                      </label>
                    </div>
                    <Show when={jevError()}>
                      <p class="set-error" role="alert">{jevError()}</p>
                    </Show>
                    <div class="set-actions">
                      <button class="btn-wax" type="button" disabled={jevSaving()} onClick={() => void saveJevKey()}>
                        <KeyRound size={16} aria-hidden="true" />
                        {jevSaving() ? 'Saving…' : 'Save key'}
                      </button>
                    </div>
                  </>
                }
              >
                <div class="set-row">
                  <span class="set-avatar" aria-hidden="true">J</span>
                  <div class="set-row-text">
                    <strong>Jev drives the browser</strong>
                    <span class="status-pill tone-sent">Key saved</span>
                  </div>
                  <button class="btn-quiet" type="button" onClick={() => void clearJevKey()}>
                    Remove key
                  </button>
                </div>
              </Show>
            </section>
          </Show>
        </div>
      </div>
    </section>
  )
}
