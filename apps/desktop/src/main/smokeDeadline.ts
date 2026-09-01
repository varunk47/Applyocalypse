const OVERRIDE_ENV_VAR = "APPLYO_SMOKE_TIMEOUT_MS";

/**
 * How long a smoke run waits before the app declares itself hung.
 *
 * The runner in `scripts/test/smoke-budget.mjs` keeps a bound of its own and
 * the two are not interchangeable. This one fires from inside the app, so its
 * message can say which suite stalled and what the renderer last reported; the
 * runner's is the blunt backstop for a child that never spoke at all. The app
 * must therefore give up first, which is why the runner adds headroom on top of
 * the operator's value instead of matching it. `scripts/test/smoke-budget.test.ts`
 * pins that ordering across both modules.
 *
 * @param defaultMs the suite's own deadline, used when the operator sets nothing
 */
export const smokeDeadlineMs = (defaultMs: number): number => {
  const raw = process.env[OVERRIDE_ENV_VAR];
  if (raw === undefined || raw === "") {
    return defaultMs;
  }

  // Deliberately stricter than parseInt, which stops at the first character it
  // cannot use: it reads "15s" as 15 and "1.5" as 1, so a typo silently becomes
  // a budget of a millisecond or two and every suite fails on a deadline nobody
  // chose. A wrong value should be loud.
  if (!/^\d+$/.test(raw) || Number(raw) <= 0) {
    throw new Error(`${OVERRIDE_ENV_VAR} must be a positive integer of milliseconds, got "${raw}"`);
  }

  return Number(raw);
};
