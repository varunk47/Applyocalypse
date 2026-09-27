# Design: soft glass

Applyocalypse sits between glassmorphism and neumorphism. Frosted, translucent
panels float over a quiet backdrop with faint indigo, teal and lavender tints.
Panels are lifted: translucent white, a bright top edge, a thin white rim and a
soft shadow below. Anything that takes input sits in a shallow well. There are
almost no borders and no decoration. Light is the main theme. Dark comes second
and uses the same rules over a near-black backdrop.

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
| `--backdrop` / `--paper` | tinted gradients over #eef1f6 | the app background; `--paper` is its solid base |
| `--card` / `--chrome` | white at 62% / 38% | frosted panels / quieter rails and wells |
| `--ink` / `--ink-2` / `--ink-3` | #232a36 / #465163 / #566174 | text, tuned for 4.5:1 on the surface |
| `--wax` | #4353c9 | the accent: primary buttons, focus, active step, emphasis |
| `--armed` | #6a45d6 | the submit gate, and nothing else |
| `--danger` | #b4322a | errors |

Status shows as a soft pill, and the color always comes with the status word:
`--tab-queued`, `--tab-needs`, `--tab-running`, `--tab-done`, `--tab-failed`.

## Shape and depth

- `--lift` / `--lift-sm`: an inset white top edge, a 1px white rim and a soft shadow below. Used for panels, buttons and chips. Panels on the backdrop also get `backdrop-filter: var(--blur)`.
- `--well` / `--well-sm`: a faint inner shadow and a thin inner rim. Used for inputs, drop zones, segmented tracks and pressed or picked states.
- State is shown with an inset 2px ring in the state colour (`inset 0 0 0 2px var(--wax)`), never a side stripe.
- Radii: `--r-card` 16px for cards, `--r-sm` 11px for buttons and fields, pills for nav, chips and status.
- The primary button is the only filled surface in view (indigo). The submit button is violet so it looks like no other button.
- Focus is a solid 2px indigo outline, because soft shadows alone are not visible enough.

## Layout

- The titlebar is part of the surface: a small indigo mark, the name and the vault note.
- Navigation is a frosted pill with the current screen shown as solid white glass inside it.
- Onboarding is one column of frosted panels; nested entries sit in wells inside their panel.

## Motion

- A new screen rises 10px with a fade, then drops back.
- Only transform, opacity and shadows animate.
- Everything respects `prefers-reduced-motion`.

## Onboarding order

Resume, cover letter (optional), other documents (optional), review of what was
read (each job has a "why you left"), about you (demographics, the two legal
answers, up to 3 references), portal sign-in, ready.
