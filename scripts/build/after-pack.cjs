const { existsSync } = require("node:fs");
const { join } = require("node:path");

exports.default = async function afterPack(context) {
  const resourcesDir = join(context.appOutDir, "resources", "automation-python");
  const workerName = process.platform === "win32" ? "applyocalypse-worker.exe" : "applyocalypse-worker";
  const workerPath = join(resourcesDir, workerName);
  const manifestPath = join(resourcesDir, "worker-manifest.json");

  if (!existsSync(workerPath)) {
    throw new Error(`Applyocalypse worker binary is missing from packaged resources: ${workerPath}`);
  }

  if (!existsSync(manifestPath)) {
    throw new Error(`Applyocalypse worker manifest is missing from packaged resources: ${manifestPath}`);
  }
};
