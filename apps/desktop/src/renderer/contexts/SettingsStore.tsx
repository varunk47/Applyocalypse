import { createContext, createEffect, onCleanup, useContext, type ParentProps } from 'solid-js'
import { createStore } from 'solid-js/store'
import type { ProviderConnection, ThemePreference, ThemeState } from '@applyocalypse/shared-types'
import { useToast } from '../components/Toast'

type SettingsState = {
  theme: ThemeState
  settings: Record<string, unknown>
  providerConnections: ProviderConnection[]
  isLoading: boolean
  error: string | null
}

type SettingsStoreValue = {
  state: SettingsState
  setThemePreference: (preference: ThemePreference) => Promise<void>
  setMaxConcurrentApplications: (value: number) => Promise<void>
  chooseOutputDir: () => Promise<void>
  saveProviderApiKey: (input: {
    provider: ProviderConnection['provider']
    displayName: string
    apiKey: string
    metadata?: Record<string, unknown>
  }) => Promise<void>
}

const SettingsContext = createContext<SettingsStoreValue>()

const applyThemeToDocument = (theme: ThemeState): void => {
  document.documentElement.dataset.theme = theme.activeTheme
  document.documentElement.classList.toggle('dark', theme.activeTheme === 'dark')
}

export const SettingsStoreProvider = (props: ParentProps) => {
  const toast = useToast()
  const initialTheme = window.applyocalypse.theme.getInitialState()

  const [state, setState] = createStore<SettingsState>({
    theme: initialTheme,
    settings: {},
    providerConnections: [],
    isLoading: false,
    error: null,
  })

  createEffect(() => {
    applyThemeToDocument(state.theme)
  })

  const unsubscribeTheme = window.applyocalypse.theme.subscribe((theme) => {
    setState('theme', theme)
  })

  onCleanup(() => {
    unsubscribeTheme()
  })

  const init = async () => {
    setState('isLoading', true)
    try {
      const [settings, providers] = await Promise.all([
        window.applyocalypse.settings.get(),
        window.applyocalypse.providers.list(),
      ])
      setState('settings', settings)
      setState('providerConnections', providers.items)
      setState('error', null)
    } catch (error) {
      setState('error', error instanceof Error ? error.message : 'Unable to load settings')
    } finally {
      setState('isLoading', false)
    }
  }

  void init()

  const setThemePreference = async (preference: ThemePreference): Promise<void> => {
    setState('isLoading', true)
    try {
      const theme = await window.applyocalypse.theme.setPreference(preference)
      setState('theme', theme)
      setState('error', null)
    } catch (error) {
      const msg = error instanceof Error ? error.message : 'Unable to update theme'
      setState('error', msg)
      toast.error(msg)
    } finally {
      setState('isLoading', false)
    }
  }

  const chooseOutputDir = async (): Promise<void> => {
    setState('isLoading', true)
    try {
      const selected = await window.applyocalypse.folders.chooseOutputDir()
      if (selected.canceled || !selected.localPath) return
      const settings = await window.applyocalypse.settings.update({ 'files.outputDir': selected.localPath })
      setState('settings', settings)
      setState('error', null)
      toast.success('Output folder updated')
    } catch (error) {
      const msg = error instanceof Error ? error.message : 'Unable to choose output folder'
      setState('error', msg)
      toast.error(msg)
    } finally {
      setState('isLoading', false)
    }
  }

  const setMaxConcurrentApplications = async (value: number): Promise<void> => {
    setState('isLoading', true)
    try {
      const settings = await window.applyocalypse.settings.update({ 'automation.maxConcurrentApplications': value })
      setState('settings', settings)
      setState('error', null)
    } catch (error) {
      setState('error', error instanceof Error ? error.message : 'Unable to update automation concurrency')
    } finally {
      setState('isLoading', false)
    }
  }

  const saveProviderApiKey = async (input: {
    provider: ProviderConnection['provider']
    displayName: string
    apiKey: string
    metadata?: Record<string, unknown>
  }): Promise<void> => {
    if (!input.apiKey.trim()) {
      setState('error', 'Provider API key is required.')
      return
    }
    setState('isLoading', true)
    try {
      const connection = await window.applyocalypse.providers.saveApiKey({
        provider: input.provider,
        displayName: input.displayName,
        apiKey: input.apiKey,
        metadata: { ...(input.metadata ?? {}), configuredAt: new Date().toISOString() },
      })
      setState('providerConnections', (connections) => {
        const next = connections.filter((item) => item.provider !== connection.provider)
        return [connection, ...next].sort((a, b) => a.provider.localeCompare(b.provider))
      })
      setState('error', null)
      toast.success('API key stored securely')
    } catch (error) {
      const msg = error instanceof Error ? error.message : 'Unable to save provider key'
      setState('error', msg)
      toast.error(msg)
    } finally {
      setState('isLoading', false)
    }
  }

  return (
    <SettingsContext.Provider value={{ state, setThemePreference, setMaxConcurrentApplications, chooseOutputDir, saveProviderApiKey }}>
      {props.children}
    </SettingsContext.Provider>
  )
}

export const useSettingsStore = (): SettingsStoreValue => {
  const ctx = useContext(SettingsContext)
  if (!ctx) throw new Error('SettingsStoreProvider is missing')
  return ctx
}
