import { ArrowRight, FileCheck2, FileSearch, Lock } from 'lucide-solid'

type Props = {
  /** The DOCX we rebuilt from the user's PDF. */
  candidateName: string
  isBusy: boolean
  onOpen: () => void
  onConfirm: () => void
}

/**
 * A PDF cannot be edited in place, so a PDF upload is converted to a DOCX that
 * stands in for it. Tailoring only ever writes into a *confirmed* master, so
 * skipping this step means every later application silently falls back to a
 * layout we invented instead of the user's own. Documents was the only screen
 * offering the confirmation, and nobody visits it before their first run, so
 * the gate lives here: onboarding does not continue around it.
 */
export function EditableMasterGate(props: Props) {
  return (
    <div class="ob-hero">
      <p class="eyebrow">One look before we continue</p>
      <h1 class="ob-hero-title">
        We rebuilt your PDF
        <br />
        as an editable copy.
      </h1>
      <p class="ob-hero-sub">
        Tailoring edits this copy, which is how every application keeps your own layout instead of a
        template. Open it, check that it still reads like your resume, then confirm. Your original PDF
        is kept exactly as you handed it over.
      </p>

      <div class="ob-master" role="group" aria-label="Editable copy of your resume">
        <div class="ob-master-file">
          <FileCheck2 size={15} aria-hidden="true" />
          <span class="mono-chip">{props.candidateName}</span>
        </div>
        <button class="secondary-action" type="button" onClick={() => props.onOpen()}>
          <FileSearch size={16} aria-hidden="true" />
          <span>Open it</span>
        </button>
        <button
          class="primary-action"
          type="button"
          disabled={props.isBusy}
          onClick={() => props.onConfirm()}
        >
          <ArrowRight size={16} aria-hidden="true" />
          <span>{props.isBusy ? 'Confirming...' : 'Use this for tailoring'}</span>
        </button>
      </div>

      <p class="ob-privacy">
        <Lock size={13} aria-hidden="true" />
        <span>Converted on this machine. Neither file leaves your disk.</span>
      </p>
    </div>
  )
}
