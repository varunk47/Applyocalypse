import { For, Show, createSignal } from 'solid-js'
import { createStore } from 'solid-js/store'
import { Lock } from 'lucide-solid'
import type { JobFilterDto } from '@applyocalypse/ipc-contracts'
import { useProfileStore } from '../../contexts/ProfileStore'
import { forgetPreference, loadPreferences, preferenceState, type SavedRef } from '../../contexts/PreferenceStore'
import { ARRANGEMENT_LABELS, FILTER_KIND_LABELS, describeAddress, describeConditions, describeFilter } from './preferenceText'

type FilterKind = JobFilterDto['kind']
const FILTER_KINDS = Object.keys(FILTER_KIND_LABELS) as FilterKind[]
const FILTER_PLACEHOLDERS: Record<FilterKind, string> = {
  skip_company: 'Initech',
  skip_keyword: 'clearance',
  min_salary: '120000',
  work_arrangement: '',
  place: 'Denver',
}
const EMPTY_ADDRESS = { label: '', addressLine1: '', city: '', state: '', postalCode: '', country: '' }

/** Settings pane listing everything the chat or the user asked the app to remember. */
export const RememberedSettings = () => {
  const { state: profileState } = useProfileStore()
  const [error, setError] = createSignal<string | null>(null)
  const [rule, setRule] = createStore({ question: '', answer: '' })
  const [filter, setFilter] = createStore({ kind: 'skip_company' as FilterKind, value: '' })
  const [address, setAddress] = createStore({ ...EMPTY_ADDRESS })

  const profileId = () => profileState.profile?.id ?? null

  const run = async (action: (id: string) => Promise<unknown>, after?: () => void) => {
    const id = profileId()
    if (!id) return
    setError(null)
    try {
      await action(id)
      after?.()
      await loadPreferences(id)
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'That change did not save.')
    }
  }

  const forget = (ref: SavedRef) => void run((id) => forgetPreference(id, ref))

  const addRule = () =>
    void run(
      (profileId) => window.applyocalypse.preferenceRules.upsert({ profileId, question: rule.question.trim(), answer: rule.answer.trim() }),
      () => setRule({ question: '', answer: '' })
    )

  const addFilter = () =>
    void run(
      (profileId) => window.applyocalypse.jobFilters.upsert({ profileId, kind: filter.kind, value: filter.value.trim() }),
      () => setFilter('value', '')
    )

  const addAddress = () =>
    void run(
      (profileId) => window.applyocalypse.profileAddresses.upsert({ profileId, ...address }),
      () => setAddress({ ...EMPTY_ADDRESS })
    )

  return (
    <div class="remembered">
      <section class="settings-block">
        <div class="settings-block-head">
          <div class="panel-kicker">Before anything is sent</div>
          <p class="settings-block-note">
            <Lock size={13} aria-hidden="true" /> Filters and answers here never submit anything. Only your own click, or Submit automatically under Applying, does.
          </p>
        </div>
      </section>

      <Show when={error()}>
        <p class="remembered-error" role="alert">{error()}</p>
      </Show>

      <section class="settings-block">
        <div class="settings-block-head">
          <div class="panel-kicker">Jobs to skip</div>
          <p class="settings-block-note">A run that breaks one of these stops before any document is written.</p>
        </div>
        <ul class="remembered-list">
          <For each={preferenceState.filters} fallback={<li class="remembered-empty">No filters yet. Every job is fair game.</li>}>
            {(item) => (
              <li>
                <div>
                  <strong>{describeFilter(item.kind, item.value)}</strong>
                  <span>{FILTER_KIND_LABELS[item.kind]}</span>
                </div>
                <button class="btn-mono" type="button" onClick={() => forget({ type: 'job_filter', id: item.id })}>
                  Forget
                </button>
              </li>
            )}
          </For>
        </ul>
        <form class="remembered-add" onSubmit={(event) => (event.preventDefault(), addFilter())}>
          <select value={filter.kind} onChange={(event) => setFilter({ kind: event.currentTarget.value as FilterKind, value: '' })} aria-label="Filter type">
            <For each={FILTER_KINDS}>{(kind) => <option value={kind}>{FILTER_KIND_LABELS[kind]}</option>}</For>
          </select>
          <Show
            when={filter.kind === 'work_arrangement'}
            fallback={
              <input
                value={filter.value}
                placeholder={FILTER_PLACEHOLDERS[filter.kind]}
                inputMode={filter.kind === 'min_salary' ? 'numeric' : 'text'}
                onInput={(event) => setFilter('value', event.currentTarget.value)}
                aria-label="Filter value"
              />
            }
          >
            <select value={filter.value} onChange={(event) => setFilter('value', event.currentTarget.value)} aria-label="Arrangement">
              <option value="">Pick one</option>
              <For each={Object.entries(ARRANGEMENT_LABELS)}>{([value, label]) => <option value={value}>{label}</option>}</For>
            </select>
          </Show>
          <button class="btn-outline-wax" type="submit" disabled={!filter.value.trim()}>
            Add
          </button>
        </form>
      </section>

      <section class="settings-block">
        <div class="settings-block-head">
          <div class="panel-kicker">Answers</div>
          <p class="settings-block-note">Used when a form asks a question your profile does not cover.</p>
        </div>
        <ul class="remembered-list">
          <For each={preferenceState.rules} fallback={<li class="remembered-empty">No saved answers yet.</li>}>
            {(item) => (
              <li>
                <div>
                  <strong>
                    {item.question}: {item.answer}
                  </strong>
                  <span>{describeConditions(item.conditions)}</span>
                </div>
                <button class="btn-mono" type="button" onClick={() => forget({ type: 'answer_rule', id: item.id })}>
                  Forget
                </button>
              </li>
            )}
          </For>
        </ul>
        <form class="remembered-add" onSubmit={(event) => (event.preventDefault(), addRule())}>
          <input value={rule.question} placeholder="Question, e.g. Notice period" onInput={(event) => setRule('question', event.currentTarget.value)} aria-label="Question" />
          <input value={rule.answer} placeholder="Answer" onInput={(event) => setRule('answer', event.currentTarget.value)} aria-label="Answer" />
          <button class="btn-outline-wax" type="submit" disabled={!rule.question.trim() || !rule.answer.trim()}>
            Add
          </button>
        </form>
      </section>

      <section class="settings-block">
        <div class="settings-block-head">
          <div class="panel-kicker">Other addresses</div>
          <p class="settings-block-note">
            A job in one of these cities gets that address on the form instead of your main one. They also count as places you will
            work.
          </p>
        </div>
        <ul class="remembered-list">
          <For each={preferenceState.addresses} fallback={<li class="remembered-empty">Only your main address so far.</li>}>
            {(item) => (
              <li>
                <div>
                  <strong>{describeAddress(item)}</strong>
                  <span>{item.country || 'Country not set'}</span>
                </div>
                <button class="btn-mono" type="button" onClick={() => forget({ type: 'address', id: item.id })}>
                  Forget
                </button>
              </li>
            )}
          </For>
        </ul>
        <form class="remembered-add" onSubmit={(event) => (event.preventDefault(), addAddress())}>
          <input value={address.label} placeholder="Label, e.g. Parents" onInput={(event) => setAddress('label', event.currentTarget.value)} aria-label="Label" />
          <input value={address.addressLine1} placeholder="Street" onInput={(event) => setAddress('addressLine1', event.currentTarget.value)} aria-label="Street" />
          <input value={address.city} placeholder="City" onInput={(event) => setAddress('city', event.currentTarget.value)} aria-label="City" />
          <input value={address.state} placeholder="State" onInput={(event) => setAddress('state', event.currentTarget.value)} aria-label="State" />
          <input value={address.postalCode} placeholder="ZIP" onInput={(event) => setAddress('postalCode', event.currentTarget.value)} aria-label="ZIP" />
          <input value={address.country} placeholder="Country" onInput={(event) => setAddress('country', event.currentTarget.value)} aria-label="Country" />
          <button class="btn-outline-wax" type="submit" disabled={!address.city.trim()}>
            Add
          </button>
        </form>
      </section>
    </div>
  )
}
