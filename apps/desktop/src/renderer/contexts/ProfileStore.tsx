import { createContext, useContext, type ParentProps } from 'solid-js'
import { createStore } from 'solid-js/store'
import type { CanonicalProfile, ParsedDocument, Profile, Screenshot, UploadedFile } from '@applyocalypse/shared-types'
import { useToast } from '../components/Toast'

type ProfileState = {
  profile: Profile | null
  canonicalProfile: CanonicalProfile | null
  uploadedFiles: UploadedFile[]
  parsedDocuments: ParsedDocument[]
  screenshots: Screenshot[]
  isLoading: boolean
  error: string | null
}

type ProfileStoreValue = {
  state: ProfileState
  createStarterProfile: (input: {
    legalName: string
    email?: string | null
    location?: string | null
    applicationEmail: string
    applicationPassword: string
    gmailOtpEnabled?: boolean
    workAuthorization?: { summary: string; sponsorshipRequired: boolean; status?: string }
  }) => Promise<void>
  configureApplicationCredentials: (input: {
    profileId: string
    applicationEmail: string
    applicationPassword: string
    gmailOtpEnabled?: boolean
  }) => Promise<void>
  saveStructuredSections: (input: {
    profileId: string
    education: Array<{ id?: string | null | undefined; institution: string; degree?: string | null | undefined; field?: string | null | undefined; gpa?: string | null | undefined; startDate?: string | null | undefined; endDate?: string | null | undefined; details?: string[] }>
    experience: Array<{ id?: string | null | undefined; company: string; title: string; location?: string | null | undefined; startDate?: string | null | undefined; endDate?: string | null | undefined; bullets?: string[]; tools?: string[] }>
    projects: Array<{ id?: string | null | undefined; name: string; role?: string | null | undefined; summary?: string | null | undefined; bullets?: string[]; tools?: string[]; links?: string[] }>
    skillGroups: Array<{ id?: string | null | undefined; label: string; skills?: string[] }>
  }) => Promise<void>
  saveProfile: (profile: Profile) => Promise<void>
  pickAndRegisterResume: () => Promise<void>
  pickAndRegisterSupportingDetails: () => Promise<void>
  pickAndRegisterCoverLetter: () => Promise<void>
  confirmEditableMaster: (uploadedFileId: string) => Promise<void>
  repairEditableMasterAnchors: (uploadedFileId: string) => Promise<void>
  openLocalPath: (localPath: string) => Promise<void>
  refreshProfile: () => Promise<void>
}

const ProfileContext = createContext<ProfileStoreValue>()

