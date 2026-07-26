import { For, Show, createSignal, onMount } from 'solid-js'
import { prefersReducedMotion } from '../animations/motion'
import { useNavigate } from '@solidjs/router'
import { createStore } from 'solid-js/store'
import { ChevronRight, ShieldCheck, Upload } from 'lucide-solid'
import { useProfileStore } from '../contexts/ProfileStore'
import { useSettingsStore } from '../contexts/SettingsStore'
import { gsap } from '../animations/gsap'
import { enterStepFromRight, exitStepToLeft } from '../animations/screenTransition'
import { PROVIDER_OPTIONS } from '../utils/providerOptions'
import { GeneralQuestionsStep } from '../features/onboarding/GeneralQuestionsStep'
import { EducationStep } from '../features/onboarding/EducationStep'
import { WorkExperienceStep } from '../features/onboarding/WorkExperienceStep'
import { EqualEmploymentStep } from '../features/onboarding/EqualEmploymentStep'
import { deriveLegalName } from '../features/onboarding/onboardingUtils'
import { formatDateMMDDYYYY, parseDateMMDDYYYY, deriveFirstName, deriveLastName } from '@applyocalypse/shared-types'
import { EQUAL_EMPLOYMENT_SEED_DEFAULTS } from '@applyocalypse/shared-schemas'

type OnboardingStep =
  | 'welcome'
  | 'upload'
  | 'upload-supporting'
  | 'upload-cover'
  | 'parse-review'
  | 'general-questions'
  | 'education'
  | 'work-experience'
  | 'equal-employment'
  | 'work-auth'
  | 'credentials'
  | 'provider'
  | 'done'

const STEPS: OnboardingStep[] = [
  'welcome', 'upload', 'upload-supporting', 'upload-cover', 'parse-review',
  'general-questions', 'education', 'work-experience', 'equal-employment',
  'work-auth', 'credentials', 'provider', 'done',
]

const STEP_LABELS: Record<OnboardingStep, string> = {
  'welcome':           'Welcome',
  'upload':            'Upload Resume',
  'upload-supporting': 'Supporting Details',
  'upload-cover':      'Cover Letter',
  'parse-review':      'Review Profile',
  'general-questions': 'Contact Info',
  'education':         'Education',
  'work-experience':   'Work Experience',
  'equal-employment':  'Equal Employment',
  'work-auth':         'Work Authorization',
  'credentials':       'App Credentials',
  'provider':          'LLM Provider',
  'done':              'Ready',
}

const applicationPasswordIsValid = (value: string): boolean =>
  /^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[^A-Za-z0-9]).{12,}$/.test(value)

