import { existsSync, readFileSync, readdirSync } from "node:fs";
import { join, resolve } from "node:path";
import { spawnSync } from "node:child_process";

const runtime = process.argv[2];
const rootDir = resolve(import.meta.dirname, "..", "..");
const pnpmStoreDir = join(rootDir, "node_modules", ".pnpm");

const run = (args, options = {}) => {
  const command = "corepack";
  const result = spawnSync(command, ["pnpm", ...args], {
    cwd: rootDir,
    stdio: "inherit",
    shell: process.platform === "win32",
    ...options,
  });

  if (result.status !== 0) {
    process.exit(result.status ?? 1);
  }
};

// node-gyp is a transitive dependency, so pnpm never links it into a `.bin`
// directory on PATH. Spawning a bare "node-gyp" therefore only works when some
// unrelated toolchain happens to have put one there. Resolve the real
// entrypoint out of the store instead.
const findNodeGypScript = () => {
  if (!existsSync(pnpmStoreDir)) return null;
  const candidates = readdirSync(pnpmStoreDir)
    .filter((entry) => entry.startsWith("node-gyp@"))
    .map((entry) => join(pnpmStoreDir, entry, "node_modules", "node-gyp", "bin", "node-gyp.js"))
    .filter((candidate) => existsSync(candidate));
  return candidates[0] ?? null;
};

const findBetterSqlitePackageDirs = () => {
  if (!existsSync(pnpmStoreDir)) {
    throw new Error(`pnpm store directory not found: ${pnpmStoreDir}`);
  }

  const packageDirs = readdirSync(pnpmStoreDir)
    .filter((entry) => entry.startsWith("better-sqlite3@"))
    .map((entry) => join(pnpmStoreDir, entry, "node_modules", "better-sqlite3"))
    .filter((candidate) => existsSync(join(candidate, "package.json")));

  if (packageDirs.length === 0) {
    throw new Error("better-sqlite3 package directory not found in pnpm store");
  }

  return packageDirs;
};

if (runtime === "electron") {
  // electron-rebuild traverses the full workspace tree and finds both
  // better-sqlite3@11.10.0 (via @applyocalypse/db) and @12.10.0. @11.10.0
  // uses v8::Context::GetIsolate() removed in Electron 39's V8 and cannot be
  // compiled against Electron headers. We bypass electron-rebuild entirely
  // and call prebuild-install directly on @12.10.0 with the Electron runtime,
  // which downloads the prebuilt binary compiled against the correct Electron ABI.
  const sqlite3v12Dir = findBetterSqlitePackageDirs().find((dir) => /better-sqlite3@12\./.test(dir));
  if (!sqlite3v12Dir) {
    console.error(`better-sqlite3@12.x not found in the pnpm store: ${pnpmStoreDir}`);
    process.exit(1);
  }

  const electronPkgPath = join(rootDir, "apps", "desktop", "node_modules", "electron", "package.json");
  if (!existsSync(electronPkgPath)) {
    console.error(`Electron package.json not found at: ${electronPkgPath}`);
    process.exit(1);
  }
  const electronVersion = JSON.parse(readFileSync(electronPkgPath, "utf8")).version;
  console.log(`Rebuilding ${sqlite3v12Dir} for Electron ${electronVersion}`);

  const prebuildInstall = join(sqlite3v12Dir, "node_modules", ".bin", "prebuild-install");
  const result = spawnSync(
    prebuildInstall,
    [
      "--runtime", "electron",
      "--target", electronVersion,
      "--tag-prefix", "v",
      "--force",
    ],
    {
      cwd: sqlite3v12Dir,
      stdio: "inherit",
      shell: process.platform === "win32",
    }
  );

  if (result.status !== 0) {
    console.error("prebuild-install failed, falling back to node-gyp...");
    const nodeGypScript = findNodeGypScript();
    if (!nodeGypScript) {
      console.error(`node-gyp not found in the pnpm store: ${pnpmStoreDir}`);
      process.exit(1);
    }
    const nodeGyp = spawnSync(
      process.execPath,
      [nodeGypScript, "rebuild", "--release"],
      {
        cwd: sqlite3v12Dir,
        stdio: "inherit",
        shell: false,
        env: {
          ...process.env,
          npm_config_runtime: "electron",
          npm_config_target: electronVersion,
          npm_config_dist_url: "https://www.electronjs.org/headers",
        },
      }
    );
    if (nodeGyp.status !== 0) {
      process.exit(nodeGyp.status ?? 1);
    }
  }
} else if (runtime === "node") {
  // Rebuild only the Node.js-compatible version; 12.x is handled by the
  // electron branch and must not be compiled against Node.js ABI.
  for (const packageDir of findBetterSqlitePackageDirs().filter(
    (d) => !/better-sqlite3@12\./.test(d)
  )) {
    run(["--dir", packageDir, "run", "install"]);
  }
} else {
  console.error("Usage: node scripts/dev/rebuild-native.mjs <node|electron>");
  process.exit(1);
}
