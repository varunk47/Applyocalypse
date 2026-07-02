# Plan 017: Make chat job cards live — statuses update from run events instead of freezing at enqueue time

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md`.
>
> **Drift check (run first)**: `git diff --stat 224c6f5..HEAD -- apps/desktop/src/renderer/contexts/ChatStore.tsx apps/desktop/src/renderer/features/chat/ apps/desktop/src/renderer/screens/ChatScreen.tsx apps/desktop/src/preload/index.ts`
> If the chat feature changed since this plan was written, compare excerpts;
> on a semantic mismatch, STOP.

## Status

- **Priority**: P2
- **Effort**: L
- **Risk**: MED (renderer-only; no main-process changes — but it is the app's primary surface)
- **Depends on**: none
- **Category**: bug / direction (Phase 5 chat vision, items 3-4, was left half-built)
- **Planned at**: commit `224c6f5`, 2026-06-11

## Why this matters

The chat screen is the app's default route and the product's core "chatbot
interface" vision. Today a `JOB_CARD` chat message renders the status captured
in its metadata **at enqueue time** and never changes: cards say "Queued"
forever while the run scrapes, tailors, hits review gates, and completes in
the background; the batch header stays at "N queued". All real interaction is
forced into the Run Console. This plan wires the existing renderer event
stream into the chat store so cards progress live and a review-required state
deep-links to the Run Console. No main-process changes are needed.

## Current state

- `apps/desktop/src/renderer/contexts/ChatStore.tsx` (49 lines, full source
  read at planning time): solid-js store + reducer:
  ```ts
  export type ChatAction =
    | { type: 'LOADED'; messages: ChatMessage[] }
    | { type: 'APPENDED'; message: ChatMessage }
  ```
  `getBatchProgress(messages, batchId)` already aggregates counts from
  `(m.metadata as { status?: string }).status` — it will work unmodified once
  metadata statuses update.
- `apps/desktop/src/renderer/features/chat/JobCard.tsx` (86 lines): renders
  `meta().status ?? 'QUEUED'` from `props.message.metadata` (`JobCardMeta` has
  `queueItemId?`, `runId?`, `status?`). Pure display — needs only a
  "Review required → open Run Console" affordance added.
- `apps/desktop/src/renderer/screens/ChatScreen.tsx` (180 lines): builds
  JOB_CARD messages on enqueue with `queueItemId` and `status: queueItem.status`
  (line ~92-95). `runId` is NOT set at creation (the scheduler creates the run
  later).
- Event stream available to the renderer —
  `apps/desktop/src/preload/index.ts:170-181`:
  ```ts
  logs: {
    subscribe: (runId: string, listener: (event: SafeRendererRunEvent) => void) => {
      // filters broadcast logsEvent by runId, returns unsubscribe fn
    }
  }
  ```
  Per-run only; there is no "all events" subscription, and adding one is out
  of scope (no main-process changes).
- Run listing — `window.applyocalypse.runs.list(limit, offset)` returns
  `{ items: ApplicationRun[], total }`; each ApplicationRun has `id`,
  `queueItemId`, `status` (see `QueueStore.tsx:80-98`, which already uses it
  to map queue items → runs by polling).
- Statuses in play (from `statusForEvent` map in pythonEventIngest.ts and the
  run lifecycle): QUEUED, PREPARING, ANALYZING, TAILORING_RESUME,
  GENERATING_COVER_LETTER, READY_FOR_REVIEW, WAITING_FOR_USER_EDIT,
  RUNNING_AUTOMATION, BLOCKED_OTP, READY_TO_SUBMIT, SUBMITTED, PAUSED,
  COMPLETED, FAILED, CANCELLED. Terminal: COMPLETED, FAILED, CANCELLED,
  SUBMITTED.
- Persistence note: chat messages live in SQLite (`chat_messages`, migration
  0011) but **status must not be persisted back into chat history** — it is
  derived state owned by `application_runs`; on every load, statuses must be
  re-hydrated from `runs.list`, never trusted from stored metadata.
- Tests: `ChatStore.test.ts` (9 tests) — reducer-level, node environment; the
  pattern to extend.

## Commands you will need

| Purpose | Command (repo root) | Expected on success |
|---------|---------------------|---------------------|
| Targeted | `pnpm vitest run apps/desktop/src/renderer/contexts/ChatStore.test.ts apps/desktop/src/renderer/contexts/chatLiveSync.test.ts` | all pass |
| Typecheck | `pnpm typecheck` | exit 0 |
| Full | `pnpm test` | exit 0 |
| Manual | `pnpm dev` → enqueue a job from chat | card progresses past "Queued" without navigating away |

## Scope

**In scope**:
- `apps/desktop/src/renderer/contexts/ChatStore.tsx` (new action + reducer case)
- `apps/desktop/src/renderer/contexts/chatLiveSync.ts` (create — the sync engine)
- `apps/desktop/src/renderer/contexts/chatLiveSync.test.ts` (create)
- `apps/desktop/src/renderer/contexts/ChatStore.test.ts` (extend)
- `apps/desktop/src/renderer/screens/ChatScreen.tsx` (mount/unmount the sync; hydrate on load)
- `apps/desktop/src/renderer/features/chat/JobCard.tsx` (review-required affordance + new status labels)

**Out of scope** (do NOT touch):
- Anything in `apps/desktop/src/main/` or `packages/ipc-contracts` — this is
  renderer-only by design.
- Inline approve/edit/document buttons in chat (phase 2 — see Maintenance).
- `QueueStore.waitForRunForQueueItems` polling — leave as is.
- Persisting statuses into chat_messages.

## Git workflow

- Branch suggestion: this is the largest plan — use a branch (`feat/chat-live-status`).
- Commit message: `feat(chat): live job-card statuses from run events`

## Steps

### Step 1: ChatStore action for status updates

Add to `ChatStore.tsx`:

```ts
export type ChatAction =
  | { type: 'LOADED'; messages: ChatMessage[] }
  | { type: 'APPENDED'; message: ChatMessage }
  | { type: 'CARD_RUN_STATE'; messageId: string; runId: string; status: string }
