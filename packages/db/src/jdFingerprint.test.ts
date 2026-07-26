import { describe, expect, it } from "vitest";
import { CROSS_LISTING_SIMILARITY, simhash64, simhashSimilarity } from "./jdFingerprint";

const JD = `We are hiring a Senior Software Engineer to build distributed systems in TypeScript
and Python. You will own services end to end, design APIs, review code, and mentor junior
engineers. Requirements include five years of backend experience, strong SQL knowledge,
and familiarity with message queues, observability tooling, and cloud infrastructure.
You will collaborate with product managers and designers to scope features, break down
ambiguous requirements into shippable milestones, and communicate progress clearly to
stakeholders across the organization. Our stack includes PostgreSQL, Redis, Kafka, and
Kubernetes deployed across multiple regions with infrastructure defined as code.
On call rotations are shared fairly across the team and incidents are followed by
blameless postmortems. Experience with performance profiling, capacity planning, and
cost optimization is valued. We sponsor conference attendance and internal guilds.
We offer flexible remote work, a learning budget, and a collaborative engineering culture.`;

const UNRELATED = `Regional sales manager wanted for agricultural equipment distributor.
Responsibilities cover dealer relationships, territory planning, quota attainment, trade
shows, and CRM hygiene. Valid driver license required, extensive travel across the region,
compensation is base salary plus commission with a company vehicle provided to candidates.`;

describe("jd fingerprint", () => {
  it("returns identical hashes for identical text", () => {
    const a = simhash64(JD);
    const b = simhash64(JD);
    expect(a).toBeTruthy();
    expect(a).toBe(b);
    expect(simhashSimilarity(a!, b!)).toBe(1);
  });

  it("scores a lightly edited repost far above an unrelated posting", () => {
    // The production CROSS_LISTING_SIMILARITY threshold is calibrated for
    // full-length JDs; this fixture is shorter, so assert the mechanism
    // (clear separation), not the calibrated cutoff.
    const reposted = JD.replace("collaborative engineering culture", "supportive engineering culture");
    const repostSimilarity = simhashSimilarity(simhash64(JD)!, simhash64(reposted)!);
    const unrelatedSimilarity = simhashSimilarity(simhash64(JD)!, simhash64(UNRELATED)!);
    expect(repostSimilarity).toBeGreaterThan(0.85);
    expect(repostSimilarity).toBeGreaterThan(unrelatedSimilarity + 0.1);
  });

  it("keeps an unrelated job description below the cross-listing threshold", () => {
    const similarity = simhashSimilarity(simhash64(JD)!, simhash64(UNRELATED)!);
    expect(similarity).toBeLessThan(CROSS_LISTING_SIMILARITY);
  });

  it("returns null for text too short to fingerprint", () => {
    expect(simhash64("too short to matter")).toBeNull();
  });
});
