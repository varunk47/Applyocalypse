import type { ParentProps } from 'solid-js'
import { ToastProvider } from '../components/Toast'
import { SettingsStoreProvider } from './SettingsStore'
import { ProfileStoreProvider } from './ProfileStore'
import { QueueStoreProvider } from './QueueStore'
import { RunStoreProvider } from './RunStore'

export const AppProviders = (props: ParentProps) => (
  <ToastProvider>
    <SettingsStoreProvider>
      <ProfileStoreProvider>
        <QueueStoreProvider>
          <RunStoreProvider>
            {props.children}
          </RunStoreProvider>
        </QueueStoreProvider>
      </ProfileStoreProvider>
    </SettingsStoreProvider>
  </ToastProvider>
)
