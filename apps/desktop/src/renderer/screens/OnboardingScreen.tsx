import { For, Show, createEffect, createMemo, createSignal, on } from 'solid-js'
import { useNavigate } from '@solidjs/router'
import { createStore } from 'solid-js/store'
import { ArrowRight, Check } from 'lucide-solid'
import { useProfileStore } from '../contexts/ProfileStore'
import { useSettingsStore } from '../contexts/SettingsStore'
import { prefersReducedMotion } from '../animations/motion'
import { enterStepFromRight } from '../animations/screenTransition'
import { ResumeDrop } from '../features/onboarding/ResumeDrop'
import {
  ConfirmLedger,
  type EducationRow,
  type ExperienceRow,
  type IdentityFields,
} from '../features/onboarding/ConfirmLedger'
import { FinalDetails, type CredentialFields, type ProviderFields } from '../features/onboarding/FinalDetails'
import { deriveLegalName } from '../features/onboarding/onboardingUtils'
import { formatDateMMDDYYYY, parseDateMMDDYYYY, deriveFirstName, deriveLastName } from '@applyocalypse/shared-types'
import { EQUAL_EMPLOYMENT_SEED_DEFAULTS } from '@applyocalypse/shared-schemas'

/**
 * Onboarding is four moments, not thirteen steps: hand over a resume, confirm
 * what we read out of it, answer the handful of things a resume cannot say, go.
 */
type Moment = 'resume' | 'review' | 'details' | 'ready'

const MOMENTS: Moment[] = ['resume', 'review', 'details', 'ready']
const MOMENT_LABELS: Record<Moment, string> = {
  resume: 'Resume',
  review: 'Review',
  details: 'Details',
  ready: 'Ready',
}

const applicationPasswordIsValid = (value: string): boolean =>
  /^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[^A-Za-z0-9]).{12,}$/.test(value)

const emptyExperience = (): ExperienceRow => ({
  company: '',
  title: '',
  location: '',
  startDate: '',
  endDate: '',
  bullets: [],
})

const emptyEducation = (): EducationRow => ({
  institution: '',
  degree: '',
  field: '',
  gpa: '',
  startDate: '',
  endDate: '',
})

