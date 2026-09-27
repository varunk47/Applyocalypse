# Design: the card catalog

Applyocalypse looks like a library card catalog: an oak drawer front, white
index cards with a blue ruled line and a red header rule, and colored guide tabs
that tell you what state a card is in. It should read as a tool a person keeps
records in, not as a generated dashboard. Light is the main theme. Dark ("after
hours") comes second.

Tokens live at the top of `apps/desktop/src/renderer/styles/app.css`. Fonts are
in `apps/desktop/src/renderer/fonts.css`.

## Type

| Role | Face | Where |
|------|------|-------|
| Everything a person reads | Atkinson Hyperlegible Next (`--sans`, `--display`) | UI, headings, labels |
| Anything the app typed for you | Courier Prime (`--mono`) | filled answers, file names, paths, the titlebar label |

- The split in type carries meaning: Courier means "the machine wrote this, check it".
- There are no uppercase micro-labels and no letter-spacing. Labels are 700 weight, 12px or larger.
- Nothing is smaller than 12px.

## Color

| Token | Light | Use |
|-------|-------|-----|
| `--paper` | #e7e6e3 | the desk behind the cards |
| `--card` | #fff | every surface you read from |
| `--ink` / `--ink-2` / `--ink-3` | #1d2126 / #50565e / #676d75 | text, from primary to quiet |
| `--rule-red` | #e0474c | the header rule on a card, the active tab, the headline underline |
| `--rule-blue` | #d6e6f5 | ruled lines |
| `--wax` | #2a5fa8 | links and focus only |
| `--armed` | #5a3aa6 | the submit gate, and nothing else |
| `--danger` | #b3261e | errors |

Status always shows as a guide tab, and the color always comes with the status word:

| Tab | Token | Meaning |
|-----|-------|---------|
| manila | `--tab-queued` | queued |
| salmon | `--tab-needs` | needs you |
| sky | `--tab-running` | running |
| mint | `--tab-done` | done or filed |
| grey | `--tab-failed` | failed |

## Shape and depth

- Cards have a 3px radius (`--r-card`). Tabs have 6px on the top corners only (`--r-tab`).
- Depth comes from edge lines (`--card-shadow` is a 1px bottom line), not blurred drop shadows. The toast is the one floating element and gets a small shadow.
- No side-stripe accent borders. To mark state, use a status tab or a full border in the state color.
- Primary buttons are filled with ink. The submit button is filled with violet, so it looks like no other button.

## Layout

- The titlebar is the oak drawer front, with a brass label holder for the name.
- Navigation is a strip of guide tabs across the top. The active tab is a white card with a red top rule. The number of runs waiting on you shows as a salmon chip reading "N need you".
- Onboarding is one column of index cards. Each group has a red header rule, and a confirm bar puts the note on the left and the way forward on the right.

## Motion

- A new screen is pulled up out of the drawer (y 10px to 0 with a fade), then dropped back.
- Only transform and opacity animate.
- Everything respects `prefers-reduced-motion`.

## Onboarding order

Resume, cover letter (optional), other documents (optional), review of what was
read (each job has a "why you left"), about you (demographics, the two legal
answers, up to 3 references), portal sign-in, ready.
