import { describe, expect, it } from "vitest";
import { withMacToolFolders } from "./macToolPath";

const LAUNCHD_PATH = "/usr/bin:/bin:/usr/sbin:/sbin";

describe("withMacToolFolders", () => {
  it("adds the Homebrew folders a Finder launch leaves out", () => {
    expect(withMacToolFolders("darwin", LAUNCHD_PATH)).toBe(`${LAUNCHD_PATH}:/opt/homebrew/bin:/usr/local/bin`);
  });

  it("keeps a shell launch's PATH as it is, without duplicating", () => {
    const shellPath = "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin";

    expect(withMacToolFolders("darwin", shellPath)).toBe(shellPath);
  });

  it("works from no PATH at all", () => {
    expect(withMacToolFolders("darwin", undefined)).toBe("/opt/homebrew/bin:/usr/local/bin");
  });

  it.each(["win32", "linux"] as const)("leaves %s alone", (platform) => {
    expect(withMacToolFolders(platform, "C:\\Windows")).toBe("C:\\Windows");
    expect(withMacToolFolders(platform, undefined)).toBeUndefined();
  });
});
