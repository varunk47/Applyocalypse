const { join } = require("node:path");
const { signWorkerBinary } = require("./sign-worker-binary.cjs");

exports.default = async function afterSign(context) {
  const resourcesDir = join(context.appOutDir, "resources", "automation-python");
  const workerName = process.platform === "win32" ? "applyocalypse-worker.exe" : "applyocalypse-worker";
  const workerPath = join(resourcesDir, workerName);
  const result = await signWorkerBinary(workerPath);

  if (result.signed) {
    console.log(`Applyocalypse worker binary signed: ${result.reason}`);
    return;
  }
  console.log(`Applyocalypse worker binary signing skipped: ${result.reason}`);
};