function OnboardingScreen() {
  const navigate = useNavigate()
  const { state: profileState, createStarterProfile, saveStructuredSections, saveProfile, pickAndRegisterResume } =
    useProfileStore()
  const { state: settingsState, saveProviderApiKey } = useSettingsStore()

  const [momentIndex, setMomentIndex] = createSignal(0)
  const [isSaving, setIsSaving] = createSignal(false)
  const [isPicking, setIsPicking] = createSignal(false)
  const [prefilled, setPrefilled] = createSignal(false)
  let stageRef: HTMLDivElement | undefined

  const [form, setForm] = createStore({
    legalName: '',

    // Identity and address, seeded from the resume then corrected in the ledger
    firstName: '',
    lastName: '',
    email: '',
    phone: '',
    linkedinUrl: '',
    githubUrl: '',
    addressLine1: '',
    addressLine2: '',
    city: '',
    state: '',
    postalCode: '',
    county: '',
    country: '',

    education: [] as EducationRow[],
    experience: [] as ExperienceRow[],

    // Equal employment defaults (seeded, always held for review before submission)
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

    workAuthSummary: '',
    sponsorshipRequired: false,

    applicationEmail: '',
    applicationPassword: '',
    gmailOtpEnabled: true,

    provider: 'openai',
    providerDisplayName: 'OpenAI',
    providerApiKey: '',
    providerModel: '',
  })

  const moment = (): Moment => MOMENTS[Math.min(momentIndex(), MOMENTS.length - 1)] as Moment
  const progressPct = () => `${(momentIndex() / (MOMENTS.length - 1)) * 100}%`

  const resumeFile = () => profileState.uploadedFiles.find((file) => file.fileKind === 'RESUME')
  const parsed = () => profileState.parsedDocuments[0] ?? null
  const canonical = createMemo(() => parsed()?.canonical ?? null)
  const isReading = () => Boolean(resumeFile()) && !parsed()

  const go = (next: Moment) => setMomentIndex(MOMENTS.indexOf(next))

  createEffect(
    on(momentIndex, () => {
      if (stageRef && !prefersReducedMotion()) enterStepFromRight(stageRef, () => {})
    }, { defer: true }),
  )

  /**
   * Seed the ledger from the parse the moment it lands. The parse is async, so
   * the user can already be sitting on the review screen when it arrives. Runs
   * once: after that the store holds the user's corrections, not the parser's
   * guesses, and re-seeding would throw them away.
   */
  createEffect(() => {
    const doc = canonical()
    if (!doc || prefilled()) return
    setPrefilled(true)

    const name = doc.identity.legalName ?? ''
    if (name) {
      setForm('firstName', deriveFirstName(name))
      setForm('lastName', deriveLastName(name))
    }
    if (doc.identity.email) setForm('email', doc.identity.email)
    if (doc.identity.phone) setForm('phone', doc.identity.phone)
    if (doc.identity.location) setForm('city', doc.identity.location)
    for (const link of doc.identity.links) {
      if (/linkedin/i.test(link.url) && !form.linkedinUrl) setForm('linkedinUrl', link.url)
      if (/github/i.test(link.url) && !form.githubUrl) setForm('githubUrl', link.url)
    }

    setForm(
      'experience',
      doc.experience.map((entry) => ({
        company: entry.company,
        title: entry.title,
        location: entry.location ?? '',
        startDate: formatDateMMDDYYYY(entry.startDate) ?? '',
        endDate: formatDateMMDDYYYY(entry.endDate) ?? '',
        bullets: entry.bullets,
      })),
    )
    setForm(
      'education',
      doc.education.map((entry) => ({
        institution: entry.institution,
        degree: entry.degree ?? '',
        field: entry.field ?? '',
        gpa: '',
        startDate: formatDateMMDDYYYY(entry.startDate) ?? '',
        endDate: formatDateMMDDYYYY(entry.endDate) ?? '',
      })),
    )
  })

  const startManualEntry = () => {
    setPrefilled(true)
    if (form.experience.length === 0) setForm('experience', [emptyExperience()])
    if (form.education.length === 0) setForm('education', [emptyEducation()])
    go('review')
  }

  const handleChooseResume = async () => {
    setIsPicking(true)
    try {
      await pickAndRegisterResume()
    } finally {
      setIsPicking(false)
    }
    if (profileState.uploadedFiles.some((file) => file.fileKind === 'RESUME')) go('review')
  }

  /**
   * One save for the whole tail. The provider key is saved last and separately:
   * it is optional, and a rejected key must not cost the user their profile.
   */
  const handleFinish = async () => {
    setIsSaving(true)
    try {
      await createStarterProfile({
        legalName: deriveLegalName(form.firstName, form.lastName, form.legalName),
        email: form.email || null,
        location: [form.city, form.state, form.country].filter(Boolean).join(', ') || null,
        applicationEmail: form.applicationEmail,
        applicationPassword: form.applicationPassword,
        gmailOtpEnabled: form.gmailOtpEnabled,
        workAuthorization: { summary: form.workAuthSummary, sponsorshipRequired: form.sponsorshipRequired },
      })
      if (profileState.error) return

      const profileId = profileState.profile?.id
      if (!profileId) return

      await saveStructuredSections({
        profileId,
        education: form.education
          .filter((entry) => entry.institution.trim())
          .map((entry) => ({
            institution: entry.institution,
            degree: entry.degree || null,
            field: entry.field || null,
            gpa: entry.gpa || null,
            startDate: parseDateMMDDYYYY(entry.startDate),
            endDate: parseDateMMDDYYYY(entry.endDate),
          })),
        experience: form.experience
          .filter((entry) => entry.company.trim() || entry.title.trim())
          .map((entry) => ({
            company: entry.company,
            title: entry.title,
            location: entry.location || null,
            startDate: parseDateMMDDYYYY(entry.startDate),
            endDate: parseDateMMDDYYYY(entry.endDate),
            bullets: entry.bullets,
          })),
        projects: (canonical()?.projects ?? []).map((entry) => ({
          name: entry.name,
          role: entry.role,
          summary: entry.summary,
          bullets: entry.bullets,
          tools: entry.tools,
          links: entry.links,
        })),
        skillGroups: (canonical()?.skillGroups ?? []).map((group) => ({
          label: group.label,
          skills: group.skills,
        })),
      })
      if (profileState.error) return

      const profile = profileState.profile
      if (profile) {
        await saveProfile({
          ...profile,
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
        if (profileState.error) return
      }

      if (form.providerApiKey.trim()) {
        await saveProviderApiKey({
          provider: form.provider as 'openai',
          displayName: form.providerDisplayName,
          apiKey: form.providerApiKey,
          ...(form.providerModel ? { metadata: { defaultModel: form.providerModel } } : {}),
        })
      }

      go('ready')
    } finally {
      setIsSaving(false)
    }
  }

  const identity = (): IdentityFields => ({
    firstName: form.firstName,
    lastName: form.lastName,
    email: form.email,
    phone: form.phone,
    linkedinUrl: form.linkedinUrl,
    githubUrl: form.githubUrl,
    addressLine1: form.addressLine1,
    addressLine2: form.addressLine2,
    city: form.city,
    state: form.state,
    postalCode: form.postalCode,
    county: form.county,
    country: form.country,
  })

  const credentials = (): CredentialFields => ({
    applicationEmail: form.applicationEmail,
    applicationPassword: form.applicationPassword,
    gmailOtpEnabled: form.gmailOtpEnabled,
  })

  const providerFields = (): ProviderFields => ({
    provider: form.provider,
    providerDisplayName: form.providerDisplayName,
    providerApiKey: form.providerApiKey,
    providerModel: form.providerModel,
  })

  return (
    <div class="onboarding-shell" data-gsap="panel" data-view-panel>
      <div class="ob-frame">
        <nav class="ob-rail" aria-label="Onboarding progress">
          <div class="ob-rail-head">
            <span class="ob-rail-count">
              {String(momentIndex() + 1).padStart(2, '0')}
              <em>/</em>
              {String(MOMENTS.length).padStart(2, '0')}
            </span>
            <span class="ob-rail-now">{MOMENT_LABELS[moment()]}</span>
          </div>
          <div
            class="wizard-progress-bar"
            role="progressbar"
            aria-valuemin={1}
            aria-valuemax={MOMENTS.length}
            aria-valuenow={momentIndex() + 1}
            aria-valuetext={`Step ${momentIndex() + 1} of ${MOMENTS.length}: ${MOMENT_LABELS[moment()]}`}
          >
            <div class="fill" style={{ width: progressPct() }} />
          </div>
          <ol class="ob-rail-stops">
            <For each={MOMENTS}>
              {(stop, index) => (
                <li
                  class="ob-rail-stop"
                  classList={{ done: index() < momentIndex(), active: index() === momentIndex() }}
                  aria-current={index() === momentIndex() ? 'step' : undefined}
                >
                  <Show when={index() < momentIndex()} fallback={<span class="ob-rail-num">{index() + 1}</span>}>
                    <Check size={11} aria-hidden="true" />
                  </Show>
                  <span>{MOMENT_LABELS[stop]}</span>
                </li>
              )}
            </For>
          </ol>
        </nav>

        <div ref={stageRef} class="ob-stage">
          <Show when={moment() === 'resume'}>
            <ResumeDrop
              fileName={resumeFile()?.originalName ?? null}
              isBusy={isPicking()}
              onChoose={() => void handleChooseResume()}
              onContinue={() => go('review')}
              onManual={startManualEntry}
            />
          </Show>

          <Show when={moment() === 'review'}>
            <ConfirmLedger
              fileName={resumeFile()?.originalName ?? null}
              isReading={isReading()}
              canonical={canonical()}
              identity={identity()}
              setIdentity={(key, value) => setForm(key, value)}
              education={form.education}
              setEducation={(index, key, value) => setForm('education', index, key, value)}
              addEducation={() => setForm('education', form.education.length, emptyEducation())}
              removeEducation={(index) =>
                setForm('education', (rows) => rows.filter((_, position) => position !== index))
              }
              experience={form.experience}
              setExperience={(index, key, value) => setForm('experience', index, key, value)}
              addExperience={() => setForm('experience', form.experience.length, emptyExperience())}
              removeExperience={(index) =>
                setForm('experience', (rows) => rows.filter((_, position) => position !== index))
              }
              onConfirm={() => go('details')}
            />
          </Show>

          <Show when={moment() === 'details'}>
            <FinalDetails
              workAuthSummary={form.workAuthSummary}
              setWorkAuthSummary={(value) => setForm('workAuthSummary', value)}
              sponsorshipRequired={form.sponsorshipRequired}
              setSponsorshipRequired={(value) => setForm('sponsorshipRequired', value)}
              eeo={{
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
              setEeoField={(key, value) => setForm(key as never, value as never)}
              credentials={credentials()}
              setCredential={(key, value) => setForm(key as never, value as never)}
              passwordIsValid={applicationPasswordIsValid(form.applicationPassword)}
              provider={providerFields()}
              setProviderField={(key, value) => setForm(key, value)}
              error={profileState.error ?? settingsState.error ?? null}
              isSaving={isSaving()}
              onFinish={() => void handleFinish()}
            />
          </Show>

          <Show when={moment() === 'ready'}>
            <div class="ob-hero">
              <p class="eyebrow">Profile complete</p>
              <h1 class="ob-hero-title">
                {form.firstName || 'You'} are ready
                <br />
                to apply.
              </h1>
              <p class="ob-hero-sub">
                {form.experience.length} role{form.experience.length === 1 ? '' : 's'} and{' '}
                {form.education.length} school{form.education.length === 1 ? '' : 's'} on file. Paste a job link in
                Intake and Applyocalypse tailors from here. Nothing is ever submitted without your approval.
              </p>
              <button class="primary-action ob-advance" type="button" onClick={() => navigate('/', { replace: true })}>
                <ArrowRight size={17} aria-hidden="true" />
                <span>Go to the queue</span>
              </button>
              <p class="fine-print">
                Have a cover letter you like the tone of? Add it any time under Documents to use it as a style
                reference.
              </p>
            </div>
          </Show>
        </div>

        <Show when={momentIndex() > 0 && moment() !== 'ready'}>
          <button class="ob-back" type="button" onClick={() => setMomentIndex((index) => index - 1)}>
            Back
          </button>
        </Show>
      </div>
    </div>
  )
}

export default OnboardingScreen