```

Reducer case (immutably update one message's metadata):

```ts
case 'CARD_RUN_STATE':
  return {
    ...state,
    messages: state.messages.map((m) =>
      m.id === action.messageId
        ? { ...m, metadata: { ...(m.metadata as object), runId: action.runId, status: action.status } }
        : m
    ),
  }
```

**Verify**: `pnpm vitest run apps/desktop/src/renderer/contexts/ChatStore.test.ts` → existing 9 pass.

### Step 2: The live-sync engine (pure, testable core)

Create `chatLiveSync.ts` exporting two layers:

**Pure core** (unit-testable, no window access):

```ts
export type CardRef = { messageId: string; queueItemId?: string; runId?: string; status?: string }
export type RunRow = { id: string; queueItemId: string; status: string }

export const TERMINAL_STATUSES = new Set(['COMPLETED', 'FAILED', 'CANCELLED', 'SUBMITTED'])

/** Diff cards against the authoritative run list; return the dispatches needed. */
export const reconcileCards = (cards: CardRef[], runs: RunRow[]):
  Array<{ messageId: string; runId: string; status: string }> => {
  const byQueueItem = new Map(runs.map((r) => [r.queueItemId, r]))
  const out = []
  for (const card of cards) {
    if (!card.queueItemId) continue
    const run = byQueueItem.get(card.queueItemId)
    if (!run) continue
    if (card.runId !== run.id || card.status !== run.status) {
      out.push({ messageId: card.messageId, runId: run.id, status: run.status })
    }
  }
  return out
}

export const hasLiveCards = (cards: CardRef[]): boolean =>
  cards.some((c) => c.queueItemId && !TERMINAL_STATUSES.has(c.status ?? 'QUEUED'))
