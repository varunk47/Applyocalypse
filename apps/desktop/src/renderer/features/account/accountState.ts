import { createSignal } from 'solid-js'
import type { AccountStateDto } from '@applyocalypse/ipc-contracts'

// Null until main reports the stored session, so the shell never flashes the sign-in screen.
const [account, setAccount] = createSignal<AccountStateDto | null>(null)

export { account, setAccount }

export const loadAccount = async (): Promise<void> => {
  setAccount(await window.applyocalypse.account.getState())
}

export const signOut = async (): Promise<void> => {
  setAccount(await window.applyocalypse.account.signOut())
}
