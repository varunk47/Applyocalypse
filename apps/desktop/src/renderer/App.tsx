import { onCleanup, onMount, type ParentProps } from 'solid-js'
import { useNavigate } from '@solidjs/router'
import { gsap } from './animations/gsap'
import { mountAmbientCanvas } from './animations/ambientCanvas'
import { enterFromRight, exitToLeft } from './animations/screenTransition'
import { AppProviders } from './contexts/AppProviders'
import { useProfileStore } from './contexts/ProfileStore'
import { AppRouter } from './router'
import { NavRail } from './components/NavRail'
import { WorkspaceTopbar } from './components/WorkspaceTopbar'

// GSAP-powered screen transition used by the router outlet
export const screenEnter = (el: Element, done: () => void) => enterFromRight(el, done)
export const screenExit = (el: Element, done: () => void) => exitToLeft(el, done)

export const AppShell = (props: ParentProps) => {
  let rootRef: HTMLDivElement | undefined
  let canvasRef: HTMLCanvasElement | undefined
  const { state: profileState } = useProfileStore()
  const navigate = useNavigate()

  onMount(() => {
    if (!profileState.isLoading && !profileState.profile) {
      navigate('/onboarding', { replace: true })
    }

    // Wire keyboard shortcuts from Electron Main → renderer navigation
    const unsubNav = window.applyocalypse.navigation.subscribe((msg) => {
      if (msg.type === 'navigate' && msg.route) navigate(msg.route)
    })
    onCleanup(unsubNav)

    let cleanupCanvas: (() => void) | undefined
    if (canvasRef) {
      cleanupCanvas = mountAmbientCanvas(canvasRef)
    }

    const context = gsap.context(() => {
      gsap.from("[data-gsap='nav-item']", {
        opacity: 0, x: -12, duration: 0.7, stagger: 0.048, ease: 'expo.out', delay: 0.05
      })
      gsap.from("[data-gsap='panel']", {
        opacity: 0, y: 22, scale: 0.996, duration: 0.85, stagger: 0.07, ease: 'expo.out', delay: 0.1
      })
      gsap.to('.pulse-dot', {
        scale: 1.7, opacity: 0.28, duration: 1.3, repeat: -1, yoyo: true, ease: 'sine.inOut'
      })
      gsap.to('.brand-core', {
        y: -1.5, duration: 2.2, repeat: -1, yoyo: true, ease: 'sine.inOut'
      })

      const sel = "button:not(:disabled), .artifact-row"
      const over = (e: PointerEvent) => {
        const t = (e.target as Element | null)?.closest<HTMLElement>(sel)
        if (!t || !rootRef?.contains(t) || t.contains(e.relatedTarget as Node | null)) return
        gsap.to(t, { y: -1.5, scale: 1.012, duration: 0.18, ease: 'expo.out', overwrite: 'auto' })
      }
      const out = (e: PointerEvent) => {
        const t = (e.target as Element | null)?.closest<HTMLElement>(sel)
        if (!t || !rootRef?.contains(t) || t.contains(e.relatedTarget as Node | null)) return
        gsap.to(t, { y: 0, scale: 1, duration: 0.25, ease: 'expo.out', overwrite: 'auto' })
      }
      const down = (e: PointerEvent) => {
        const t = (e.target as Element | null)?.closest<HTMLElement>(sel)
        if (!t || !rootRef?.contains(t)) return
        gsap.to(t, { y: 0.5, scale: 0.982, duration: 0.07, ease: 'power2.in', overwrite: 'auto' })
      }
      const up = (e: PointerEvent) => {
        const t = (e.target as Element | null)?.closest<HTMLElement>(sel)
        if (!t || !rootRef?.contains(t)) return
        gsap.to(t, { y: -1.5, scale: 1.012, duration: 0.16, ease: 'expo.out', overwrite: 'auto' })
      }

      rootRef?.addEventListener('pointerover', over)
      rootRef?.addEventListener('pointerout', out)
      rootRef?.addEventListener('pointerdown', down)
      rootRef?.addEventListener('pointerup', up)

      return () => {
        rootRef?.removeEventListener('pointerover', over)
        rootRef?.removeEventListener('pointerout', out)
        rootRef?.removeEventListener('pointerdown', down)
        rootRef?.removeEventListener('pointerup', up)
      }
    }, rootRef)

    onCleanup(() => {
      context.revert()
      cleanupCanvas?.()
    })
  })

  return (
    <div ref={rootRef} class="app-shell">
      <canvas
        ref={canvasRef}
        style={{ position: 'fixed', inset: '0', 'z-index': '-1', 'pointer-events': 'none' }}
        aria-hidden="true"
      />
      <NavRail />
      <main class="command-workspace">
        <WorkspaceTopbar />
        <div class="surface-grid">
          {props.children}
        </div>
      </main>
    </div>
  )
}

export const App = () => (
  <AppProviders>
    <AppRouter />
  </AppProviders>
)
