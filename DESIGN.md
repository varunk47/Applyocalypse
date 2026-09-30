# Design: paper and sheet

Applyocalypse looks like a sheet of good paper on a desk. The window is warm
paper; the working area is a single white sheet laid on it; everything inside
the sheet is separated by hairlines, not boxes or shadows. One ink colour does
the pointing. Violet is kept for the one irreversible act, submitting. Light is
the main theme. Dark follows the same rules on near-black.

Tokens live at the top of `apps/desktop/src/renderer/styles/app.css`. Fonts are
in `apps/desktop/src/renderer/fonts.css`.

## Type

| Role | Face | Where |
|------|------|-------|
| Display | Fraunces (`--display`), bundled locally | screen headlines, onboarding headlines, card titles |
| Everything else | Onest (`--sans`), bundled locally | UI, labels, body copy |
| File paths only | system monospace (`--mono`) | settings paths, run ids |

- Screen headlines are Fraunces at 30px, 560 weight. Emphasis inside a headline takes the accent colour, never italics.
- Labels are sentence case. No uppercase micro-labels, no letter-spaced kickers. Acronyms (DOCX, OTP, EEO) stay as they are.
- Nothing is smaller than 12px.

## Colour

| Token | Light | Dark | Use |
|-------|-------|------|-----|
| `--paper` / `--backdrop` | #f3f1ec | #111214 | the desk behind the sheet |
| `--card` / `--chrome` | #ffffff | #1e1f24 / #191a1e | the sheet, and cards on it |
| `--ink` / `--ink-2` / `--ink-3` | #15171c / #474c57 / #5f6472 | #ecebe7 / #bdbcb6 / #9d9c96 | text, each 4.5:1 or better on its surface |
| `--hairline` / `-strong` / `-soft` | #e6e3db / #d4cfc3 / #efece6 | #2b2c32 / #3a3b42 / #222328 | every divider and field edge |
| `--wax` | #0e6570 | #74c6cc | the accent, "bottle ink": primary buttons, focus, active step, emphasis |
| `--armed` | #6641d4 | #b9a4f6 | the submit gate, and nothing else |
| `--danger` | #b3261e | #f29a90 | errors and failures; never the accent |
| `--live` | #177049 | #7fd1ad | running and submitted |

The accent is a deep teal so it reads as ink on paper rather than as a UI blue
(6.7:1 on white, 6.0:1 on paper). Status shows as a soft pill and the colour
always comes with the status word: `--tab-queued`, `--tab-needs`,
`--tab-running`, `--tab-done`, `--tab-failed`.

## Shape and depth

- `--lift` / `--lift-sm`: a 1px hairline ring plus one soft shadow. Used for the sheet, cards and buttons.
- `--well` / `--well-sm`: an inset hairline, no inner shade. Used for inputs, drop zones and segmented tracks.
- There is no blur and no glass. `--blur` is `none`.
- State is an inset 2px ring in the state colour (`inset 0 0 0 2px var(--wax)`), never a side stripe.
- Radii: `--r-card` 14px for cards, `--r-sm` 9px for buttons and fields, pills for nav, chips and status.
- The primary button is the only filled surface in view (ink). The submit button is violet so it looks like no other button.
- Save buttons sit under the fields they save, at their own width, never stretched across a card.
- Focus is a solid 2px accent outline.

## Layout

- The titlebar sits on the paper: a small ink mark, the name and the vault note.
- The preference chat is a column on the paper to the left of the sheet.
- Navigation is a row of text tabs across the top of the sheet; the current one is underlined.
- Content screens (Documents, Profile, History) open with a Fraunces headline and one line of plain copy.
- Profile forms are a two-column grid, capped at 800px, one column below 620px.
- Signed out, the app shows the sign-in screen: the promise on the paper at left, the form on a sheet at right.

## Motion

- A new screen rises 10px with a fade.
- Only transform, opacity and shadows animate.
- Everything respects `prefers-reduced-motion`.

## Onboarding order

Resume, cover letter (optional), other documents (optional), review of what was
read (each job has a "why you left"), about you (demographics, the two legal
answers, up to 3 references), portal sign-in, ready.
