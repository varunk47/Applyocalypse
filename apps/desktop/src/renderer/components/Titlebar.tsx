export const Titlebar = () => {
  const control = (action: 'minimize' | 'toggle-maximize' | 'close') => {
    void window.applyocalypse.system.windowControl(action)
  }

  return (
    <header class="titlebar" data-gsap="panel">
      <div class="brand-seal" data-gsap="nav-item" aria-hidden="true">
        A
      </div>
      <span class="brand-word">Applyocalypse</span>
      <span class="vault-note">LOCAL VAULT · ENCRYPTED</span>
      <div class="window-controls">
        <button type="button" aria-label="Minimize window" onClick={() => control('minimize')}>
          <span class="glyph-min" />
        </button>
        <button type="button" aria-label="Maximize or restore window" onClick={() => control('toggle-maximize')}>
          <span class="glyph-max" />
        </button>
        <button type="button" class="close" aria-label="Close window" onClick={() => control('close')}>
          <span class="glyph-close">✕</span>
        </button>
      </div>
    </header>
  )
}
