# Design: soft UI

Applyocalypse uses light neumorphism. Every surface shares one soft grey. Elements
are either pressed out of it (raised) or pressed into it (inset). Depth does the
separating, so there are almost no borders and no decoration. Light is the main
theme. Dark comes second and uses the same rules on a charcoal base.

Tokens live at the top of `apps/desktop/src/renderer/styles/app.css`. Fonts are
in `apps/desktop/src/renderer/fonts.css`.

## Type

| Role | Face | Where |
|------|------|-------|
| Everything | Onest (`--sans`, `--display`), bundled locally | UI, headings, labels |
| File paths only | system monospace (`--mono`) | settings paths |

- Headings are 650 to 700 weight, never 800 or heavier. There are no uppercase micro-labels.
- Nothing is smaller than 12px.

## Color

| Token | Light | Use |
|-------|-------|-----|
| `--paper` = `--card` = `--chrome` | #e6eaf0 | the one surface |
| `--ink` / `--ink-2` / `--ink-3` | #232a36 / #465163 / #566174 | text, tuned for 4.5:1 on the surface |
| `--wax` | #4353c9 | the accent: primary buttons, focus, active step, emphasis |
| `--armed` | #6a45d6 | the submit gate, and nothing else |
| `--danger` | #b4322a | errors |

Status shows as a soft pill, and the color always comes with the status word:
`--tab-queued`, `--tab-needs`, `--tab-running`, `--tab-done`, `--tab-failed`.

## Shape and depth

- `--neu-raised` / `--neu-raised-sm`: a white shadow up-left and a cool grey one down-right. Used for cards, buttons and chips.
- `--neu-inset` / `--neu-inset-sm`: the same shadows, inset. Used for inputs, drop zones, nav and segmented tracks, and pressed or picked states.
- State is shown with an inset 2px ring in the state colour (`inset 0 0 0 2px var(--wax)`), never a side stripe.
- Radii: `--r-card` 16px for cards, `--r-sm` 11px for buttons and fields, pills for nav, chips and status.
- The primary button is the only filled surface in view (indigo). The submit button is violet so it looks like no other button.
- Focus is a solid 2px indigo outline, because soft shadows alone are not visible enough.

## Layout

- The titlebar is part of the surface: a small indigo mark, the name and the vault note.
- Navigation is an inset pill track with the current screen raised inside it.
- Onboarding is one column of raised cards; nested entries sit inset inside their card.

## Motion

- A new screen rises 10px with a fade, then drops back.
- Only transform, opacity and shadows animate.
- Everything respects `prefers-reduced-motion`.

## Onboarding order

Resume, cover letter (optional), other documents (optional), review of what was
read (each job has a "why you left"), about you (demographics, the two legal
answers, up to 3 references), portal sign-in, ready.
