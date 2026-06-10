import { For, Show, createEffect, createSignal } from 'solid-js'
import { createStore, produce } from 'solid-js/store'
import { KeyRound, Minus, Plus, Save, Settings, ShieldCheck, X } from 'lucide-solid'
import type { CanonicalProfile } from '@applyocalypse/shared-types'
import { useProfileStore } from '../contexts/ProfileStore'

const applicationPasswordIsValid = (v: string) =>
  /^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[^A-Za-z0-9]).{12,}$/.test(v)

// ── Local editable snapshot of structured canonical sections ─────────────────
type LocalExperience = { company: string; title: string; location: string; startDate: string; endDate: string; bullets: string[] }
type LocalProject    = { name: string; summary: string; bullets: string[]; tools: string[] }
type LocalEducation  = { institution: string; degree: string; field: string; startDate: string; endDate: string }
type LocalSkillGroup = { label: string; skills: string[] }

const fromCanonical = (c: CanonicalProfile | null) => ({
  experience: (c?.experience ?? []).map((e) => ({
    company: e.company, title: e.title,
    location: e.location ?? '', startDate: e.startDate ?? '', endDate: e.endDate ?? '',
    bullets: [...(e.bullets ?? [])],
  })) as LocalExperience[],
  education: (c?.education ?? []).map((e) => ({
    institution: e.institution ?? '', degree: e.degree ?? '',
    field: e.field ?? '', startDate: e.startDate ?? '', endDate: e.endDate ?? '',
  })) as LocalEducation[],
  projects: (c?.projects ?? []).map((p) => ({
    name: p.name, summary: p.summary ?? '',
    bullets: [...(p.bullets ?? [])],
    tools: [...(p.tools ?? [])],
  })) as LocalProject[],
  skillGroups: (c?.skillGroups ?? []).map((g) => ({
    label: g.label, skills: [...g.skills],
  })) as LocalSkillGroup[],
})

