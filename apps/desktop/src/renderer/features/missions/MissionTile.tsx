import { For, Show } from 'solid-js'
import { PenLine } from 'lucide-solid'
import type { JobTarget } from '@applyocalypse/shared-types'
import { runStage, runTone, STAGES } from './runTone'

type MissionTileProps = {
  status: string
  target: JobTarget | undefined
  fallbackName: string
  hero?: boolean
  completedAt?: string | null
  delay?: number
  onOpen?: () => void
}

const STATE_TEXT: Record<string, string> = {
  READY_TO_SUBMIT: 'Ready for your signature',
  READY_FOR_REVIEW: 'Documents ready for your review',
  WAITING_FOR_USER_EDIT: 'Waiting on your edit',
  BLOCKED_OTP: 'Needs a code from your email',
  BLOCKED_CAPTCHA: 'Needs a human check',
  BLOCKED_MFA: 'Needs a sign-in approval',
  BLOCKED_AMBIGUOUS_QUESTION: 'A question needs your answer',
  PAUSED: 'Paused, pick it up any time',
  CLAIMED: 'Getting ready',
  PREPARING: 'Getting ready',
  PARSING_JD: 'Reading the posting',
  ANALYZING: 'Checking the fit',
  TAILORING_RESUME: 'Tailoring your resume',
  GENERATING_COVER_LETTER: 'Writing your cover letter',
  RUNNING_AUTOMATION: 'Filling the portal',
  PENDING: 'Queued, starts when a worker frees up',
}

const ACTION_TEXT: Record<string, string> = {
  READY_FOR_REVIEW: 'Review documents',
  WAITING_FOR_USER_EDIT: 'Review documents',
  BLOCKED_OTP: 'Enter the code',
  BLOCKED_CAPTCHA: 'Open the portal',
  BLOCKED_MFA: 'Open the portal',
  BLOCKED_AMBIGUOUS_QUESTION: 'Answer it',
  PAUSED: 'Open run',
}

const sentTime = (iso: string | null | undefined): string => {
  if (!iso) return 'Sent'
  const date = new Date(iso)
  const time = date.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' })
  return new Date().toDateString() === date.toDateString() ? `Sent today at ${time}` : `Sent ${date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}`
}

const portalOf = (target: JobTarget | undefined): string | null => {
  if (!target) return null
  if (target.portal) return target.portal
  if (target.sourceKind !== 'URL') return null
  try {
    return new URL(target.sourceValue).hostname.replace(/^www\./, '')
  } catch {
    return null
  }
}

/** One job on Missions. Its colour is its state, so a finished run visibly turns gold. */
export const MissionTile = (props: MissionTileProps) => {
  const tone = () => runTone(props.status)
  const stage = () => runStage(props.status)
  const company = () => props.target?.company ?? null
  const title = () => props.target?.role ?? props.target?.company ?? props.fallbackName
  const who = () => [company() && props.target?.role ? company() : null, portalOf(props.target)].filter(Boolean).join(' · ')
  const initial = () => (company() ?? title()).charAt(0).toUpperCase()
  const showTrack = () => tone() === 'sign' || tone() === 'needs' || tone() === 'working'

  return (
    <article
      class={`tile tone-${tone()}`}
      classList={{ hero: props.hero, clickable: !!props.onOpen }}
      style={{ 'animation-delay': `${props.delay ?? 0}ms` }}
      onClick={() => props.onOpen?.()}
    >
      <div class="tile-who">
        <span class="tile-logo" aria-hidden="true">{initial()}</span>
        <span>{who() || 'Job'}</span>
      </div>
      <h3 class="tile-role">
        <Show when={props.onOpen} fallback={title()}>
          <button class="tile-open" type="button" onClick={(event) => { event.stopPropagation(); props.onOpen?.() }}>
            {title()}
          </button>
        </Show>
      </h3>
      <div class="tile-state">{tone() === 'sent' ? sentTime(props.completedAt) : (STATE_TEXT[props.status] ?? 'Working')}</div>
      <Show when={showTrack()}>
        <div class="stage-track" role="img" aria-label={`Stage ${Math.min(stage().done + 1, STAGES.length)} of ${STAGES.length}: ${STAGES[stage().current ?? stage().done] ?? 'Sent'}`}>
          <For each={STAGES}>
            {(_, index) => (
              <i classList={{ done: index() < stage().done, current: index() === stage().current && tone() === 'working' }} />
            )}
          </For>
        </div>
        <Show when={props.hero}>
          <div class="stage-labels" aria-hidden="true">
            <For each={STAGES}>{(name, index) => <span classList={{ on: index() === stage().current }}>{name}</span>}</For>
          </div>
        </Show>
      </Show>
      <Show when={props.status === 'READY_TO_SUBMIT' && props.onOpen}>
        <button class="btn-sign" type="button" onClick={(event) => { event.stopPropagation(); props.onOpen?.() }}>
          <PenLine size={16} aria-hidden="true" />
          Review &amp; sign
        </button>
      </Show>
      <Show when={ACTION_TEXT[props.status] && props.onOpen}>
        <button class="tile-action" type="button" onClick={(event) => { event.stopPropagation(); props.onOpen?.() }}>
          {ACTION_TEXT[props.status]}
        </button>
      </Show>
    </article>
  )
}