export default function OnboardingScreen() {
  const {
    state: profileState,
    createStarterProfile,
    saveProfile,
    saveStructuredSections,
    pickAndRegisterResume,
    pickAndRegisterSupportingDetails,
    pickAndRegisterCoverLetter,
  } = useProfileStore()
  const { state: settingsState, saveProviderApiKey } = useSettingsStore()
  const navigate = useNavigate()

  const [stepIndex, setStepIndex] = createSignal(0)
  const [form, setForm] = createStore({
    // Credentials (required for profile creation)
    legalName: '',
    email: '',
    location: '',
    applicationEmail: '',
    applicationPassword: '',
    gmailOtpEnabled: false,

    // General questions
    firstName: '',
    lastName: '',
    phone: '',
    country: '',
    city: '',
    state: '',
    addressLine1: '',
    addressLine2: '',
    postalCode: '',
    county: '',
    linkedinUrl: '',
    githubUrl: '',

    // Education (prefilled from parsed resume on education step mount)
    education: [] as Array<{ institution: string; degree: string; field: string; gpa: string; startDate: string; endDate: string }>,

    // Work experience (prefilled from parsed resume on work-experience step mount)
    experience: [] as Array<{ company: string; title: string; location: string; startDate: string; endDate: string; bullets: string[] }>,

    // Equal employment defaults (seeded with owner's defaults)
    eeoAuthorizedToWorkUS: EQUAL_EMPLOYMENT_SEED_DEFAULTS.authorizedToWorkUS as string | null,
    eeoRequiresSponsorship: EQUAL_EMPLOYMENT_SEED_DEFAULTS.requiresSponsorship as string | null,
    eeoSponsorshipDetailText: EQUAL_EMPLOYMENT_SEED_DEFAULTS.sponsorshipDetailText ?? '',
    eeoDisability: EQUAL_EMPLOYMENT_SEED_DEFAULTS.disability as string | null,
    eeoGender: EQUAL_EMPLOYMENT_SEED_DEFAULTS.gender ?? '',
    eeoLgbtq: EQUAL_EMPLOYMENT_SEED_DEFAULTS.lgbtq as string | null,
    eeoVeteran: EQUAL_EMPLOYMENT_SEED_DEFAULTS.veteran as string | null,
    eeoRace: EQUAL_EMPLOYMENT_SEED_DEFAULTS.race ?? '',
    eeoHispanicOrLatino: EQUAL_EMPLOYMENT_SEED_DEFAULTS.hispanicOrLatino as string | null,
    eeoSexualOrientation: EQUAL_EMPLOYMENT_SEED_DEFAULTS.sexualOrientation as string[] | null,

    // Work authorization
    workAuthSummary: '',
    sponsorshipRequired: false,

    // Provider
    provider: 'openai',
    providerDisplayName: 'OpenAI',
    providerModel: '',
    providerApiKey: '',
  })

  let stepRef: HTMLDivElement | undefined
  let progressFillRef: HTMLDivElement | undefined

  const step = (): OnboardingStep => STEPS[Math.min(stepIndex(), STEPS.length - 1)] ?? 'welcome'
  const progressWidth = () => `${((stepIndex() + 1) / STEPS.length) * 100}%`

  // GSAP owns the fill width exclusively; a reactive style binding would jump the
  // DOM to the target before the tween starts and turn the animation into a no-op.
  const syncProgressBar = (animate: boolean) => {
    if (!progressFillRef) return
    if (animate && !prefersReducedMotion()) {
      gsap.to(progressFillRef, { width: progressWidth(), duration: 0.4, ease: 'power3.out' })
    } else {
      gsap.set(progressFillRef, { width: progressWidth() })
    }
  }

  onMount(() => {
    syncProgressBar(true)
  })

  const animateToStep = (direction: 'forward' | 'back') => {
    if (!stepRef || prefersReducedMotion()) return
    const outFn = direction === 'forward' ? exitStepToLeft : (el: Element, done: () => void) => {
      gsap.to(el, { x: 60, opacity: 0, duration: 0.18, ease: 'expo.in', onComplete: done })
    }
    const inFn = direction === 'forward' ? enterStepFromRight : (el: Element, done: () => void) => {
      gsap.fromTo(el, { x: -60, opacity: 0 }, { x: 0, opacity: 1, duration: 0.35, ease: 'expo.out', onComplete: done })
    }
    outFn(stepRef, () => { inFn(stepRef!, () => {}) })
  }

  const advance = () => {
    if (stepIndex() >= STEPS.length - 1) return
    animateToStep('forward')
    setStepIndex((i) => i + 1)
    syncProgressBar(true)
  }

  const retreat = () => {
    if (stepIndex() <= 0) return
    animateToStep('back')
    setStepIndex((i) => i - 1)
    syncProgressBar(true)
  }

  // Prefill general-questions from parsed resume canonical when entering that step
  const prefillGeneralFromParsed = () => {
    const canonical = profileState.parsedDocuments[0]?.canonical
    if (!canonical) return
    const name = canonical.identity.legalName ?? ''
    if (name && !form.firstName) {
      setForm('firstName', deriveFirstName(name))
      setForm('lastName', deriveLastName(name))
    }
    if (canonical.identity.email && !form.email) setForm('email', canonical.identity.email)
    if (canonical.identity.phone && !form.phone) setForm('phone', canonical.identity.phone)
    if (canonical.identity.location && !form.city) setForm('city', canonical.identity.location)
  }

  // Prefill education from parsed resume canonical
  const prefillEducation = () => {
    if (form.education.length > 0) return
    const entries = profileState.parsedDocuments[0]?.canonical.education ?? []
    setForm('education', entries.map((e) => ({
      institution: e.institution,
      degree: e.degree ?? '',
      field: e.field ?? '',
      gpa: '',
      startDate: formatDateMMDDYYYY(e.startDate) ?? '',
      endDate: formatDateMMDDYYYY(e.endDate) ?? '',
    })))
  }

  // Prefill work experience from parsed resume canonical
  const prefillExperience = () => {
    if (form.experience.length > 0) return
    const entries = profileState.parsedDocuments[0]?.canonical.experience ?? []
    setForm('experience', entries.map((e) => ({
      company: e.company,
      title: e.title,
      location: e.location ?? '',
      startDate: formatDateMMDDYYYY(e.startDate) ?? '',
      endDate: formatDateMMDDYYYY(e.endDate) ?? '',
      bullets: e.bullets ?? [],
    })))
  }

  const handleCreateProfile = async () => {
    const legalName = deriveLegalName(form.firstName, form.lastName, form.legalName)
    await createStarterProfile({
      legalName,
      email: form.email || null,
      location: [form.city, form.state, form.country].filter(Boolean).join(', ') || form.location || null,
      applicationEmail: form.applicationEmail,
      applicationPassword: form.applicationPassword,
      gmailOtpEnabled: form.gmailOtpEnabled,
      workAuthorization: { summary: form.workAuthSummary, sponsorshipRequired: form.sponsorshipRequired },
    })
    if (profileState.error) return
    const profileId = profileState.profile?.id
    if (profileId) {
      await saveStructuredSections({
        profileId,
        education: form.education.map((e) => ({
          institution: e.institution,
          degree: e.degree || null,
          field: e.field || null,
          gpa: e.gpa || null,
          startDate: parseDateMMDDYYYY(e.startDate),
          endDate: parseDateMMDDYYYY(e.endDate),
        })),
        experience: form.experience.map((e) => ({
          company: e.company,
          title: e.title,
          location: e.location || null,
          startDate: parseDateMMDDYYYY(e.startDate),
          endDate: parseDateMMDDYYYY(e.endDate),
          bullets: e.bullets,
        })),
        projects: [],
        skillGroups: [],
      })
      if (profileState.profile) {
        await saveProfile({
          ...profileState.profile,
          firstName: form.firstName || null,
          lastName: form.lastName || null,
          phone: form.phone || null,
          address: {
            country: form.country || null,
            city: form.city || null,
            state: form.state || null,
            addressLine1: form.addressLine1 || null,
            addressLine2: form.addressLine2 || null,
            postalCode: form.postalCode || null,
            county: form.county || null,
          },
          linkedinUrl: form.linkedinUrl || null,
          githubUrl: form.githubUrl || null,
          equalEmploymentDefaults: {
            authorizedToWorkUS: form.eeoAuthorizedToWorkUS as 'Yes' | 'No' | null,
            requiresSponsorship: form.eeoRequiresSponsorship as 'Yes' | 'No' | null,
            sponsorshipDetailText: form.eeoSponsorshipDetailText || null,
            disability: form.eeoDisability as 'Yes' | 'No' | 'Prefer not to say' | null,
            gender: form.eeoGender || null,
            lgbtq: form.eeoLgbtq as 'Yes' | 'No' | 'Prefer not to say' | null,
            veteran: form.eeoVeteran as 'Yes' | 'No' | 'Prefer not to say' | null,
            race: form.eeoRace || null,
            hispanicOrLatino: form.eeoHispanicOrLatino as 'Yes' | 'No' | null,
            sexualOrientation: form.eeoSexualOrientation,
            previouslyEmployedDefault: 'No',
            criminalRecordDefault: 'No',
          },
        })
      }
    }
    if (!profileState.error) advance()
  }

  const handleSaveProvider = async () => {
    await saveProviderApiKey({
      provider: form.provider as 'openai',
      displayName: form.providerDisplayName,
      apiKey: form.providerApiKey,
      ...(form.providerModel ? { metadata: { defaultModel: form.providerModel } } : {}),
    })
    // The store swallows save failures into state.error; never advance past a failed save.
    if (!settingsState.error) {
      advance()
    }
  }

  const handleComplete = () => navigate('/', { replace: true })

  const resumeFile = () => profileState.uploadedFiles.find((f) => f.fileKind === 'RESUME')
  const supportingFile = () => profileState.uploadedFiles.find((f) => f.fileKind === 'SUPPORTING_DETAILS')
  const coverFile = () => profileState.uploadedFiles.find((f) => f.fileKind === 'COVER_LETTER')

  return (
    <div class="onboarding-shell" style={{ position: 'fixed', inset: '44px 0 0 0', display: 'flex', 'align-items': 'center', 'justify-content': 'center', background: 'var(--bg)', 'z-index': '100' }}>
      <div style={{ width: '100%', 'max-width': '560px', padding: '2rem' }}>
        <div class="wizard-progress-bar" style={{ 'margin-bottom': '2rem' }}>
          <div class="fill" ref={progressFillRef} />
        </div>

        <div class="eyebrow" style={{ 'margin-bottom': '0.5rem' }}>
          Step {stepIndex() + 1} of {STEPS.length} — {STEP_LABELS[step()]}
        </div>

        <div ref={stepRef}>

          {/* ── Welcome ─────────────────────────────────────────────────────── */}
          <Show when={step() === 'welcome'}>
            <h1 style={{ 'font-size': '2rem', 'margin-bottom': '1rem' }}>Welcome to Applyocalypse</h1>
            <p style={{ color: 'var(--text-secondary)', 'margin-bottom': '2rem' }}>
              Local-first job application automation. Your data stays on your machine. Set up once, apply everywhere.
            </p>
            <button class="primary-action" type="button" onClick={advance}>
              <ChevronRight size={18} aria-hidden="true" />
              <span>Get started</span>
            </button>
          </Show>

          {/* ── Upload resume ────────────────────────────────────────────────── */}
          <Show when={step() === 'upload'}>
            <h2 style={{ 'margin-bottom': '0.5rem' }}>Upload your resume</h2>
            <p style={{ color: 'var(--text-secondary)', 'margin-bottom': '2rem' }}>
              Supports PDF, DOCX, and TEX. This becomes your master template.
            </p>
            <Show
              when={resumeFile()}
              fallback={
                <button class="primary-action" type="button" onClick={() => void pickAndRegisterResume()}>
                  <Upload size={18} aria-hidden="true" />
                  <span>Browse or drop resume</span>
                </button>
              }
            >
              {(file) => (
                <>
                  <div class="queue-row static-row" style={{ 'margin-bottom': '1rem' }}>
                    <span>Uploaded</span>
                    <strong>{file().originalName}</strong>
                  </div>
                  <button class="secondary-action" type="button" onClick={advance}>
                    <ChevronRight size={17} aria-hidden="true" />
                    <span>Continue</span>
                  </button>
                </>
              )}
            </Show>
          </Show>

          {/* ── Upload supporting details (optional) ─────────────────────────── */}
          <Show when={step() === 'upload-supporting'}>
            <h2 style={{ 'margin-bottom': '0.5rem' }}>Supporting details (optional)</h2>
            <p style={{ color: 'var(--text-secondary)', 'margin-bottom': '1.5rem' }}>
              Projects writeup, portfolio, or extra context. More detail means better-tailored bullets in your resume.
            </p>
            <Show when={supportingFile()}>
              {(file) => (
                <div class="queue-row static-row" style={{ 'margin-bottom': '1rem' }}>
                  <span>Uploaded</span>
                  <strong>{file().originalName}</strong>
                </div>
              )}
            </Show>
            <div style={{ display: 'flex', gap: '0.75rem' }}>
              <button class="secondary-action" type="button" onClick={() => void pickAndRegisterSupportingDetails()}>
                <Upload size={16} aria-hidden="true" />
                <span>{supportingFile() ? 'Replace' : 'Upload'}</span>
              </button>
              <button class="secondary-action" type="button" onClick={advance}>
                {supportingFile() ? 'Continue' : 'Skip'}
              </button>
            </div>
          </Show>

          {/* ── Upload sample cover letter (optional) ────────────────────────── */}
          <Show when={step() === 'upload-cover'}>
            <h2 style={{ 'margin-bottom': '0.5rem' }}>Sample cover letter (optional)</h2>
            <p style={{ color: 'var(--text-secondary)', 'margin-bottom': '1.5rem' }}>
              Upload a cover letter you have written. It will be used as a style reference. Without one, a generic template is used.
            </p>
            <Show when={coverFile()}>
              {(file) => (
                <div class="queue-row static-row" style={{ 'margin-bottom': '1rem' }}>
                  <span>Uploaded</span>
                  <strong>{file().originalName}</strong>
                </div>
              )}
            </Show>
            <div style={{ display: 'flex', gap: '0.75rem' }}>
              <button class="secondary-action" type="button" onClick={() => void pickAndRegisterCoverLetter()}>
                <Upload size={16} aria-hidden="true" />
                <span>{coverFile() ? 'Replace' : 'Upload'}</span>
              </button>
              <button class="secondary-action" type="button" onClick={advance}>
                {coverFile() ? 'Continue' : 'Skip'}
              </button>
            </div>
          </Show>

          {/* ── Parse review ─────────────────────────────────────────────────── */}
          <Show when={step() === 'parse-review'}>
            <h2 style={{ 'margin-bottom': '0.5rem' }}>Review parsed profile</h2>
            <Show
              when={profileState.parsedDocuments[0]}
              fallback={<p style={{ color: 'var(--text-secondary)' }}>Parsing your resume…</p>}
            >
              {(doc) => (
                <>
                  <div class="portal-workflow-grid" style={{ 'margin-bottom': '1.5rem' }}>
                    <span>Experience</span><strong>{doc().canonical.experience.length}</strong>
                    <span>Education</span><strong>{doc().canonical.education.length}</strong>
                    <span>Projects</span><strong>{doc().canonical.projects.length}</strong>
                    <span>Skill groups</span><strong>{doc().canonical.skillGroups.length}</strong>
                  </div>
                  <button class="primary-action" type="button" onClick={() => { prefillGeneralFromParsed(); advance() }}>
                    <ChevronRight size={17} aria-hidden="true" />
                    <span>Looks good, continue</span>
                  </button>
                </>
              )}
            </Show>
          </Show>

          {/* ── General questions ────────────────────────────────────────────── */}
          <Show when={step() === 'general-questions'}>
            <GeneralQuestionsStep
              fields={{
                firstName: form.firstName, lastName: form.lastName, email: form.email, phone: form.phone,
                country: form.country, city: form.city, state: form.state,
                addressLine1: form.addressLine1, addressLine2: form.addressLine2,
                postalCode: form.postalCode, county: form.county,
                linkedinUrl: form.linkedinUrl, githubUrl: form.githubUrl,
              }}
              setField={(k, v) => setForm(k as never, v as never)}
              onNext={advance}
            />
          </Show>

          {/* ── Education ────────────────────────────────────────────────────── */}
          <Show when={step() === 'education'}>
            {(() => { prefillEducation(); return null })()}
            <EducationStep
              entries={form.education}
              setEntry={(idx, key, value) => setForm('education', idx, key, value)}
              onNext={advance}
            />
          </Show>

          {/* ── Work experience ──────────────────────────────────────────────── */}
          <Show when={step() === 'work-experience'}>
            {(() => { prefillExperience(); return null })()}
            <WorkExperienceStep
              entries={form.experience}
              setEntry={(idx, key, value) => setForm('experience', idx, key, value as never)}
              onNext={advance}
            />
          </Show>

          {/* ── Equal employment ─────────────────────────────────────────────── */}
          <Show when={step() === 'equal-employment'}>
            <EqualEmploymentStep
              fields={{
                eeoAuthorizedToWorkUS: form.eeoAuthorizedToWorkUS,
                eeoRequiresSponsorship: form.eeoRequiresSponsorship,
                eeoSponsorshipDetailText: form.eeoSponsorshipDetailText,
                eeoDisability: form.eeoDisability,
                eeoGender: form.eeoGender,
                eeoLgbtq: form.eeoLgbtq,
                eeoVeteran: form.eeoVeteran,
                eeoRace: form.eeoRace,
                eeoHispanicOrLatino: form.eeoHispanicOrLatino,
                eeoSexualOrientation: form.eeoSexualOrientation,
              }}
              setField={(k, v) => setForm(k as never, v as never)}
              onNext={advance}
            />
          </Show>

          {/* ── Work authorization ───────────────────────────────────────────── */}
          <Show when={step() === 'work-auth'}>
            <h2 style={{ 'margin-bottom': '0.5rem' }}>Work authorization</h2>
            <p style={{ color: 'var(--text-secondary)', 'margin-bottom': '1.5rem' }}>
              Used to fill work authorization fields on job portals.
            </p>
            <label>
              <span>Summary (e.g. US Citizen, H1B, OPT)</span>
              <input value={form.workAuthSummary} onInput={(e) => setForm('workAuthSummary', e.currentTarget.value)} placeholder="Authorized to work in the US without sponsorship" />
            </label>
            <label class="toggle-row" style={{ 'margin-top': '1rem' }}>
              <input type="checkbox" checked={form.sponsorshipRequired} onChange={(e) => setForm('sponsorshipRequired', e.currentTarget.checked)} />
              <span>Require visa sponsorship</span>
            </label>
            <button class="secondary-action" type="button" style={{ 'margin-top': '1.5rem' }} onClick={advance}>
              <ChevronRight size={17} aria-hidden="true" />
              <span>Continue</span>
            </button>
          </Show>

          {/* ── Credentials ──────────────────────────────────────────────────── */}
          <Show when={step() === 'credentials'}>
            <h2 style={{ 'margin-bottom': '0.5rem' }}>Application credentials</h2>
            <p style={{ color: 'var(--text-secondary)', 'margin-bottom': '1.5rem' }}>
              The email and password used to log in to job portals. Stored locally, encrypted by Electron.
            </p>
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
              disabled={!form.applicationEmail.trim() || !applicationPasswordIsValid(form.applicationPassword)}
              onClick={() => void handleCreateProfile()}
            >
              <ShieldCheck size={17} aria-hidden="true" />
              <span>Create profile</span>
            </button>
          </Show>

          {/* ── Provider ─────────────────────────────────────────────────────── */}
          <Show when={step() === 'provider'}>
            <h2 style={{ 'margin-bottom': '0.5rem' }}>LLM provider</h2>
            <p style={{ color: 'var(--text-secondary)', 'margin-bottom': '1.5rem' }}>
              Paste your API key. Used for resume tailoring and JD analysis.
            </p>
            <label>
              <span>Provider</span>
              <select value={form.provider} onChange={(e) => {
                const p = e.currentTarget.value
                setForm('provider', p)
                setForm('providerDisplayName', PROVIDER_OPTIONS.find((o) => o.value === p)?.label ?? p)
              }}>
                <For each={PROVIDER_OPTIONS}>
                  {(p) => <option value={p.value}>{p.label}</option>}
                </For>
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
              <button class="primary-action" type="button" style={{ flex: '1' }} disabled={!form.providerApiKey.trim()} onClick={() => void handleSaveProvider()}>
                <ShieldCheck size={17} aria-hidden="true" />
                <span>Save key</span>
              </button>
              <button class="secondary-action" type="button" onClick={advance}>Skip</button>
            </div>
          </Show>

          {/* ── Done ─────────────────────────────────────────────────────────── */}
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

        <Show when={stepIndex() > 0 && step() !== 'done'}>
          <button type="button" style={{ 'margin-top': '1.5rem', background: 'none', border: 'none', color: 'var(--muted)', cursor: 'pointer', 'font-size': '0.82rem' }} onClick={retreat}>
            Back
          </button>
        </Show>
      </div>
    </div>
  )
}
