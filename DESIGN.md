# Design: Jewel

Applyocalypse is a warm ivory desk with white cards on it. A floating sidebar
sits on the left, the routed page on the ivory beside it, and the assistant in
a drawer that slides in from the right. Everything is flat: no gradients, no
glass, no glow, no shine. Ink carries everything neutral, and colour appears
only when it means something. Light is the main theme; dark follows the same
rules on warm near-black.

Tokens live at the top of `apps/desktop/src/renderer/styles/app.css`. The font
is bundled in `apps/desktop/src/renderer/fonts.css`.

## Type

| Role | Face | Where |
|------|------|-------|
| Everything | Figtree (`--sans`, `--display`), bundled locally | UI, headings, numbers |
| Paths only | system monospace (`--mono`) | settings paths |

- Page titles are 28px, weight 700, tracking -0.025em. Card titles are 14px, weight 700.
- Labels are sentence case. No uppercase micro-labels.
- Big numbers (stat tiles) use proportional figures; table columns and chart ticks use tabular figures.
- Nothing is smaller than 12px.

## Colour

One palette, used the same way on every screen and in every chart.

| Meaning | Tile fill | Text / marks | Light | Dark |
|---------|-----------|--------------|-------|------|
| Neutral (working, queued) | white card | ink | `#121214` on `#ffffff` | `#f2efe7` on `#1c1b19` |
| Your turn to sign | honey gold | gold ink | `--gold #e9b44c`, `--gold-ink #4a3000` | same fill |
| Needs you, or failed | garnet | white | `--garnet #b5452b` | same fill |
| Sent | emerald tint | emerald | `--emerald-tint #d5ebde`, `--emerald #0e7a4e` | `#17342a`, `#58a872` |

- Base: `--paper #f2efe7` (ivory) behind white `--card`s, `--sunk #eae6dc` for wells and the active nav item.
- Ink ramp: `--ink #121214`, `--ink-2 #4e4b45`, `--ink-3 #66635c`, all 4.5:1 or better on ivory and white.
- The action colour (`--wax`) is ink: primary buttons, focus rings, the stage track.
- Signing is the one irreversible act, so "Review & sign" is the only ink-and-gold button (`--armed-fill`, `--on-armed`). In dark it inverts to gold with ink.
- There is no forest green, no indigo and no violet anywhere.

## Charts

Charts use the same colours as the tiles, so "sent" is the same emerald on
Missions and on every chart.

- Single series (sent per day, week or month): emerald columns, 4px rounded tops, at most 24px wide, hairline grid, the peak labelled.
- Outcomes: emerald sent, garnet failed (`--garnet-mark`), grey withdrawn (`--withdrawn`), each with an icon and a word, never colour alone.
- Calendar: one emerald ramp, `--heat-0` to `--heat-6`, darker for more.
- Every chart has a hover and keyboard tooltip, and the main chart has a table view.
- Chart colours were checked with the dataviz palette validator in both themes.

## Shape and depth

- Cards and tiles: `--r-card` 18px, a hairline ring (`--lift`), no shadow.
- Floating layers (the drawer, tooltips): `--float`, one soft shadow.
- Hover on a clickable tile: rises 3px with `--hover-lift`.
- Buttons and fields: `--r-sm` 10px. Focus is a solid 2px ink ring.

## Layout

- Titlebar: the vault note and window controls only.
- Sidebar (216px, white, 20px radius): the mark and name, six destinations with icons (Missions, Stats, Documents, Profile, History, Settings), then "Ask anything" and the engine status at the foot.
- Pages share one header: an optional kicker, the page title, one line of plain copy.
- Missions: the intake card, then "Your queue" as tiles. The first tile is doubled in size when it is ready to sign. Each tile shows the run's five stages (Read, Tailor, Fill, Sign, Sent).
- Stats: the six-month calendar with streaks, a per day / per week / per month switch, four stat tiles, the main chart, then outcomes and portals.
- Ask anything: a 380px drawer from the right with a scrim; Esc, the close button or a click outside closes it.

## Motion

Smooth and quick, never bouncy. Only transform, opacity, colour and shadows animate.

- Screens rise 16px and fade in over 0.55s (expo out); the old screen lifts 6px and fades in 0.16s.
- Tiles rise in a stagger; a tile whose run changes state changes colour in place (0.6s).
- The current stage of a working run fills on a loop; finished stages fill once.
- The sidebar highlight and every segmented switch slide to the new choice.
- Stat numbers count up; chart columns grow from the baseline; calendar cells pop in a diagonal wave.
- The drawer slides in over 0.55s with a fading scrim.
- Everything respects `prefers-reduced-motion`.

## Onboarding order

Resume, cover letter (optional), other documents (optional), review of what was
read (each job has a "why you left"), about you (demographics, the two legal
answers, up to 3 references), portal sign-in, ready.
