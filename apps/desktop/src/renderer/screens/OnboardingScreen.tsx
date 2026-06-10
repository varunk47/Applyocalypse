import { Show, createSignal, onCleanup, onMount } from 'solid-js'
import { useNavigate } from '@solidjs/router'
import { createStore } from 'solid-js/store'
import { ChevronRight, ShieldCheck, Upload } from 'lucide-solid'
import { useProfileStore } from '../contexts/ProfileStore'
import { useSettingsStore } from '../contexts/SettingsStore'
import { gsap } from '../animations/gsap'
import { enterStepFromRight, exitStepToLeft } from '../animations/screenTransition'

type OnboardingStep = 'welcome' | 'upload' | 'parse-review' | 'work-auth' | 'credentials' | 'provider' | 'done'

const STEPS: OnboardingStep[] = ['welcome', 'upload', 'parse-review', 'work-auth', 'credentials', 'provider', 'done']

const STEP_LABELS: Record<OnboardingStep, string> = {
  'welcome':      'Welcome',
  'upload':       'Upload Resume',
  'parse-review': 'Review Profile',
  'work-auth':    'Work Authorization',
  'credentials':  'App Credentials',
  'provider':     'LLM Provider',
  'done':         'Ready',
}

const applicationPasswordIsValid = (value: string): boolean =>
  /^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[^A-Za-z0-9]).{12,}$/.test(value)

