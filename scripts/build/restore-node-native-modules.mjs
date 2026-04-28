import { existsSync, rmSync } from "node:fs";
import { readdir } from "node:fs/promises";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { spawn } from "node:child_process";

const __dirname = dirname(fileURLToPath(import.meta.url));
const rootDir = resolve(__dirname, "../..");
const pnpmStoreDir = join(rootDir, "node_modules", ".pnpm");
const pnpm = process.platform === "win32" ? "pnpm.cmd" : "pnpm";
const nodeGypBin = process.platform === "win32" ? "node-gyp.CMD" : "node-gyp";

const run = async (command, args, cwd, extraEnv = {}) => {
  await new Promise((resolvePromise, rejectPromise) => {
    const child = spawn(command, args, {
      cwd,
      env: {
        ...process.env,
        ...extraEnv
      },
      shell: process.platform === "win32",
      stdio: "inherit",
      windowsHide: true
    });
    child.on("error", rejectPromise);
    child.on("exit", (code) => {
      if (code === 0) {
        resolvePromise();
        return;
      }
      rejectPromise(new Error(`${command} ${args.join(" ")} exited with ${code}`));
    });
  });
};

const findNodeGyp = () => {
  const candidates = [
    join(rootDir, "node_modules", ".pnpm", "node_modules", ".bin", nodeGypBin),
    join(rootDir, "node_modules", ".bin", nodeGypBin)
  ];
  return candidates.find((candidate) => existsSync(candidate));
};

const main = async () => {
  if (!existsSync(pnpmStoreDir)) {
    return;
  }

  const entries = await readdir(pnpmStoreDir);
  const betterSqliteEntries = entries.filter((entry) => entry.startsWith("better-sqlite3@"));
  if (betterSqliteEntries.length === 0) {
    return;
  }

  const nodeGyp = findNodeGyp();

  for (const betterSqliteEntry of betterSqliteEntries) {
    const packageDir = join(pnpmStoreDir, betterSqliteEntry, "node_modules", "better-sqlite3");
    if (!existsSync(packageDir)) {
      continue;
    }

    rmSync(join(packageDir, "build"), { recursive: true, force: true });

    if (nodeGyp) {
      await run(nodeGyp, ["rebuild", "--release"], packageDir, {
        npm_config_runtime: "node",
        npm_config_target: process.versions.node,
        npm_config_disturl: "https://nodejs.org/download/release"
      });
      continue;
    }

    await run(pnpm, ["exec", "prebuild-install", "--runtime", "node", "--force"], packageDir);
  }
};

main().catch((error) => {
  console.error(error instanceof Error ? error.message : error);
  process.exit(1);
});
