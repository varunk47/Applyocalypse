import { Show } from 'solid-js'
import { FileText, Lock, PenLine } from 'lucide-solid'

type Props = {
  fileName: string | null
  onChoose: () => void
  onManual: () => void
}

/**
 * The cold open. One decision on screen: hand over a resume. Everything the old
 * thirteen-step wizard asked for is derived from this file, so the page earns
 * its whitespace by refusing to ask anything else.
 */
export function ResumeDrop(props: Props) {
  return (
    <div class="ob-hero">
      <h1 class="ob-hero-title">
        Hand us your resume.
        <br />
        We build the rest.
      </h1>
      <p class="ob-hero-sub">
        One file is enough. We read it, lay out every fact we found, and you correct anything we got
        wrong. No twenty-field intake form.
      </p>

      <button class="ob-target" type="button" onClick={props.onChoose}>
        <FileText size={28} aria-hidden="true" />
        <span class="ob-target-main">{props.fileName ? 'Choose a different resume' : 'Choose your resume'}</span>
        <span class="ob-target-sub">PDF, DOCX, or TEX</span>
      </button>

      <Show when={props.fileName}>
        {(name) => (
          <p class="ob-picked">
            <span class="mono-chip">{name()}</span>
          </p>
        )}
      </Show>

      <p class="ob-privacy">
        <Lock size={13} aria-hidden="true" />
        <span>Parsed on this machine. The file never leaves your disk.</span>
      </p>

      <button class="ob-ghost" type="button" onClick={props.onManual}>
        <PenLine size={13} aria-hidden="true" />
        <span>or fill it in by hand</span>
      </button>
    </div>
  )
}