```

**Effectful shell** `startChatLiveSync()`:
- Extracts `CardRef`s from `chatState.messages` (kind === 'JOB_CARD').
- Reconcile loop: while `hasLiveCards`, every 3000ms call
  `window.applyocalypse.runs.list(100, 0)`, run `reconcileCards`, dispatch
  each result as `CARD_RUN_STATE`. When no live cards remain, stop the timer
  (restart when a new JOB_CARD is appended — drive this from a solid
  `createEffect` watching message count, or simply restart the loop on each
  APPENDED dispatch via an exported `notifyCardsChanged()` the screen calls).
- Low-latency push layer: for each card that HAS a runId and is non-terminal,
  hold one `window.applyocalypse.logs.subscribe(runId, () => scheduleReconcile())`
  subscription (a Map runId→unsubscribe). `scheduleReconcile` = debounced
  (250ms) single `runs.list` reconcile, so event semantics never need
  duplicating in the renderer — events are just triggers, `runs.list` is the
  source of truth. Unsubscribe terminal runs.
- Returns a `stop()` disposing timers and all subscriptions.

**Verify**: `pnpm typecheck` → exit 0.

### Step 3: Mount in ChatScreen + hydrate on load

In `ChatScreen.tsx`:
1. `onMount`: after the existing chat-history load dispatches LOADED, call
   `startChatLiveSync()` once and keep the `stop` handle; `onCleanup(stop)`.
   The first reconcile pass also HYDRATES stale persisted statuses (cards
   loaded from SQLite with old metadata get corrected by the first
   `runs.list` diff — no special-case code needed).
2. Where the screen appends JOB_CARD messages after enqueue (~line 92), call
   `notifyCardsChanged()` (or whatever restart hook Step 2 chose).

**Verify**: `pnpm typecheck` → exit 0; manual: `pnpm dev`, enqueue a job from
chat, observe the card move past "Queued" within ~3s and the batch header
counts change.

### Step 4: JobCard review affordance + label coverage

In `JobCard.tsx`:
1. Extend `statusLabel`/`statusClass` maps to cover ALL statuses listed in
   Current state (ANALYZING → 'Analyzing', TAILORING_RESUME → 'Tailoring',
   GENERATING_COVER_LETTER → 'Cover letter', READY_FOR_REVIEW → 'Review
   required', WAITING_FOR_USER_EDIT → 'Edit required', BLOCKED_OTP → 'OTP
   needed', READY_TO_SUBMIT → 'Ready to submit', SUBMITTED → 'Submitted',
   PAUSED → 'Paused'). Review-ish statuses get `status-review` class; add the
   CSS class beside the existing `status-*` styles (find them:
   `grep -rn "status-running" apps/desktop/src/renderer` and add `status-review`
   in the same stylesheet with a distinct accent).
2. When status is one of READY_FOR_REVIEW / WAITING_FOR_USER_EDIT /
   BLOCKED_OTP / READY_TO_SUBMIT and `meta().runId` exists, render a button
   "Open run" that navigates to the Run Console route for that run. Find the
   route shape with `grep -n "run" apps/desktop/src/renderer/router.tsx` and
   navigate the way other screens do (`useNavigate` from @solidjs/router —
   check an exemplar screen).

**Verify**: `pnpm typecheck` → exit 0.

### Step 5: Tests

1. `chatLiveSync.test.ts` (pure core):
   - `reconcileCards` maps queueItemId→run, emits only changed cards,
     ignores cards without queueItemId, ignores cards already current.
   - `hasLiveCards` false when all terminal; true with one QUEUED.
2. `ChatStore.test.ts`: CARD_RUN_STATE updates the right message's metadata
   immutably (others untouched), preserves existing metadata keys
   (company/role survive).
3. Existing `getBatchProgress` tests keep passing — they prove the header
   aggregates the new statuses (extend one case: a RUNNING_AUTOMATION +
   READY_FOR_REVIEW mix counts as running per the existing bucketing; check
   how the function buckets unknown statuses — it defaults to queued; decide
   with the function's actual code whether READY_FOR_REVIEW should count as
   `running` and adjust ITS bucket list, with a test).

**Verify**: targeted vitest command → all pass; `pnpm test` → exit 0.

## Test plan

Covered in Step 5 (pure core + reducer). The effectful shell (timers,
subscriptions) is validated manually via `pnpm dev` — record in the report
what you observed (card progression, header counts, "Open run" navigation).

## Done criteria

- [ ] `pnpm typecheck` and `pnpm test` exit 0; new tests pass
- [ ] JobCard statuses update without navigating away (manual check, described in report)
- [ ] Statuses are NEVER written back to chat persistence (grep: no `chat` IPC call in chatLiveSync.ts)
- [ ] Review-required cards deep-link to the Run Console
- [ ] All run statuses have labels (no raw enum strings in the UI)
- [ ] `plans/README.md` status row updated

## STOP conditions

Stop and report back if:

- `runs.list` does not return `queueItemId` per item (check the contract in
  packages/ipc-contracts — the mapping is the plan's backbone).
- Subscribing to many runIds via `logs.subscribe` causes duplicate
  `logsSubscribe` invokes that the main process rejects (read the
  logsSubscribe handler in registerIpc.ts first; at planning time it appears
  idempotent — verify).
- The ChatMessage metadata type is strictly validated somewhere
  (Zod-parsed on read) such that adding/refreshing keys breaks parsing.
- The 3s reconcile visibly degrades renderer performance with 100+ cards
  (measure before optimizing; report rather than redesign).

## Maintenance notes

- Phase 2 (explicitly deferred): inline Approve/Edit review actions on the
  card, reusing `materialRequirementsView` handlers, and document open
  buttons. The CARD_RUN_STATE plumbing this plan adds is the foundation.
- If a global (non-per-run) renderer event channel is ever added to preload,
  replace the 3s reconcile timer with pure push and delete the polling.
- Reviewer should scrutinize: subscription cleanup (no leaked `ipcRenderer.on`
  handlers after unmount — `stop()` must run in `onCleanup`), and that the
  debounced reconcile cannot stack concurrent `runs.list` calls.
