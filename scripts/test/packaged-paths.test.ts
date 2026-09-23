import { join } from "node:path";
import { describe, expect, it } from "vitest";

import { packagedExecutable, packagedResourcesDir } from "./packaged-paths.mjs";

const RELEASE = join("root", "apps", "desktop", "release");

describe("packaged app paths", () => {
  it("finds the Windows build in win-unpacked", () => {
    expect(packagedExecutable("root", "win32", "x64")).toBe(join(RELEASE, "win-unpacked", "Applyocalypse.exe"));
    expect(packagedResourcesDir("root", "win32", "x64")).toBe(join(RELEASE, "win-unpacked", "resources"));
  });

  it("looks inside the .app bundle on an Apple Silicon Mac", () => {
    const bundle = join(RELEASE, "mac-arm64", "Applyocalypse.app", "Contents");

    expect(packagedExecutable("root", "darwin", "arm64")).toBe(join(bundle, "MacOS", "Applyocalypse"));
    expect(packagedResourcesDir("root", "darwin", "arm64")).toBe(join(bundle, "Resources"));
  });

  it("uses electron-builder's unsuffixed mac folder for an Intel Mac", () => {
    const bundle = join(RELEASE, "mac", "Applyocalypse.app", "Contents");

    expect(packagedExecutable("root", "darwin", "x64")).toBe(join(bundle, "MacOS", "Applyocalypse"));
    expect(packagedResourcesDir("root", "darwin", "x64")).toBe(join(bundle, "Resources"));
  });
});