export const ProfileStoreProvider = (props: ParentProps) => {
  const toast = useToast()
  const [state, setState] = createStore<ProfileState>({
    profile: null,
    canonicalProfile: null,
    uploadedFiles: [],
    parsedDocuments: [],
    screenshots: [],
    isLoading: false,
    error: null,
  })

  const refreshCanonical = async (profileId?: string | null) => {
    const canonical = await window.applyocalypse.profile.getCanonical(profileId ?? undefined)
    setState('canonicalProfile', canonical)
  }

  const init = async () => {
    setState('isLoading', true)
    try {
      const [profile, canonical, uploads, parsedDocuments] = await Promise.all([
        window.applyocalypse.profile.get(),
        window.applyocalypse.profile.getCanonical(),
        window.applyocalypse.files.listUploads(null),
        window.applyocalypse.documents.listParsed({ profileId: null }),
      ])
      setState('profile', profile)
      setState('canonicalProfile', canonical)
      setState('uploadedFiles', uploads.items)
      setState('parsedDocuments', parsedDocuments.items)
      setState('error', null)
    } catch (error) {
      setState('error', error instanceof Error ? error.message : 'Unable to load profile')
    } finally {
      setState('isLoading', false)
    }
  }

  void init()

  const refreshProfile = async (): Promise<void> => {
    const profile = await window.applyocalypse.profile.get()
    setState('profile', profile)
    await refreshCanonical(profile?.id)
  }

  const createStarterProfile = async (input: {
    legalName: string
    email?: string | null
    location?: string | null
    applicationEmail: string
    applicationPassword: string
    gmailOtpEnabled?: boolean
    workAuthorization?: { summary: string; sponsorshipRequired: boolean; status?: string }
  }): Promise<void> => {
    setState('isLoading', true)
    try {
      const profile = await window.applyocalypse.profile.createStarter(input)
      setState('profile', profile)
      await refreshCanonical(profile.id)
      setState('error', null)
    } catch (error) {
      setState('error', error instanceof Error ? error.message : 'Unable to create profile')
    } finally {
      setState('isLoading', false)
    }
  }

  const configureApplicationCredentials = async (input: {
    profileId: string
    applicationEmail: string
    applicationPassword: string
    gmailOtpEnabled?: boolean
  }): Promise<void> => {
    setState('isLoading', true)
    try {
      const updated = await window.applyocalypse.profile.configureApplicationCredentials(input)
      setState('profile', updated)
      await refreshCanonical(updated.id)
      setState('error', null)
    } catch (error) {
      setState('error', error instanceof Error ? error.message : 'Unable to save application credentials')
    } finally {
      setState('isLoading', false)
    }
  }

  const saveStructuredSections = async (input: {
    profileId: string
    education: Array<{ id?: string | null | undefined; institution: string; degree?: string | null | undefined; field?: string | null | undefined; gpa?: string | null | undefined; startDate?: string | null | undefined; endDate?: string | null | undefined; details?: string[] }>
    experience: Array<{ id?: string | null | undefined; company: string; title: string; location?: string | null | undefined; startDate?: string | null | undefined; endDate?: string | null | undefined; bullets?: string[]; tools?: string[] }>
    projects: Array<{ id?: string | null | undefined; name: string; role?: string | null | undefined; summary?: string | null | undefined; bullets?: string[]; tools?: string[]; links?: string[] }>
    skillGroups: Array<{ id?: string | null | undefined; label: string; skills?: string[] }>
  }): Promise<void> => {
    setState('isLoading', true)
    try {
      const canonical = await window.applyocalypse.profile.updateStructured(input)
      if (canonical) setState('canonicalProfile', canonical)
      setState('error', null)
      toast.success('Sections saved')
    } catch (error) {
      const msg = error instanceof Error ? error.message : 'Unable to save sections'
      setState('error', msg)
      toast.error(msg)
    } finally {
      setState('isLoading', false)
    }
  }

  const saveProfile = async (profile: Profile): Promise<void> => {
    setState('isLoading', true)
    try {
      const updated = await window.applyocalypse.profile.update(profile)
      setState('profile', updated)
      await refreshCanonical(updated.id)
      setState('error', null)
      toast.success('Profile saved')
    } catch (error) {
      const msg = error instanceof Error ? error.message : 'Unable to save profile'
      setState('error', msg)
      toast.error(msg)
    } finally {
      setState('isLoading', false)
    }
  }

  const pickAndRegisterUpload = async (
    purpose: 'cover_letter' | 'supporting_details' | 'other',
    fileKind: 'COVER_LETTER' | 'SUPPORTING_DETAILS' | 'OTHER'
  ): Promise<void> => {
    setState('isLoading', true)
    try {
      const picked = await window.applyocalypse.files.pick(purpose)
      if (picked.canceled) return
      const localPath = picked.paths[0]
      if (!localPath) throw new Error('No source path returned from file picker')
      const registered = await window.applyocalypse.files.registerUpload({
        profileId: state.profile?.id ?? null,
        localPath,
        fileKind,
      })
      setState('uploadedFiles', (files) => [registered.uploadedFile, ...files])
      if (registered.parsing) {
        setState('parsedDocuments', (docs) => [registered.parsing!.parsedDocument, ...docs])
        if (registered.parsing.updatedProfile) setState('profile', registered.parsing.updatedProfile)
      }
      await refreshCanonical(state.profile?.id)
      setState('error', null)
    } catch (error) {
      setState('error', error instanceof Error ? error.message : 'Unable to register source material')
    } finally {
      setState('isLoading', false)
    }
  }

  const pickAndRegisterResume = async (): Promise<void> => {
    setState('isLoading', true)
    try {
      const picked = await window.applyocalypse.files.pick('resume')
      if (picked.canceled) return
      const localPath = picked.paths[0]
      if (!localPath) throw new Error('No resume path returned from file picker')
      const registered = await window.applyocalypse.documents.ingestResumeSource({
        profileId: state.profile?.id ?? null,
        localPath,
      })
      setState('uploadedFiles', (files) =>
        [registered.sourceFile, registered.editableMasterCandidate, ...files].filter((f): f is UploadedFile => Boolean(f))
      )
      if (registered.parsing) {
        setState('parsedDocuments', (docs) => [registered.parsing!.parsedDocument, ...docs])
        if (registered.parsing.updatedProfile) setState('profile', registered.parsing.updatedProfile)
      }
      await refreshCanonical(state.profile?.id)
      setState('error', null)
    } catch (error) {
      setState('error', error instanceof Error ? error.message : 'Unable to register resume')
    } finally {
      setState('isLoading', false)
    }
  }

  const pickAndRegisterSupportingDetails = async (): Promise<void> =>
    pickAndRegisterUpload('supporting_details', 'SUPPORTING_DETAILS')

  const pickAndRegisterCoverLetter = async (): Promise<void> =>
    pickAndRegisterUpload('cover_letter', 'COVER_LETTER')

  const confirmEditableMaster = async (uploadedFileId: string): Promise<void> => {
    setState('isLoading', true)
    try {
      const uploadedFile = await window.applyocalypse.documents.confirmEditableMaster(uploadedFileId)
      const [parsedDocuments, profile] = await Promise.all([
        window.applyocalypse.documents.listParsed({ uploadedFileId }),
        window.applyocalypse.profile.get(),
      ])
      setState('uploadedFiles', (files) => files.map((f) => (f.id === uploadedFile.id ? uploadedFile : f)))
      setState('parsedDocuments', (docs) => {
        const remaining = docs.filter((d) => d.uploadedFileId !== uploadedFileId)
        return [...parsedDocuments.items, ...remaining]
      })
      setState('profile', profile)
      await refreshCanonical(profile?.id)
      setState('error', null)
      toast.success('Resume confirmed as editable master')
    } catch (error) {
      const msg = error instanceof Error ? error.message : 'Unable to confirm editable master'
      setState('error', msg)
      toast.error(msg)
    } finally {
      setState('isLoading', false)
    }
  }

  const repairEditableMasterAnchors = async (uploadedFileId: string): Promise<void> => {
    setState('isLoading', true)
    try {
      const repaired = await window.applyocalypse.documents.repairEditableMasterAnchors(uploadedFileId)
      setState('uploadedFiles', (files) => [repaired.anchoredCandidate, ...files])
      if (repaired.parsing) {
        setState('parsedDocuments', (docs) => [repaired.parsing!.parsedDocument, ...docs])
      }
      await refreshCanonical(state.profile?.id)
      setState('error', null)
    } catch (error) {
      setState('error', error instanceof Error ? error.message : 'Unable to create anchor repair candidate')
    } finally {
      setState('isLoading', false)
    }
  }

  const openLocalPath = async (localPath: string): Promise<void> => {
    try {
      const result = await window.applyocalypse.files.openLocalPath(localPath)
      if (!result.opened) throw new Error('Operating system did not open the path')
      setState('error', null)
    } catch (error) {
      setState('error', error instanceof Error ? error.message : 'Unable to open local path')
    }
  }

  return (
    <ProfileContext.Provider
      value={{
        state,
        createStarterProfile,
        configureApplicationCredentials,
        saveStructuredSections,
        saveProfile,
        pickAndRegisterResume,
        pickAndRegisterSupportingDetails,
        pickAndRegisterCoverLetter,
        confirmEditableMaster,
        repairEditableMasterAnchors,
        openLocalPath,
        refreshProfile,
      }}
    >
      {props.children}
    </ProfileContext.Provider>
  )
}

export const useProfileStore = (): ProfileStoreValue => {
  const ctx = useContext(ProfileContext)
  if (!ctx) throw new Error('ProfileStoreProvider is missing')
  return ctx
}
