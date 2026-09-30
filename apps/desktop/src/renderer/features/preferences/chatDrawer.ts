import { createSignal } from 'solid-js'

// The assistant lives in a drawer on the right; the sidebar and the drawer share this.
const [chatOpen, setChatOpen] = createSignal(false)

export { chatOpen, setChatOpen }
