// Finder and the Dock launch an app with launchd's PATH, /usr/bin:/bin:/usr/sbin:/sbin,
// which has none of the folders Homebrew installs into. A `brew install tectonic` would
// then be invisible both to the Settings diagnostic and to the worker, which inherits
// this process's environment. Apple Silicon Homebrew first, then Intel.
const MAC_TOOL_FOLDERS = ["/opt/homebrew/bin", "/usr/local/bin"];

export const withMacToolFolders = (platform: NodeJS.Platform, path: string | undefined): string | undefined => {
  if (platform !== "darwin") return path;
  const entries = (path ?? "").split(":").filter(Boolean);
  const missing = MAC_TOOL_FOLDERS.filter((folder) => !entries.includes(folder));
  return [...entries, ...missing].join(":");
};
