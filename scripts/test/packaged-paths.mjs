import { join } from "node:path";

// Where electron-builder leaves the unpacked app. Windows gets a flat
// win-unpacked folder; a Mac gets an .app bundle in `mac-arm64` on Apple
// Silicon and in a plain `mac` on Intel, with the executable and the
// extraResources both tucked under Contents.
const appRoot = (rootDir, platform, arch) => {
  const releaseDir = join(rootDir, "apps", "desktop", "release");
  if (platform === "darwin") {
    return join(releaseDir, arch === "arm64" ? "mac-arm64" : "mac", "Applyocalypse.app", "Contents");
  }
  return join(releaseDir, "win-unpacked");
};

/**
 * @param {string} rootDir repository root
 * @param {NodeJS.Platform} [platform]
 * @param {string} [arch]
 * @returns {string} the packaged desktop executable
 */
export const packagedExecutable = (rootDir, platform = process.platform, arch = process.arch) =>
  platform === "darwin"
    ? join(appRoot(rootDir, platform, arch), "MacOS", "Applyocalypse")
    : join(appRoot(rootDir, platform, arch), "Applyocalypse.exe");

/**
 * @param {string} rootDir repository root
 * @param {NodeJS.Platform} [platform]
 * @param {string} [arch]
 * @returns {string} the folder holding automation-python and migrations
 */
export const packagedResourcesDir = (rootDir, platform = process.platform, arch = process.arch) =>
  platform === "darwin"
    ? join(appRoot(rootDir, platform, arch), "Resources")
    : join(appRoot(rootDir, platform, arch), "resources");