export default function ProfileScreen() {
  const { state, createStarterProfile, configureApplicationCredentials, saveProfile, saveStructuredSections } = useProfileStore()

  const [form, setForm] = createStore({
    legalName: '', email: '', location: '', applicationEmail: '', applicationPassword: '', gmailOtpEnabled: false,
    profileLegalName: '', profileDisplayName: '', profileEmail: '', profilePhone: '',
    profileLocation: '', profileWorkAuthorization: '',
    profileApplicationEmail: '', profileApplicationPassword: '', profileGmailOtpEnabled: false,
  })

  const [structured, setStructured] = createStore(fromCanonical(null))
  const [skillInput, setSkillInput] = createSignal<Record<number, string>>({})
  let hydratedProfileId = ''

  createEffect(() => {
    const profile = state.profile
    if (!profile || profile.id === hydratedProfileId) return
    hydratedProfileId = profile.id
    setForm({
      profileDisplayName: profile.displayName,
      profileLegalName: profile.legalName,
      profileEmail: profile.email ?? '',
      profilePhone: profile.phone ?? '',
      profileLocation: profile.location ?? '',
      profileWorkAuthorization: String(profile.workAuthorization['summary'] ?? ''),
      profileApplicationEmail: profile.applicationEmail ?? profile.email ?? '',
      profileApplicationPassword: '',
      profileGmailOtpEnabled: profile.otpHandlingEnabled,
    })
  })

  createEffect(() => {
    const canonical = state.canonicalProfile
    if (!canonical) return
    setStructured(fromCanonical(canonical))
  })

  const submitStarterProfile = () => {
    if (!applicationPasswordIsValid(form.applicationPassword)) return
    void createStarterProfile({
      legalName: form.legalName, email: form.email || null, location: form.location || null,
      applicationEmail: form.applicationEmail, applicationPassword: form.applicationPassword,
      gmailOtpEnabled: form.gmailOtpEnabled,
    })
    setForm('applicationPassword', '')
  }

  const submitProfileEdits = () => {
    if (!state.profile) return
    void saveProfile({
      ...state.profile,
      legalName: form.profileLegalName || state.profile.legalName,
      displayName: form.profileDisplayName || state.profile.displayName,
      email: form.profileEmail || null,
      phone: form.profilePhone || null,
      location: form.profileLocation || null,
      workAuthorization: {
        ...state.profile.workAuthorization,
        ...(form.profileWorkAuthorization ? { summary: form.profileWorkAuthorization } : {}),
      },
    })
  }

  const submitApplicationCredentials = () => {
    if (!state.profile || !applicationPasswordIsValid(form.profileApplicationPassword)) return
    void configureApplicationCredentials({
      profileId: state.profile.id,
      applicationEmail: form.profileApplicationEmail,
      applicationPassword: form.profileApplicationPassword,
      gmailOtpEnabled: form.profileGmailOtpEnabled,
    })
    setForm('profileApplicationPassword', '')
  }

  return (
    <section class="settings-panel surface-panel surface-panel-active" data-gsap="panel" data-view-panel>
      <Settings size={20} aria-hidden="true" />
      <div class="panel-kicker">Profile workspace</div>

      <Show
        when={state.profile}
        fallback={
          <div class="starter-profile">
            <h2>Create master profile</h2>
            <label><span>Legal name</span><input value={form.legalName} onInput={(e) => setForm('legalName', e.currentTarget.value)} /></label>
            <label><span>Email</span><input value={form.email} onInput={(e) => setForm('email', e.currentTarget.value)} /></label>
            <label><span>Application email</span><input type="email" value={form.applicationEmail} autocomplete="username" onInput={(e) => setForm('applicationEmail', e.currentTarget.value)} /></label>
            <label><span>Application password</span><input type="password" value={form.applicationPassword} autocomplete="new-password" onInput={(e) => setForm('applicationPassword', e.currentTarget.value)} /></label>
            <label class="toggle-row"><input type="checkbox" checked={form.gmailOtpEnabled} onChange={(e) => setForm('gmailOtpEnabled', e.currentTarget.checked)} /><span>Use Gmail OTP extraction</span></label>
            <p class="fine-print">Password policy: 12+ chars, uppercase, lowercase, number, symbol.</p>
            <label><span>Location</span><input value={form.location} onInput={(e) => setForm('location', e.currentTarget.value)} /></label>
            <button class="secondary-action" type="button" disabled={!form.legalName.trim() || !form.applicationEmail.trim() || !applicationPasswordIsValid(form.applicationPassword)} onClick={submitStarterProfile}>
              <ShieldCheck size={17} aria-hidden="true" /><span>Save profile</span>
            </button>
          </div>
        }
      >
        {/* ── Section 1: Identity ── */}
        <details open>
          <summary class="panel-kicker" style={{ cursor: 'pointer', 'margin-bottom': '0.75rem' }}>Identity</summary>
          <div class="starter-profile profile-editor">
            <label><span>Display name</span><input value={form.profileDisplayName} onInput={(e) => setForm('profileDisplayName', e.currentTarget.value)} /></label>
            <label><span>Legal name</span><input value={form.profileLegalName} onInput={(e) => setForm('profileLegalName', e.currentTarget.value)} /></label>
            <label><span>Email</span><input value={form.profileEmail} onInput={(e) => setForm('profileEmail', e.currentTarget.value)} /></label>
            <label><span>Phone</span><input value={form.profilePhone} onInput={(e) => setForm('profilePhone', e.currentTarget.value)} /></label>
            <label><span>Location</span><input value={form.profileLocation} onInput={(e) => setForm('profileLocation', e.currentTarget.value)} /></label>
            <label><span>Work authorization</span><input value={form.profileWorkAuthorization} onInput={(e) => setForm('profileWorkAuthorization', e.currentTarget.value)} /></label>
            <button class="secondary-action" type="button" onClick={submitProfileEdits}><Save size={17} aria-hidden="true" /><span>Save identity</span></button>
          </div>
        </details>

        {/* ── Section 2: Experience ── */}
        <details open>
          <summary class="panel-kicker" style={{ cursor: 'pointer', 'margin': '1rem 0 0.75rem' }}>
            Experience ({structured.experience.length})
          </summary>
          <For each={structured.experience}>
            {(entry, idx) => (
              <div class="structured-entry">
                <div class="structured-entry-header">
                  <div style={{ flex: 1 }}>
                    <input
                      class="entry-title-input"
                      value={entry.company}
                      placeholder="Company"
                      onInput={(e) => setStructured('experience', idx(), 'company', e.currentTarget.value)}
                    />
                    <input
                      class="entry-sub-input"
                      value={entry.title}
                      placeholder="Title"
                      onInput={(e) => setStructured('experience', idx(), 'title', e.currentTarget.value)}
                    />
                    <div style={{ display: 'flex', gap: '0.5rem' }}>
                      <input class="entry-date-input" value={entry.startDate} placeholder="Start" onInput={(e) => setStructured('experience', idx(), 'startDate', e.currentTarget.value)} />
                      <input class="entry-date-input" value={entry.endDate} placeholder="End" onInput={(e) => setStructured('experience', idx(), 'endDate', e.currentTarget.value)} />
                    </div>
                  </div>
                  <button class="icon-button" type="button" aria-label="Remove entry" onClick={() => setStructured('experience', produce((arr) => { arr.splice(idx(), 1) }))}><X size={14} /></button>
                </div>
                <div class="bullet-list">
                  <For each={entry.bullets}>
                    {(bullet, bIdx) => (
                      <div class="bullet-row">
                        <input
                          value={bullet}
                          placeholder="Bullet point"
                          onInput={(e) => setStructured('experience', idx(), 'bullets', bIdx(), e.currentTarget.value)}
                        />
                        <button class="icon-button" type="button" aria-label="Remove bullet" onClick={() => setStructured('experience', idx(), 'bullets', produce((arr) => { arr.splice(bIdx(), 1) }))}><Minus size={12} /></button>
                      </div>
                    )}
                  </For>
                  <button class="secondary-action small" type="button" onClick={() => setStructured('experience', idx(), 'bullets', produce((arr) => { arr.push('') }))}><Plus size={12} /><span>Add bullet</span></button>
                </div>
              </div>
            )}
          </For>
          <button class="secondary-action" type="button" style={{ 'margin-top': '0.5rem' }}
            onClick={() => setStructured('experience', produce((arr) => { arr.push({ company: '', title: '', location: '', startDate: '', endDate: '', bullets: [''] }) }))}>
            <Plus size={14} /><span>Add experience</span>
          </button>
        </details>

        {/* ── Section 3: Education ── */}
        <details>
          <summary class="panel-kicker" style={{ cursor: 'pointer', 'margin': '1rem 0 0.75rem' }}>
            Education ({structured.education.length})
          </summary>
          <For each={structured.education}>
            {(entry, idx) => (
              <div class="structured-entry">
                <div class="structured-entry-header">
                  <div style={{ flex: 1 }}>
                    <input class="entry-title-input" value={entry.institution} placeholder="Institution" onInput={(e) => setStructured('education', idx(), 'institution', e.currentTarget.value)} />
                    <input class="entry-sub-input" value={entry.degree} placeholder="Degree" onInput={(e) => setStructured('education', idx(), 'degree', e.currentTarget.value)} />
                    <input class="entry-sub-input" value={entry.field} placeholder="Field of study" onInput={(e) => setStructured('education', idx(), 'field', e.currentTarget.value)} />
                  </div>
                  <button class="icon-button" type="button" aria-label="Remove entry" onClick={() => setStructured('education', produce((arr) => { arr.splice(idx(), 1) }))}><X size={14} /></button>
                </div>
              </div>
            )}
          </For>
          <button class="secondary-action" type="button" style={{ 'margin-top': '0.5rem' }}
            onClick={() => setStructured('education', produce((arr) => { arr.push({ institution: '', degree: '', field: '', startDate: '', endDate: '' }) }))}>
            <Plus size={14} /><span>Add education</span>
          </button>
        </details>

        {/* ── Section 4: Projects ── */}
        <details>
          <summary class="panel-kicker" style={{ cursor: 'pointer', 'margin': '1rem 0 0.75rem' }}>
            Projects ({structured.projects.length})
          </summary>
          <For each={structured.projects}>
            {(entry, idx) => (
              <div class="structured-entry">
                <div class="structured-entry-header">
                  <div style={{ flex: 1 }}>
                    <input class="entry-title-input" value={entry.name} placeholder="Project name" onInput={(e) => setStructured('projects', idx(), 'name', e.currentTarget.value)} />
                    <input class="entry-sub-input" value={entry.summary} placeholder="Summary" onInput={(e) => setStructured('projects', idx(), 'summary', e.currentTarget.value)} />
                  </div>
                  <button class="icon-button" type="button" aria-label="Remove entry" onClick={() => setStructured('projects', produce((arr) => { arr.splice(idx(), 1) }))}><X size={14} /></button>
                </div>
                <div class="bullet-list">
                  <For each={entry.bullets}>
                    {(bullet, bIdx) => (
                      <div class="bullet-row">
                        <input value={bullet} placeholder="Bullet point" onInput={(e) => setStructured('projects', idx(), 'bullets', bIdx(), e.currentTarget.value)} />
                        <button class="icon-button" type="button" aria-label="Remove bullet" onClick={() => setStructured('projects', idx(), 'bullets', produce((arr) => { arr.splice(bIdx(), 1) }))}><Minus size={12} /></button>
                      </div>
                    )}
                  </For>
                  <button class="secondary-action small" type="button" onClick={() => setStructured('projects', idx(), 'bullets', produce((arr) => { arr.push('') }))}><Plus size={12} /><span>Add bullet</span></button>
                </div>
                <div class="tool-chips" style={{ 'margin-top': '0.5rem' }}>
                  <For each={entry.tools}>
                    {(tool, tIdx) => (
                      <span class="tool-chip">
                        {tool}
                        <button type="button" aria-label={`Remove ${tool}`} onClick={() => setStructured('projects', idx(), 'tools', produce((arr) => { arr.splice(tIdx(), 1) }))}><X size={10} /></button>
                      </span>
                    )}
                  </For>
                </div>
              </div>
            )}
          </For>
          <button class="secondary-action" type="button" style={{ 'margin-top': '0.5rem' }}
            onClick={() => setStructured('projects', produce((arr) => { arr.push({ name: '', summary: '', bullets: [''], tools: [] }) }))}>
            <Plus size={14} /><span>Add project</span>
          </button>
        </details>

        {/* ── Section 5: Skills ── */}
        <details>
          <summary class="panel-kicker" style={{ cursor: 'pointer', 'margin': '1rem 0 0.75rem' }}>
            Skills ({structured.skillGroups.reduce((sum, g) => sum + g.skills.length, 0)} skills)
          </summary>
          <For each={structured.skillGroups}>
            {(group, gIdx) => (
              <div class="structured-entry">
                <div class="structured-entry-header">
                  <input class="entry-title-input" style={{ flex: 1 }} value={group.label} placeholder="Category (e.g. Languages)" onInput={(e) => setStructured('skillGroups', gIdx(), 'label', e.currentTarget.value)} />
                  <button class="icon-button" type="button" aria-label="Remove group" onClick={() => setStructured('skillGroups', produce((arr) => { arr.splice(gIdx(), 1) }))}><X size={14} /></button>
                </div>
                <div class="tool-chips">
                  <For each={group.skills}>
                    {(skill, sIdx) => (
                      <span class="tool-chip">
                        {skill}
                        <button type="button" aria-label={`Remove ${skill}`} onClick={() => setStructured('skillGroups', gIdx(), 'skills', produce((arr) => { arr.splice(sIdx(), 1) }))}><X size={10} /></button>
                      </span>
                    )}
                  </For>
                  <input
                    class="chip-input"
                    value={skillInput()[gIdx()] ?? ''}
                    placeholder="Add skill, press Enter"
                    onInput={(e) => setSkillInput((s) => ({ ...s, [gIdx()]: e.currentTarget.value }))}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') {
                        const val = (skillInput()[gIdx()] ?? '').trim()
                        if (val) {
                          setStructured('skillGroups', gIdx(), 'skills', produce((arr) => { arr.push(val) }))
                          setSkillInput((s) => ({ ...s, [gIdx()]: '' }))
                        }
                        e.preventDefault()
                      }
                    }}
                  />
                </div>
              </div>
            )}
          </For>
          <button class="secondary-action" type="button" style={{ 'margin-top': '0.5rem' }}
            onClick={() => setStructured('skillGroups', produce((arr) => { arr.push({ label: '', skills: [] }) }))}>
            <Plus size={14} /><span>Add skill group</span>
          </button>
          <button
            class="secondary-action"
            type="button"
            style={{ 'margin-top': '1rem' }}
            disabled={!state.profile}
            onClick={() => {
              if (!state.profile) return
              void saveStructuredSections({
                profileId: state.profile.id,
                education: structured.education,
                experience: structured.experience,
                projects: structured.projects,
                skillGroups: structured.skillGroups,
              })
            }}
          >
            <Save size={17} aria-hidden="true" /><span>Save sections</span>
          </button>
        </details>

        {/* ── Section 6: Application credentials ── */}
        <details>
          <summary class="panel-kicker" style={{ cursor: 'pointer', 'margin': '1rem 0 0.75rem' }}>Application identity</summary>
          <div class="starter-profile credential-editor">
            <div style={{ display: 'flex', 'align-items': 'center', gap: '0.5rem', 'margin-bottom': '0.5rem' }}>
              <KeyRound size={16} aria-hidden="true" />
              <p class="fine-print" style={{ margin: 0 }}>
                Passwords are encrypted by Electron Main and never exposed back to the renderer.
                {state.profile?.applicationPasswordConfigured ? ' A password is configured.' : ' No password is configured.'}
              </p>
            </div>
            <label><span>Application email</span><input type="email" value={form.profileApplicationEmail} autocomplete="username" onInput={(e) => setForm('profileApplicationEmail', e.currentTarget.value)} /></label>
            <label><span>Application password</span><input type="password" value={form.profileApplicationPassword} autocomplete="new-password" onInput={(e) => setForm('profileApplicationPassword', e.currentTarget.value)} /></label>
            <label class="toggle-row"><input type="checkbox" checked={form.profileGmailOtpEnabled} onChange={(e) => setForm('profileGmailOtpEnabled', e.currentTarget.checked)} /><span>Use Gmail OTP extraction</span></label>
            <p class="fine-print">12+ chars, uppercase, lowercase, number, symbol.</p>
            <button class="secondary-action" type="button" disabled={!form.profileApplicationEmail.trim() || !applicationPasswordIsValid(form.profileApplicationPassword)} onClick={submitApplicationCredentials}>
              <ShieldCheck size={17} aria-hidden="true" /><span>Save application identity</span>
            </button>
          </div>
        </details>
      </Show>
    </section>
  )
}
