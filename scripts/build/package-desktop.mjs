import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { spawn } from "node:child_process";

const __dirname = dirname(fileURLToPath(import.meta.url));
const rootDir = resolve(__dirname, "../..");
const pnpm = process.platform === "win32" ? "pnpm.cmd" : "pnpm";
const node = process.execPath;

const run = async (command, args, cwd = rootDir) => {
  await new Promise((resolvePromise, rejectPromise) => {
    const child = spawn(command, args, {
      cwd,
      env: process.env,
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

const main = async () => {
  let packageError = null;
  try {
    await run(pnpm, ["--filter", "@applyocalypse/desktop", "package:raw"]);
  } catch (error) {
    packageError = error;
  } finally {
    await run(node, ["scripts/build/restore-node-native-modules.mjs"]);
  }

  if (packageError) {
    throw packageError;
  }
};

main().catch((error) => {
  console.error(error instanceof Error ? error.message : error);
  process.exit(1);
});
