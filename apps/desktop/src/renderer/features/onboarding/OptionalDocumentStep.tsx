import { For, Show } from 'solid-js'
import { ArrowRight, FileText, Loader2, Plus } from 'lucide-solid'

type Props = {
  eyebrow: string
  title: string
  sub: string
  addLabel: string
  fileNames: string[]
  isBusy: boolean
  onAdd: () => void
  onContinue: () => void
}

/**
 * A step the user may skip. Files already added are listed as filed cards, so
 * coming back to the step shows what is on hand instead of an empty drop zone.
 */
export function OptionalDocumentStep(props: Props) {
  return (
    <div class="ob-hero">
      <p class="eyebrow">{props.eyebrow}</p>
      <h1 class="ob-hero-title">{props.title}</h1>
      <p class="ob-hero-sub">{props.sub}</p>

      <div class="ob-filed">
        <For each={props.fileNames}>
          {(name) => (
            <div class="ob-filed-card">
              <FileText size={15} aria-hidden="true" />
              <span class="ob-filed-name">{name}</span>
              <span class="status-tab done">Filed</span>
            </div>
          )}
        </For>
        <button class="ob-add" type="button" disabled={props.isBusy} onClick={() => props.onAdd()}>
          <Show when={props.isBusy} fallback={<Plus size={13} aria-hidden="true" />}>
            <Loader2 size={13} class="ob-spin" aria-hidden="true" />
          </Show>
          <span>{props.addLabel}</span>
        </button>
      </div>

      <div class="ob-confirm-bar">
        <p class="fine-print">Optional. You can add or remove these later under Documents.</p>
        <button class="primary-action ob-advance" type="button" onClick={() => props.onContinue()}>
          <ArrowRight size={17} aria-hidden="true" />
          <span>{props.fileNames.length > 0 ? 'Continue' : 'Skip for now'}</span>
        </button>
      </div>
    </div>
  )
}
