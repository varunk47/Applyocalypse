import { describe, expect, it } from "vitest";
import {
  WORK_AUTHORIZATION_STATUSES,
  deriveWorkAuthorization,
  readWorkAuthorization,
  type SponsorshipNeed,
  type WorkAuthorizationStatus
} from "./workAuthorization";

describe("WORK_AUTHORIZATION_STATUSES", () => {
  it("offers every status with a label the user can recognise", () => {
    for (const option of WORK_AUTHORIZATION_STATUSES) {
      expect(option.label.length).toBeGreaterThan(0);
      expect(option.label).not.toContain("—");
    }
  });

  it("has no duplicate ids", () => {
    const ids = WORK_AUTHORIZATION_STATUSES.map((option) => option.id);
    expect(new Set(ids).size).toBe(ids.length);
  });
});

describe("deriveWorkAuthorization", () => {
  // The two questions every US portal asks, and the answer each status owes
  // them. "Will you now or in the future require sponsorship" is the one that
  // catches people out: someone on OPT is authorized today and still has to
  // answer Yes.
  const CASES: ReadonlyArray<{
    status: WorkAuthorizationStatus;
    authorizedInUs: boolean;
    sponsorshipNeed: SponsorshipNeed;
  }> = [
    { status: "US_CITIZEN", authorizedInUs: true, sponsorshipNeed: "NEVER" },
    { status: "PERMANENT_RESIDENT", authorizedInUs: true, sponsorshipNeed: "NEVER" },
    { status: "F1_OPT", authorizedInUs: true, sponsorshipNeed: "FUTURE" },
    { status: "F1_CPT", authorizedInUs: true, sponsorshipNeed: "FUTURE" },
    { status: "H1B", authorizedInUs: true, sponsorshipNeed: "NOW" },
    { status: "NOT_YET_AUTHORIZED", authorizedInUs: false, sponsorshipNeed: "NOW" }
  ];

  it.each(CASES)("$status answers both portal questions", (expected) => {
    const answer = deriveWorkAuthorization(expected.status, null);
    expect(answer).not.toBeNull();
    expect(answer?.authorizedInUs).toBe(expected.authorizedInUs);
    expect(answer?.sponsorshipNeed).toBe(expected.sponsorshipNeed);
    expect(answer?.summary.length).toBeGreaterThan(0);
  });

  it("refuses to guess for a status that does not imply an answer", () => {
    expect(deriveWorkAuthorization("OTHER_AUTHORIZED", null)).toBeNull();
  });

  it("accepts an explicit answer for that status", () => {
    const answer = deriveWorkAuthorization("OTHER_AUTHORIZED", "FUTURE");
    expect(answer?.authorizedInUs).toBe(true);
    expect(answer?.sponsorshipNeed).toBe("FUTURE");
  });

  it("lets the user override a status default, because immigration is not a lookup table", () => {
    const answer = deriveWorkAuthorization("H1B", "NEVER");
    expect(answer?.sponsorshipNeed).toBe("NEVER");
  });

  it("never claims someone unauthorized needs no sponsorship", () => {
    const answer = deriveWorkAuthorization("NOT_YET_AUTHORIZED", "NEVER");
    expect(answer?.sponsorshipNeed).not.toBe("NEVER");
  });

  it("writes a summary free of em dashes", () => {
    for (const option of WORK_AUTHORIZATION_STATUSES) {
      const answer = deriveWorkAuthorization(option.id, "NOW");
      expect(answer?.summary).not.toContain("—");
    }
  });

  it("rejects an unknown status", () => {
    expect(deriveWorkAuthorization("GREEN_CARD_LOTTERY" as WorkAuthorizationStatus, null)).toBeNull();
  });
});

describe("readWorkAuthorization", () => {
  it("reads a stored answer back", () => {
    const stored = { ...deriveWorkAuthorization("F1_OPT", null) } as Record<string, unknown>;
    const answer = readWorkAuthorization(stored);
    expect(answer?.status).toBe("F1_OPT");
    expect(answer?.sponsorshipNeed).toBe("FUTURE");
  });

  it("returns null for the free-text blob older profiles stored", () => {
    expect(readWorkAuthorization({ summary: "Authorized to work in the US", sponsorshipRequired: false })).toBeNull();
  });

  it("returns null for an empty or malformed field", () => {
    expect(readWorkAuthorization({})).toBeNull();
    expect(readWorkAuthorization({ status: "F1_OPT" })).toBeNull();
    expect(readWorkAuthorization({ status: 7, authorizedInUs: true, sponsorshipNeed: "NEVER" })).toBeNull();
  });
});
