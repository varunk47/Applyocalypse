import { For, Show } from 'solid-js'
import {
  WORK_AUTHORIZATION_STATUSES,
  deriveWorkAuthorization,
  type SponsorshipNeed,
  type WorkAuthorizationStatus,
} from '@applyocalypse/shared-types'

export type WorkAuthFields = {
  workAuthStatus: WorkAuthorizationStatus | ''
  workAuthSponsorship: SponsorshipNeed | ''
}

type Props = {
  fields: WorkAuthFields
  setStatus: (value: WorkAuthorizationStatus | '') => void
  setSponsorship: (value: SponsorshipNeed | '') => void
}

const SPONSORSHIP_CHOICES: ReadonlyArray<{ id: SponsorshipNeed; label: string }> = [
  { id: 'NEVER', label: 'No, not now and not later' },
  { id: 'FUTURE', label: 'Not now, but I will later' },
  { id: 'NOW', label: 'Yes, I need it now' },
]

const statusOption = (status: WorkAuthorizationStatus | '') =>
  WORK_AUTHORIZATION_STATUSES.find((option) => option.id === status)

/**
 * The two questions a portal actually asks, asked once here.
 *
 * The preview is the point: the user sees which radio button gets clicked on
 * their behalf before any form is ever opened, rather than finding out from a
 * rejection weeks later.
 */
export function WorkAuthorizationFields(props: Props) {
  const needsExplicitSponsorship = () => {
    const option = statusOption(props.fields.workAuthStatus)
    return Boolean(option) && option?.defaultSponsorshipNeed === null
  }

  const answer = () =>
    props.fields.workAuthStatus
      ? deriveWorkAuthorization(props.fields.workAuthStatus, props.fields.workAuthSponsorship || null)
      : null

  return (
    <>
      <label class="form-field">
        <span>Your status</span>
        <select
          value={props.fields.workAuthStatus}
          onChange={(event) => {
            props.setStatus(event.currentTarget.value as WorkAuthorizationStatus | '')
            // The old answer belonged to the old status. Statuses that settle
            // it themselves get their own default back.
            props.setSponsorship('')
          }}
        >
          <option value="">Choose one</option>
          <For each={WORK_AUTHORIZATION_STATUSES}>
            {(option) => <option value={option.id}>{option.label}</option>}
          </For>
        </select>
      </label>

      <Show when={needsExplicitSponsorship()}>
        <label class="form-field">
          <span>Will you now or in the future require sponsorship?</span>
          <select
            value={props.fields.workAuthSponsorship}
            onChange={(event) =>
              props.setSponsorship(event.currentTarget.value as SponsorshipNeed | '')
            }
          >
            <option value="">Choose one</option>
            <For each={SPONSORSHIP_CHOICES}>{(choice) => <option value={choice.id}>{choice.label}</option>}</For>
          </select>
        </label>
      </Show>

      <Show when={answer()}>
        {(resolved) => (
          <div class="workauth-preview">
            <div class="workauth-preview-head">What portals will be told</div>
            <dl>
              <dt>Legally authorized to work in the US</dt>
              <dd>{resolved().authorizedInUs ? 'Yes' : 'No'}</dd>
              <dt>Requires sponsorship now or in the future</dt>
              <dd>{resolved().sponsorshipNeed === 'NEVER' ? 'No' : 'Yes'}</dd>
            </dl>
          </div>
        )}
      </Show>
    </>
  )
}
