const { existsSync } = require("node:fs");
const { join, resolve } = require("node:path");
const { brandWindowsExecutable } = require("./brand-windows-executable.cjs");

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

  const migrationsDir = join(context.appOutDir, "resources", "migrations");
  const initialMigrationPath = join(migrationsDir, "0001_initial.sql");
  if (!existsSync(initialMigrationPath)) {
    throw new Error(`Applyocalypse SQLite migrations are missing from packaged resources: ${migrationsDir}`);
  }

  if (context.electronPlatformName !== "win32") {
    return;
  }

  // electron-builder skips its own rcedit pass because signAndEditExecutable is
  // off; see scripts/build/brand-windows-executable.cjs for why. Without this
  // the app wears Electron's logo and calls itself Electron everywhere Windows
  // shows a program to a person.
  const { appInfo } = context.packager;
  const executablePath = join(context.appOutDir, `${appInfo.productFilename}.exe`);
  if (!existsSync(executablePath)) {
    throw new Error(`Applyocalypse executable is missing from the packaged output: ${executablePath}`);
  }

  const iconPath = resolve(__dirname, "..", "..", "apps", "desktop", "electron-builder", "icon.ico");
  if (!existsSync(iconPath)) {
    throw new Error(
      `Application icon is missing: ${iconPath}. Rebuild it with scripts/build/generate-app-icon.mjs.`
    );
  }

  await brandWindowsExecutable({
    executablePath,
    iconPath,
    productName: appInfo.productName,
    version: appInfo.version,
    description: appInfo.description || appInfo.productName,
    copyright: appInfo.copyright,
    companyName: appInfo.companyName || undefined
  });
};
