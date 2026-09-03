const { existsSync, readdirSync } = require("node:fs");
const { spawn } = require("node:child_process");
const { dirname, extname, join, resolve } = require("node:path");

const run = (command, args) =>
  new Promise((resolve, reject) => {
    const child = spawn(command, args, {
      shell: false,
      stdio: "inherit",
      windowsHide: true
    });
    child.on("error", reject);
    child.on("exit", (code) => {
      if (code === 0) {
        resolve();
        return;
      }
      reject(new Error(`${command} exited with code ${code ?? "unknown"}`));
    });
  });

const requireSigning = () => process.env.APPLYO_REQUIRE_CODE_SIGNING === "1";

// PyInstaller's onedir layout puts the launcher next to an _internal directory
// holding every DLL and extension module the process maps: 60 DLLs and 75 .pyd
// files against the one .exe. Signing the launcher alone signs 1 binary in 137,
// and WDAC and AppLocker rule on the DLL rather than on whatever loaded it.
const NATIVE_EXTENSIONS = {
  win32: new Set([".exe", ".dll", ".pyd"]),
  darwin: new Set([".dylib", ".so"])
};

const collectNativeBinaries = (rootDir, platform = process.platform) => {
  const extensions = NATIVE_EXTENSIONS[platform];
  if (!extensions || !existsSync(rootDir)) {
    return [];
  }

  const found = [];
  const walk = (dir) => {
    for (const entry of readdirSync(dir, { withFileTypes: true })) {
      const entryPath = join(dir, entry.name);
      if (entry.isDirectory()) {
        walk(entryPath);
        continue;
      }
      // isFile() is false for symlinks, which is what we want: following one
      // signs its target a second time under a name nothing loads it by.
      if (entry.isFile() && extensions.has(extname(entry.name).toLowerCase())) {
        found.push(entryPath);
      }
    }
  };

  walk(rootDir);
  return found.sort();
};

// macOS invalidates an outer signature when nested code is signed after it, so
// the launcher goes last. Windows is indifferent to the order, and one order
// that satisfies the stricter platform beats two that each satisfy one.
const planSigningTargets = (workerPath, platform = process.platform) => {
  // Compared through resolve because the walk builds paths with the platform
  // separator while a caller is free to hand us forward slashes on Windows.
  // A raw string compare misses, and the launcher lands in the list twice: once
  // from the walk and once appended, which on macOS re-signs the outer binary
  // before the inner ones and undoes the ordering this function exists for.
  const launcher = resolve(workerPath);
  const inner = collectNativeBinaries(dirname(workerPath), platform).filter((path) => resolve(path) !== launcher);
  return [...inner, workerPath];
};

// CreateProcess caps a command line at 32767 characters and signtool accepts any
// number of files, so how many fit per call is a length question rather than a
// count question. Half the cap leaves room for the fixed arguments and for a
// build agent whose output directory sits deeper than a laptop's.
const MAX_COMMAND_LENGTH = 16_000;

const batchByCommandLength = (paths, maxLength = MAX_COMMAND_LENGTH) => {
  const batches = [];
  let current = [];
  let length = 0;

  for (const path of paths) {
    const cost = path.length + 3;
    if (current.length > 0 && length + cost > maxLength) {
      batches.push(current);
      current = [];
      length = 0;
    }
    current.push(path);
    length += cost;
  }

  if (current.length > 0) {
    batches.push(current);
  }
  return batches;
};

const signWindows = async (paths) => {
  const signtoolPath = process.env.WINDOWS_SIGNTOOL_PATH;
  const certificateSha1 = process.env.WINDOWS_CERT_SHA1;
  const timestampUrl = process.env.WINDOWS_TIMESTAMP_URL || "http://timestamp.digicert.com";

  if (!signtoolPath || !certificateSha1) {
    if (requireSigning()) {
      throw new Error("WINDOWS_SIGNTOOL_PATH and WINDOWS_CERT_SHA1 are required when APPLYO_REQUIRE_CODE_SIGNING=1");
    }
    return { signed: false, reason: "windows_signing_not_configured", count: 0 };
  }

  for (const batch of batchByCommandLength(paths)) {
    await run(signtoolPath, [
      "sign",
      "/fd",
      "SHA256",
      "/tr",
      timestampUrl,
      "/td",
      "SHA256",
      "/sha1",
      certificateSha1,
      ...batch
    ]);
  }
  return { signed: true, reason: "windows_signtool", count: paths.length };
};

const signMac = async (paths) => {
  const identity = process.env.APPLE_CODESIGN_IDENTITY;
  if (!identity) {
    if (requireSigning()) {
      throw new Error("APPLE_CODESIGN_IDENTITY is required when APPLYO_REQUIRE_CODE_SIGNING=1");
    }
    return { signed: false, reason: "mac_signing_not_configured", count: 0 };
  }

  // One call per file rather than one call for the list: codesign stops at the
  // first failure without saying how far it got, and the ordering above is the
  // whole reason the list is in that order.
  for (const path of paths) {
    await run("codesign", ["--force", "--timestamp", "--options", "runtime", "--sign", identity, path]);
  }
  return { signed: true, reason: "mac_codesign", count: paths.length };
};

const signPaths = async (paths, platform) => {
  if (platform === "win32") {
    return signWindows(paths);
  }
  if (platform === "darwin") {
    return signMac(paths);
  }
  if (requireSigning()) {
    throw new Error(`Worker binary signing is not configured for platform: ${platform}`);
  }
  return { signed: false, reason: "platform_signing_not_configured", count: 0 };
};

const signWorkerTree = async (workerPath, platform = process.platform) => {
  if (!existsSync(workerPath)) {
    throw new Error(`Worker binary does not exist: ${workerPath}`);
  }

  return signPaths(planSigningTargets(workerPath, platform), platform);
};

module.exports = { batchByCommandLength, collectNativeBinaries, planSigningTargets, signWorkerTree };
