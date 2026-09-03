// A smoke timeout is a "this process is hung" bound, not a performance
// assertion. These suites run right after a native rebuild that can recompile
// better-sqlite3 from scratch, so the machine is often saturated when Electron
// makes its cold start and applies first-run migrations. Budgets tuned to an
// idle developer box turn that into a red build with nothing to debug.
const DEFAULT_BUDGET_MS = 120_000;

/**
 * Extra patience the runner keeps beyond the operator's value.
 *
 * The desktop suites arm a deadline inside the app too (see
 * apps/desktop/src/main/smokeDeadline.ts), and both read the same variable. The
 * app's timer is the one worth reaching: it prints which suite stalled and what
 * the renderer last reported, where this one can only say the child went quiet.
 * Matching the two exactly would make which fires first a coin toss, so the
 * runner buys a few seconds for the app to name its own failure and exit.
 */
export const RUNNER_HEADROOM_MS = 5_000;

/**
 * @param {number} [fallback] budget when the environment does not override it
 * @returns {number} milliseconds to wait before declaring a smoke child hung
 */
export const smokeBudgetMs = (fallback = DEFAULT_BUDGET_MS) => {
  const raw = process.env.APPLYO_SMOKE_TIMEOUT_MS;
  if (raw === undefined || raw === "") {
    return fallback;
  }

  // Deliberately stricter than parseInt, which stops at the first character it
  // cannot use: it reads "15s" as 15 and "1.5" as 1, so a typo silently becomes
  // a budget of a millisecond or two. Kept identical to the app-side check.
  if (!/^\d+$/.test(raw) || Number(raw) <= 0) {
    throw new Error(`APPLYO_SMOKE_TIMEOUT_MS must be a positive integer of milliseconds, got "${raw}"`);
  }

  return Number(raw) + RUNNER_HEADROOM_MS;
};

/**
 * Says what actually happened. The old message collapsed to a bare marker when
 * the child printed nothing, which is exactly the case that needs explaining.
 *
 * @param {string} label suite marker prefix, e.g. "boot-smoke"
 * @param {number} budgetMs
 * @param {string} output everything the child wrote before it was killed
 */
export const timeoutMessage = (label, budgetMs, output) =>
  output
    ? `${label}:timeout after ${budgetMs}ms. Output before the kill:\n${output}`
    : `${label}:timeout after ${budgetMs}ms with no output at all, so the child never reached its first log line.`;