export default function OnboardingScreen() {
  const { state: profileState, createStarterProfile, pickAndRegisterResume } = useProfileStore()
  const { saveProviderApiKey } = useSettingsStore()
  const navigate = useNavigate()

  const [stepIndex, setStepIndex] = createSignal(0)
  const [form, setForm] = createStore({
    legalName: '',
    email: '',
    location: '',
    applicationEmail: '',
    applicationPassword: '',
    gmailOtpEnabled: false,
    workAuthSummary: '',
    sponsorshipRequired: false,
    provider: 'openai',
    providerDisplayName: 'OpenAI',
    providerModel: '',
    providerApiKey: '',
  })

  let stepRef: HTMLDivElement | undefined
  let progressFillRef: HTMLDivElement | undefined

  const step = (): OnboardingStep => STEPS[Math.min(stepIndex(), STEPS.length - 1)] ?? 'welcome'
  const progress = () => ((stepIndex() + 1) / STEPS.length) * 100

  onMount(() => {
    if (progressFillRef) {
      gsap.to(progressFillRef, { width: `${progress()}%`, duration: 0.4, ease: 'power3.out' })
    }
  })

  const animateToStep = (direction: 'forward' | 'back') => {
    if (!stepRef) return
    const outFn = direction === 'forward' ? exitStepToLeft : (el: Element, done: () => void) => {
      gsap.to(el, { x: 60, opacity: 0, duration: 0.18, ease: 'expo.in', onComplete: done })
    }
    const inFn = direction === 'forward' ? enterStepFromRight : (el: Element, done: () => void) => {
      gsap.fromTo(el, { x: -60, opacity: 0 }, { x: 0, opacity: 1, duration: 0.35, ease: 'expo.out', onComplete: done })
    }
    outFn(stepRef, () => {
      inFn(stepRef!, () => {})
    })
  }

  const advance = () => {
    if (stepIndex() >= STEPS.length - 1) return
    animateToStep('forward')
    setStepIndex((i) => i + 1)
    if (progressFillRef) {
      gsap.to(progressFillRef, { width: `${((stepIndex() + 1) / STEPS.length) * 100}%`, duration: 0.4, ease: 'power3.out' })
    }
  }

  const retreat = () => {
    if (stepIndex() <= 0) return
    animateToStep('back')
    setStepIndex((i) => i - 1)
    if (progressFillRef) {
      gsap.to(progressFillRef, { width: `${((stepIndex() + 1) / STEPS.length) * 100}%`, duration: 0.4, ease: 'power3.out' })
    }
  }

  const handleKeyDown = (e: KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) advance()
    if (e.key === 'Tab' && !e.shiftKey) { e.preventDefault(); retreat() }
  }

  onMount(() => window.addEventListener('keydown', handleKeyDown))
  onCleanup(() => window.removeEventListener('keydown', handleKeyDown))

  const handleCreateProfile = async () => {
    await createStarterProfile({
      legalName: form.legalName,
      email: form.email || null,
      location: form.location || null,
      applicationEmail: form.applicationEmail,
      applicationPassword: form.applicationPassword,
      gmailOtpEnabled: form.gmailOtpEnabled,
      workAuthorization: {
        summary: form.workAuthSummary,
        sponsorshipRequired: form.sponsorshipRequired,
      },
    })
    if (!profileState.error) advance()
  }

  const handleSaveProvider = async () => {
    await saveProviderApiKey({
      provider: form.provider as 'openai',
      displayName: form.providerDisplayName,
      apiKey: form.providerApiKey,
      ...(form.providerModel ? { metadata: { defaultModel: form.providerModel } } : {}),
    })
    advance()
  }

  const handleComplete = () => navigate('/', { replace: true })

  return (
    <div
      style={{
        position: 'fixed',
        inset: '0',
        display: 'flex',
        'align-items': 'center',
        'justify-content': 'center',
        background: 'var(--bg)',
        'z-index': '100',
      }}
    >
      <div style={{ width: '100%', 'max-width': '520px', padding: '2rem' }}>
        {/* Progress bar */}
        <div class="wizard-progress-bar" style={{ 'margin-bottom': '2rem' }}>
          <div class="fill" ref={progressFillRef} style={{ width: `${progress()}%` }} />
        </div>

        {/* Step label */}
        <div class="eyebrow" style={{ 'margin-bottom': '0.5rem' }}>
          Step {stepIndex() + 1} of {STEPS.length} — {STEP_LABELS[step()]}
        </div>

        {/* Step content */}
        <div ref={stepRef}>
          <Show when={step() === 'welcome'}>
            <h1 style={{ 'font-size': '2rem', 'margin-bottom': '1rem' }}>Welcome to Applyocalypse</h1>
            <p style={{ color: 'var(--text-secondary)', 'margin-bottom': '2rem' }}>
              Local-first job application automation. Your data stays on your machine.
              Set up once, apply everywhere.
            </p>
            <button class="primary-action" type="button" onClick={advance}>
              <ChevronRight size={18} aria-hidden="true" />
              <span>Get started</span>
            </button>
          </Show>

          <Show when={step() === 'upload'}>
            <h2 style={{ 'margin-bottom': '0.5rem' }}>Upload your resume</h2>
            <p style={{ color: 'var(--text-secondary)', 'margin-bottom': '2rem' }}>
              Supports PDF, DOCX, and TEX. This becomes your master template.
            </p>
            <Show
              when={profileState.uploadedFiles.length > 0}
              fallback={
                <button class="primary-action" type="button" onClick={() => void pickAndRegisterResume()}>
                  <Upload size={18} aria-hidden="true" />
                  <span>Browse or drop resume</span>
                </button>
              }
            >
              <div class="queue-row static-row" style={{ 'margin-bottom': '1rem' }}>
                <span>Uploaded</span>
                <strong>{profileState.uploadedFiles[0]?.originalName}</strong>
              </div>
              <button class="secondary-action" type="button" onClick={advance}>
                <ChevronRight size={17} aria-hidden="true" />
                <span>Continue</span>
              </button>
            </Show>
          </Show>

          <Show when={step() === 'parse-review'}>
            <h2 style={{ 'margin-bottom': '0.5rem' }}>Review parsed profile</h2>
            <Show
              when={profileState.canonicalProfile}
              fallback={<p style={{ color: 'var(--text-secondary)' }}>Parsing your resume…</p>}
            >
              {(canonical) => (
                <>
                  <div class="portal-workflow-grid" style={{ 'margin-bottom': '1.5rem' }}>
                    <span>Experience</span><strong>{canonical().experience.length}</strong>
                    <span>Education</span><strong>{canonical().education.length}</strong>
                    <span>Projects</span><strong>{canonical().projects.length}</strong>
                    <span>Skills groups</span><strong>{canonical().skillGroups.length}</strong>
                  </div>
                  <button class="primary-action" type="button" onClick={advance}>
                    <ChevronRight size={17} aria-hidden="true" />
                    <span>Looks good, continue</span>
                  </button>
                </>
              )}
            </Show>
          </Show>

          <Show when={step() === 'work-auth'}>
            <h2 style={{ 'margin-bottom': '0.5rem' }}>Work authorization</h2>
            <p style={{ color: 'var(--text-secondary)', 'margin-bottom': '1.5rem' }}>
              This is used to fill work authorization fields on job portals.
            </p>
            <label>
              <span>Summary (e.g. US Citizen, H1B, OPT)</span>
              <input
                value={form.workAuthSummary}
                onInput={(e) => setForm('workAuthSummary', e.currentTarget.value)}
                placeholder="Authorized to work in the US without sponsorship"
              />
            </label>
            <label class="toggle-row" style={{ 'margin-top': '1rem' }}>
              <input
                type="checkbox"
                checked={form.sponsorshipRequired}
                onChange={(e) => setForm('sponsorshipRequired', e.currentTarget.checked)}
              />
              <span>Require visa sponsorship</span>
            </label>
            <button class="secondary-action" type="button" style={{ 'margin-top': '1.5rem' }} onClick={advance}>
              <ChevronRight size={17} aria-hidden="true" />
              <span>Continue</span>
            </button>
          </Show>

          <Show when={step() === 'credentials'}>
            <h2 style={{ 'margin-bottom': '0.5rem' }}>Application credentials</h2>
            <p style={{ color: 'var(--text-secondary)', 'margin-bottom': '1.5rem' }}>
              The email and password used to log in to job portals. Stored locally, encrypted by Electron.
            </p>
            <label>
              <span>Legal name</span>
              <input value={form.legalName} onInput={(e) => setForm('legalName', e.currentTarget.value)} />
            </label>
            <label>
              <span>Application email</span>
              <input type="email" value={form.applicationEmail} autocomplete="username" onInput={(e) => setForm('applicationEmail', e.currentTarget.value)} />
            </label>
            <label>
              <span>Application password</span>
              <input type="password" value={form.applicationPassword} autocomplete="new-password" onInput={(e) => setForm('applicationPassword', e.currentTarget.value)} />
            </label>
            <p class="fine-print">12+ chars, uppercase, lowercase, number, symbol.</p>
            <label class="toggle-row">
              <input type="checkbox" checked={form.gmailOtpEnabled} onChange={(e) => setForm('gmailOtpEnabled', e.currentTarget.checked)} />
              <span>Use Gmail OTP extraction</span>
            </label>
            {profileState.error && <div class="error-box">{profileState.error}</div>}
            <button
              class="primary-action"
              type="button"
              style={{ 'margin-top': '1.5rem' }}
              disabled={!form.legalName.trim() || !form.applicationEmail.trim() || !applicationPasswordIsValid(form.applicationPassword)}
              onClick={() => void handleCreateProfile()}
            >
              <ShieldCheck size={17} aria-hidden="true" />
              <span>Save credentials</span>
            </button>
          </Show>

          <Show when={step() === 'provider'}>
            <h2 style={{ 'margin-bottom': '0.5rem' }}>LLM provider</h2>
            <p style={{ color: 'var(--text-secondary)', 'margin-bottom': '1.5rem' }}>
              Paste your API key. Used for resume tailoring and JD analysis.
            </p>
            <label>
              <span>Provider</span>
              <select value={form.provider} onChange={(e) => setForm('provider', e.currentTarget.value)}>
                <option value="openai">OpenAI</option>
                <option value="anthropic">Anthropic</option>
                <option value="gemini">Gemini</option>
                <option value="groq">Groq</option>
                <option value="openrouter">OpenRouter</option>
              </select>
            </label>
            <label>
              <span>API key</span>
              <input type="password" value={form.providerApiKey} autocomplete="off" onInput={(e) => setForm('providerApiKey', e.currentTarget.value)} />
            </label>
            <label>
              <span>Model (optional)</span>
              <input value={form.providerModel} placeholder="e.g. gpt-4o" onInput={(e) => setForm('providerModel', e.currentTarget.value)} />
            </label>
            <div style={{ display: 'flex', gap: '0.75rem', 'margin-top': '1.5rem' }}>
              <button
                class="primary-action"
                type="button"
                style={{ flex: '1' }}
                disabled={!form.providerApiKey.trim()}
                onClick={() => void handleSaveProvider()}
              >
                <ShieldCheck size={17} aria-hidden="true" />
                <span>Save key</span>
              </button>
              <button class="secondary-action" type="button" onClick={advance}>
                Skip
              </button>
            </div>
          </Show>

          <Show when={step() === 'done'}>
            <h2 style={{ 'margin-bottom': '0.5rem' }}>You're all set</h2>
            <p style={{ color: 'var(--text-secondary)', 'margin-bottom': '2rem' }}>
              Your profile is configured and ready. Head to Intake to add job links.
            </p>
            <button class="primary-action" type="button" onClick={handleComplete}>
              <ChevronRight size={18} aria-hidden="true" />
              <span>Go to Queue</span>
            </button>
          </Show>
        </div>

        {/* Back nav */}
        <Show when={stepIndex() > 0 && step() !== 'done'}>
          <button
            type="button"
            style={{ 'margin-top': '1.5rem', background: 'none', border: 'none', color: 'var(--muted)', cursor: 'pointer', 'font-size': '0.82rem' }}
            onClick={retreat}
          >
            ← Back
          </button>
        </Show>
      </div>
    </div>
  )
}
