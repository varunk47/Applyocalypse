import { For, createContext, createSignal, onCleanup, useContext, type ParentProps } from 'solid-js'
import { CheckCircle2, AlertTriangle, XCircle, Info, X } from 'lucide-solid'
import { gsap } from '../animations/gsap'

type ToastKind = 'success' | 'error' | 'info' | 'warning'

interface ToastItem {
  id: string
  kind: ToastKind
  message: string
}

interface ToastContextValue {
  success: (message: string) => void
  error: (message: string) => void
  info: (message: string) => void
  warning: (message: string) => void
}

const ToastContext = createContext<ToastContextValue>()

const ICON: Record<ToastKind, typeof CheckCircle2> = {
  success: CheckCircle2,
  error: XCircle,
  warning: AlertTriangle,
  info: Info,
}

const COLOR: Record<ToastKind, string> = {
  success: 'var(--success)',
  error: 'var(--danger)',
  warning: 'var(--warning)',
  info: 'var(--accent-strong)',
}

let uid = 0

export const ToastProvider = (props: ParentProps) => {
  const [toasts, setToasts] = createSignal<ToastItem[]>([])

  const dismiss = (id: string) => setToasts((t) => t.filter((item) => item.id !== id))

  const push = (kind: ToastKind, message: string) => {
    const id = String(++uid)
    setToasts((t) => [...t, { id, kind, message }].slice(-4))
    window.setTimeout(() => dismiss(id), 4000)
  }

  const ctx: ToastContextValue = {
    success: (m) => push('success', m),
    error: (m) => push('error', m),
    info: (m) => push('info', m),
    warning: (m) => push('warning', m),
  }

  return (
    <ToastContext.Provider value={ctx}>
      {props.children}
      <div class="toast-viewport" aria-live="polite">
        <For each={toasts()}>
          {(item) => {
            let el: HTMLDivElement | undefined
            const Icon = ICON[item.kind]

            const animateIn = (node: Element) => {
              gsap.fromTo(node, { y: 12, opacity: 0 }, { y: 0, opacity: 1, duration: 0.25, ease: 'expo.out' })
            }
            const animateOut = (node: Element, done: () => void) => {
              gsap.to(node, { y: 12, opacity: 0, duration: 0.18, ease: 'expo.in', onComplete: done })
            }

            // Animate in on mount
            // (solid-transition-group handles this via parent Transition if needed;
            // here we use a simple ref-based approach)
            setTimeout(() => { if (el) animateIn(el) }, 0)

            return (
              <div ref={el} class="toast" role="status">
                <Icon size={18} aria-hidden="true" style={{ color: COLOR[item.kind], 'flex-shrink': '0' }} />
                <span style={{ flex: '1', 'font-size': '0.85rem', color: 'var(--text)' }}>{item.message}</span>
                <button
                  type="button"
                  style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--muted)', padding: '0' }}
                  aria-label="Dismiss"
                  onClick={() => {
                    if (el) animateOut(el, () => dismiss(item.id))
                    else dismiss(item.id)
                  }}
                >
                  <X size={14} aria-hidden="true" />
                </button>
              </div>
            )
          }}
        </For>
      </div>
    </ToastContext.Provider>
  )
}

export const useToast = (): ToastContextValue => {
  const ctx = useContext(ToastContext)
  if (!ctx) throw new Error('ToastProvider is missing')
  return ctx
}
