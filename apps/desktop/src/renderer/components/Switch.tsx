type SwitchProps = {
  checked: boolean
  label: string
  disabled?: boolean
  onChange: (checked: boolean) => void
}

/** An on/off switch whose knob slides across; announced as a switch to screen readers. */
export const Switch = (props: SwitchProps) => (
  <button
    type="button"
    role="switch"
    class="switch"
    aria-checked={props.checked}
    aria-label={props.label}
    disabled={props.disabled}
    onClick={() => props.onChange(!props.checked)}
  >
    <span class="switch-knob" aria-hidden="true" />
  </button>
)
