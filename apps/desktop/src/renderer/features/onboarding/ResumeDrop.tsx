import { Show, createSignal } from 'solid-js'
import { ArrowRight, FileCheck2, FileText, Loader2, Lock, PenLine, Upload } from 'lucide-solid'

const SUPPORTED_EXTENSION = /\.(pdf|docx?|tex)$/i

type Props = {
  fileName: string | null
  /** True while the picker is open or the chosen file is being registered. */
  isBusy: boolean
  onChoose: () => void
  onContinue: () => void
  onManual: () => void
}

/**
 * The cold open. One decision on screen: hand over a resume. Everything the old
 * thirteen-step wizard asked for is derived from this file, so the page earns its
 * whitespace by refusing to ask anything else.
 *
 * The plate accepts a drag gesture, but a dropped file only hands the renderer a
 * display name, never a path the main process would trust. So a drop routes into
 * the one channel main will vet, its own file dialog, and the copy says so out
 * loud rather than pretending the file was already read.
 */
export function ResumeDrop(props: Props) {
  const [primed, setPrimed] = createSignal(false)
  const [handoff, setHandoff] = createSignal<string | null>(null)
  const [rejected, setRejected] = createSignal<string | null>(null)

  // dragenter/dragleave also fire for every child the cursor crosses. Counting
  // them keeps the primed state from strobing on the way in.
  let dragDepth = 0

  const onDragEnter = (event: DragEvent) => {
    event.preventDefault()
    dragDepth += 1
    setPrimed(true)
    setRejected(null)
  }

  const onDragOver = (event: DragEvent) => {
    event.preventDefault()
    if (event.dataTransfer) event.dataTransfer.dropEffect = 'copy'
  }

  const onDragLeave = (event: DragEvent) => {
    event.preventDefault()
    dragDepth = Math.max(0, dragDepth - 1)
    if (dragDepth === 0) setPrimed(false)
  }

  const onDrop = (event: DragEvent) => {
    event.preventDefault()
    dragDepth = 0
    setPrimed(false)

    const dropped = event.dataTransfer?.files?.[0] ?? null
    if (dropped && !SUPPORTED_EXTENSION.test(dropped.name)) {
      setRejected(dropped.name)
      setHandoff(null)
      return
    }

    setRejected(null)
    setHandoff(dropped?.name ?? null)
    props.onChoose()
  }

  const choose = () => {
    setRejected(null)
    setHandoff(null)
    props.onChoose()
  }

  const markIcon = () => {
    if (props.isBusy) return <Loader2 size={26} class="ob-spin" />
    if (props.fileName) return <FileCheck2 size={26} />
    if (primed()) return <Upload size={26} />
    return <FileText size={26} />
  }

  const headline = () => {
    if (props.isBusy) return 'Reading your resume'
    if (primed()) return 'Let go to hand it over'
    return props.fileName ? 'Choose a different resume' : 'Drop your resume here'
  }

  return (
    <div class="ob-hero">
      <p class="eyebrow">Step one of four</p>
      <h1 class="ob-hero-title">
        Hand us your resume.
        <br />
        We build the rest.
      </h1>
      <p class="ob-hero-sub">
        One file is enough. We read it, lay out every fact we found, and you correct anything we got
        wrong. No twenty-field intake form.
      </p>

      <div class="ob-plate-well">
        <button
          class="ob-target"
          classList={{
            primed: primed(),
            busy: props.isBusy,
            landed: Boolean(props.fileName) && !props.isBusy,
          }}
          type="button"
          disabled={props.isBusy}
          aria-describedby="ob-target-formats"
          onClick={() => choose()}
          onDragEnter={onDragEnter}
          onDragOver={onDragOver}
          onDragLeave={onDragLeave}
          onDrop={onDrop}
        >
          <span class="ob-target-mark" aria-hidden="true">
            {markIcon()}
          </span>
          <span class="ob-target-main">{headline()}</span>
          <span class="ob-target-sub" id="ob-target-formats">
            <Show when={!props.isBusy} fallback="This takes a few seconds">
              PDF, DOCX, or TEX / or click to browse
            </Show>
          </span>
        </button>
      </div>

      <Show when={rejected()}>
        {(name) => (
          <p class="ob-drop-note warn" role="status">
            <span class="mono-chip">{name()}</span>
            <span>is not a format we can read. Try a PDF, a DOCX, or a TEX source file.</span>
          </p>
        )}
      </Show>

      <Show when={!rejected() && handoff() && !props.fileName}>
        <p class="ob-drop-note" role="status">
          Almost. Pick <strong>{handoff()}</strong> in the dialog that just opened: we only read files
          this machine has handed us directly.
        </p>
      </Show>

      <Show when={props.fileName && !props.isBusy}>
        <div class="ob-landed" role="status">
          <div class="ob-landed-file">
            <FileCheck2 size={15} aria-hidden="true" />
            <span class="mono-chip">{props.fileName}</span>
          </div>
          <button class="primary-action" type="button" onClick={() => props.onContinue()}>
            <ArrowRight size={16} aria-hidden="true" />
            <span>See what we read</span>
          </button>
        </div>
      </Show>

      <p class="ob-privacy">
        <Lock size={13} aria-hidden="true" />
        <span>Parsed on this machine. The file never leaves your disk.</span>
      </p>

      <button class="ob-ghost" type="button" onClick={() => props.onManual()}>
        <PenLine size={13} aria-hidden="true" />
        <span>or fill it in by hand</span>
      </button>
    </div>
  )
}
