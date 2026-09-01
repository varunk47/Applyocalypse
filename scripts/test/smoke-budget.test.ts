import { afterEach, describe, expect, it } from "vitest";

import { smokeDeadlineMs } from "../../apps/desktop/src/main/smokeDeadline";
import { RUNNER_HEADROOM_MS, smokeBudgetMs } from "./smoke-budget.mjs";

const KNOB = "APPLYO_SMOKE_TIMEOUT_MS";

// The three deadlines the app itself arms, from apps/desktop/src/main/index.ts.
const APP_DEFAULTS = [
  ["boot", 15_000],
  ["user-flow", 20_000],
  ["full-e2e", 25_000]
] as const;

afterEach(() => {
  delete process.env[KNOB];
});

describe("smokeBudgetMs", () => {
  it("keeps its generous default when the operator sets nothing", () => {
    expect(smokeBudgetMs()).toBe(120_000);
  });

  it("treats an empty value as unset rather than as zero", () => {
    process.env[KNOB] = "";
    expect(smokeBudgetMs(90_000)).toBe(90_000);
  });

  it("clears the operator's own deadline so the app is the one that gives up", () => {
    process.env[KNOB] = "40000";
    expect(smokeBudgetMs()).toBe(40_000 + RUNNER_HEADROOM_MS);
  });

  it.each(["abc", "0", "-5", "1.5", "15s", "1e4"])(
    "refuses %j rather than inventing a number the operator did not ask for",
    (raw) => {
      process.env[KNOB] = raw;
      expect(() => smokeBudgetMs()).toThrow(KNOB);
    }
  );
});

describe("the app gives up before its runner does", () => {
  // This is the ordering that makes a smoke timeout worth reading. The app's
  // own timer prints which suite stalled and what the renderer last reported;
  // the runner's is a blunt kill that can only say the child went quiet. If the
  // runner fires first the diagnosis is lost, so the runner buys headroom on
  // top of whatever the operator asked for rather than matching it.
  it("leaves the app room to name its own failure", () => {
    expect(RUNNER_HEADROOM_MS).toBeGreaterThan(0);
  });

  it.each(APP_DEFAULTS)("holds for the %s suite when nothing is overridden", (_suite, appDefault) => {
    expect(smokeDeadlineMs(appDefault)).toBeLessThan(smokeBudgetMs());
  });

  const overrides = ["1000", "15000", "120000", "600000"];
  it.each(
    APP_DEFAULTS.flatMap(([suite, appDefault]) =>
      overrides.map((override) => [suite, appDefault, override] as const)
    )
  )("holds for the %s suite (default %dms) at APPLYO_SMOKE_TIMEOUT_MS=%s", (_suite, appDefault, override) => {
    process.env[KNOB] = override;
    expect(smokeDeadlineMs(appDefault)).toBeLessThan(smokeBudgetMs());
  });
});
