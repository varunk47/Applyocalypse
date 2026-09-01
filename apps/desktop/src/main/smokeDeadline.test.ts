import { afterEach, describe, expect, it } from "vitest";

import { smokeDeadlineMs } from "./smokeDeadline";

const KNOB = "APPLYO_SMOKE_TIMEOUT_MS";

afterEach(() => {
  delete process.env[KNOB];
});

describe("smokeDeadlineMs", () => {
  it("uses the suite's own default when the operator sets nothing", () => {
    expect(smokeDeadlineMs(15_000)).toBe(15_000);
  });

  it("treats an empty value as unset rather than as zero", () => {
    process.env[KNOB] = "";
    expect(smokeDeadlineMs(20_000)).toBe(20_000);
  });

  it("honours the override, which is the whole point of the knob", () => {
    process.env[KNOB] = "90000";
    expect(smokeDeadlineMs(15_000)).toBe(90_000);
  });

  it("lets the operator shorten the wait as well as lengthen it", () => {
    process.env[KNOB] = "3000";
    expect(smokeDeadlineMs(25_000)).toBe(3_000);
  });

  // parseInt stops at the first character it cannot use, so "15s" reads as 15
  // and "1.5" as 1. Either one turns a typo into a budget of a millisecond or
  // two, and every suite then fails on a deadline nobody chose.
  it.each(["abc", "0", "-5", "1.5", "15s", "15 000", " 15000", "1e4"])(
    "refuses %j rather than inventing a number the operator did not ask for",
    (raw) => {
      process.env[KNOB] = raw;
      expect(() => smokeDeadlineMs(15_000)).toThrow(KNOB);
    }
  );
});
