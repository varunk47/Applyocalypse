import { describe, expect, it, vi } from "vitest";
import { resolveAllowedArtifactPath } from "./artifactProtocol";

vi.mock("electron", () => ({
  net: { fetch: vi.fn() },
  protocol: {
    handle: vi.fn(),
    registerSchemesAsPrivileged: vi.fn()
  }
}));

describe("artifact protocol authorization", () => {
  it("allows DB-known artifact paths without granting the whole containing folder", () => {
    const knownPath = "C:\\Users\\Ada\\Downloads\\Grace Hopper Example Resume.pdf";
    const unrelatedPath = "C:\\Users\\Ada\\Downloads\\Bank Statement.pdf";
    const options = {
      isAllowedPath: (localPath: string) => localPath === knownPath
    };

    expect(resolveAllowedArtifactPath(knownPath, options)).toBe(knownPath);
    expect(resolveAllowedArtifactPath(unrelatedPath, options)).toBeNull();
  });

  it("rejects relative paths and paths with NUL characters", () => {
    expect(resolveAllowedArtifactPath("..\\secret.png", { isAllowedPath: () => true })).toBeNull();
    expect(resolveAllowedArtifactPath("C:\\Users\\Ada\\Downloads\\bad\0name.png", { isAllowedPath: () => true })).toBeNull();
  });
});
