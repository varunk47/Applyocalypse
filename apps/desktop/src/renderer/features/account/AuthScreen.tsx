import { Show, createSignal } from 'solid-js'
import type { AccountResultDto } from '@applyocalypse/ipc-contracts'
import { setAccount } from './accountState'

type Mode = 'sign-in' | 'sign-up'

const PROMISES = [
  ['You approve every submit', 'Nothing is sent to an employer until you say so.'],
  ['Your files stay on this computer', 'The account only signs you in. Resumes, answers and history stay local.'],
  ['Tailored, never invented', 'Each resume is rewritten from what you have actually done.'],
] as const

const GoogleMark = () => (
  <svg width="18" height="18" viewBox="0 0 48 48" aria-hidden="true">
    <path fill="#FFC107" d="M43.6 20.5H42V20H24v8h11.3C33.7 32.7 29.2 36 24 36c-6.6 0-12-5.4-12-12s5.4-12 12-12c3.1 0 5.8 1.2 7.9 3.1l5.7-5.7C34 6.1 29.3 4 24 4 12.9 4 4 12.9 4 24s8.9 20 20 20 20-8.9 20-20c0-1.3-.1-2.4-.4-3.5z" />
    <path fill="#FF3D00" d="m6.3 14.7 6.6 4.8C14.7 15.1 19 12 24 12c3.1 0 5.8 1.2 7.9 3.1l5.7-5.7C34 6.1 29.3 4 24 4 16.3 4 9.7 8.3 6.3 14.7z" />
    <path fill="#4CAF50" d="M24 44c5.2 0 9.9-2 13.4-5.2l-6.2-5.2C29.2 35.1 26.7 36 24 36c-5.2 0-9.6-3.3-11.3-8l-6.5 5C9.5 39.6 16.2 44 24 44z" />
    <path fill="#1976D2" d="M43.6 20.5H42V20H24v8h11.3c-.8 2.2-2.2 4.2-4.1 5.6l6.2 5.2C37 39.2 44 34 44 24c0-1.3-.1-2.4-.4-3.5z" />
  </svg>
)

export const AuthScreen = () => {
  const [mode, setMode] = createSignal<Mode>('sign-in')
  const [email, setEmail] = createSignal('')
  const [password, setPassword] = createSignal('')
  const [busy, setBusy] = createSignal<'form' | 'google' | null>(null)
  const [notice, setNotice] = createSignal<{ tone: 'error' | 'info'; text: string } | null>(null)

  const settle = (result: AccountResultDto) => {
    if (result.signedIn) {
      setAccount({ signedIn: true, email: result.email })
      return
    }
    // Sign-up without a session means the confirmation email is on its way.
    const confirming = mode() === 'sign-up' && /confirm your email/i.test(result.message)
    setNotice({ tone: confirming ? 'info' : 'error', text: result.message })
    if (confirming) setMode('sign-in')
  }

  const run = async (kind: 'form' | 'google', call: () => Promise<AccountResultDto>) => {
    setBusy(kind)
    setNotice(null)
    try {
      settle(await call())
    } catch {
      setNotice({ tone: 'error', text: 'Could not reach the sign-in service. Check your connection and try again.' })
    } finally {
      setBusy(null)
    }
  }

  const submit = (event: SubmitEvent) => {
    event.preventDefault()
    const input = { email: email().trim(), password: password() }
    void run('form', () =>
      mode() === 'sign-in' ? window.applyocalypse.account.signIn(input) : window.applyocalypse.account.signUp(input)
    )
  }

  const switchMode = (next: Mode) => {
    setMode(next)
    setNotice(null)
  }

  return (
    <div class="auth-screen">
      <section class="auth-story" aria-labelledby="auth-story-title">
        <div class="auth-brand">
          <span class="auth-mark" aria-hidden="true">A</span>
          <span class="auth-word">Applyocalypse</span>
        </div>
        <h1 id="auth-story-title" class="auth-title">
          Apply with a co-pilot, <em>not an autopilot.</em>
        </h1>
        <ol class="auth-promises">
          {PROMISES.map(([title, body]) => (
            <li>
              <strong>{title}</strong>
              <span>{body}</span>
            </li>
          ))}
        </ol>
      </section>

      <section class="auth-sheet" aria-labelledby="auth-sheet-title">
        <header class="auth-sheet-head">
          <h2 id="auth-sheet-title">{mode() === 'sign-in' ? 'Welcome back' : 'Create your account'}</h2>
          <p>{mode() === 'sign-in' ? 'Sign in to pick up where you left off.' : 'One sign-in. Your data stays on this computer.'}</p>
        </header>
        <div class="auth-switch" role="tablist">
          <button type="button" role="tab" aria-selected={mode() === 'sign-in'} onClick={() => switchMode('sign-in')}>
            Sign in
          </button>
          <button type="button" role="tab" aria-selected={mode() === 'sign-up'} onClick={() => switchMode('sign-up')}>
            Create account
          </button>
        </div>

        <button
          type="button"
          class="auth-google"
          disabled={busy() !== null}
          onClick={() => void run('google', () => window.applyocalypse.account.signInWithGoogle())}
        >
          <GoogleMark />
          <span>{busy() === 'google' ? 'Finish in your browser…' : 'Continue with Google'}</span>
        </button>

        <div class="auth-or" aria-hidden="true">
          <span>or with email</span>
        </div>

        <form class="auth-form" onSubmit={submit}>
          <label>
            <span>Email</span>
            <input
              type="email"
              autocomplete="email"
              required
              maxLength={320}
              value={email()}
              onInput={(event) => setEmail(event.currentTarget.value)}
            />
          </label>
          <label>
            <span>Password</span>
            <input
              type="password"
              autocomplete={mode() === 'sign-in' ? 'current-password' : 'new-password'}
              required
              minLength={8}
              maxLength={128}
              value={password()}
              onInput={(event) => setPassword(event.currentTarget.value)}
            />
            <Show when={mode() === 'sign-up'}>
              <small>At least 8 characters.</small>
            </Show>
          </label>

          <Show when={notice()}>
            {(current) => (
              <p class="auth-notice" classList={{ error: current().tone === 'error' }} role="status">
                {current().text}
              </p>
            )}
          </Show>

          <button type="submit" class="btn-wax auth-submit" disabled={busy() !== null}>
            {busy() === 'form' ? 'One moment…' : mode() === 'sign-in' ? 'Sign in' : 'Create account'}
          </button>
        </form>
      </section>
    </div>
  )
}
