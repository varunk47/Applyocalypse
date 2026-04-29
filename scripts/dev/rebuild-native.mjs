import { existsSync, readdirSync } from "node:fs";
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
  run(["--filter", "@applyocalypse/desktop", "exec", "electron-rebuild", "-f", "-w", "better-sqlite3"]);
} else if (runtime === "node") {
  for (const packageDir of findBetterSqlitePackageDirs()) {
    run(["--dir", packageDir, "run", "install"]);
  }
} else {
  console.error("Usage: node scripts/dev/rebuild-native.mjs <node|electron>");
  process.exit(1);
}
