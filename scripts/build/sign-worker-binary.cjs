const { existsSync } = require("node:fs");
const { spawn } = require("node:child_process");

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

const signWindows = async (workerPath) => {
  const signtoolPath = process.env.WINDOWS_SIGNTOOL_PATH;
  const certificateSha1 = process.env.WINDOWS_CERT_SHA1;
  const timestampUrl = process.env.WINDOWS_TIMESTAMP_URL || "http://timestamp.digicert.com";

  if (!signtoolPath || !certificateSha1) {
    if (requireSigning()) {
      throw new Error("WINDOWS_SIGNTOOL_PATH and WINDOWS_CERT_SHA1 are required when APPLYO_REQUIRE_CODE_SIGNING=1");
    }
    return { signed: false, reason: "windows_signing_not_configured" };
  }

  await run(signtoolPath, ["sign", "/fd", "SHA256", "/tr", timestampUrl, "/td", "SHA256", "/sha1", certificateSha1, workerPath]);
  return { signed: true, reason: "windows_signtool" };
};

const signMac = async (workerPath) => {
  const identity = process.env.APPLE_CODESIGN_IDENTITY;
  if (!identity) {
    if (requireSigning()) {
      throw new Error("APPLE_CODESIGN_IDENTITY is required when APPLYO_REQUIRE_CODE_SIGNING=1");
    }
    return { signed: false, reason: "mac_signing_not_configured" };
  }

  await run("codesign", ["--force", "--timestamp", "--options", "runtime", "--sign", identity, workerPath]);
  return { signed: true, reason: "mac_codesign" };
};

const signWorkerBinary = async (workerPath, platform = process.platform) => {
  if (!existsSync(workerPath)) {
    throw new Error(`Worker binary does not exist: ${workerPath}`);
  }

  if (platform === "win32") {
    return signWindows(workerPath);
  }
  if (platform === "darwin") {
    return signMac(workerPath);
  }
  if (requireSigning()) {
    throw new Error(`Worker binary signing is not configured for platform: ${platform}`);
  }
  return { signed: false, reason: "platform_signing_not_configured" };
};

module.exports = { signWorkerBinary };
