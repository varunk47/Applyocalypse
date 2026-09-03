import { createHash } from "node:crypto";
import { existsSync } from "node:fs";
import { mkdir, readFile, rm, writeFile } from "node:fs/promises";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { spawn } from "node:child_process";

const __dirname = dirname(fileURLToPath(import.meta.url));
const rootDir = resolve(__dirname, "../..");
const serviceDir = join(rootDir, "services", "automation-python");
const distDir = join(serviceDir, "dist");
const buildDir = join(serviceDir, "build");
const venvDir = join(serviceDir, ".venv-build");
const isWindows = process.platform === "win32";
const hostPython = process.env.APPLYO_PYTHON ?? (isWindows ? "python" : "python3");
const workerBinaryName = isWindows ? "applyocalypse-worker.exe" : "applyocalypse-worker";

const run = async (command, args, options = {}) => {
  await new Promise((resolvePromise, rejectPromise) => {
    const child = spawn(command, args, {
      cwd: options.cwd ?? serviceDir,
      env: process.env,
      shell: false,
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

const resolveVenvPython = () => {
  if (isWindows) {
    return join(venvDir, "Scripts", "python.exe");
  }
  return join(venvDir, "bin", "python");
};

const sha256File = async (filePath) => {
  const bytes = await readFile(filePath);
  return createHash("sha256").update(bytes).digest("hex");
};

const main = async () => {
  if (!existsSync(venvDir)) {
    await run(hostPython, ["-m", "venv", venvDir], { cwd: rootDir });
  }

  const venvPython = resolveVenvPython();
  await run(venvPython, ["-m", "pip", "install", "--upgrade", "pip"]);
  await run(venvPython, ["-m", "pip", "install", "-r", join(serviceDir, "requirements.txt")]);

  await rm(distDir, { recursive: true, force: true });
  await mkdir(distDir, { recursive: true });
  await mkdir(join(buildDir, "pyinstaller"), { recursive: true });
  await mkdir(join(buildDir, "specs"), { recursive: true });

  const hiddenImports = [
    // PDF page counting (Phase 4)
    "pypdf",
    "pypdf._reader",
    "pypdf._page",
    "pypdf.filters",
    // SeleniumBase UC Mode adapter (Phase 6.1)
    "seleniumbase",
    "seleniumbase.core.browser_launcher",
    "seleniumbase.core.download_helper",
    // Google API client — Gmail OAuth OTP (Phase 6.3)
    "googleapiclient",
    "googleapiclient.discovery",
    "googleapiclient.http",
    "google.auth",
    "google.auth.transport.requests",
    "google.oauth2.credentials",
    "google_auth_oauthlib",
    "google_auth_oauthlib.flow"
  ];

  const hiddenImportArgs = hiddenImports.flatMap((m) => ["--hidden-import", m]);

  // Patchright drives playwright_adapter.py, and hidden imports alone are not enough for
  // it: the package ships a Node driver (node.exe plus a JS package directory) that the
  // Python side spawns as a subprocess, and PyInstaller's static analysis sees only
  // Python. Without the data files the import succeeds, the launch starts a driver that
  // is not there, and the failure surfaces halfway through an application. --collect-all
  // takes the submodules and the driver tree together; PyInstaller ships a hook for
  // "playwright" but knows nothing about the fork's name.
  const collectAllArgs = ["patchright"].flatMap((pkg) => ["--collect-all", pkg]);

  await run(venvPython, [
    "-m",
    "PyInstaller",
    "--noconfirm",
    "--clean",
    // --onefile bundles everything into a single executable that unpacks itself into a
    // fresh temp directory on every launch, and this worker is 148 MB. Measured against
    // the packaged binary, that cost about 11 seconds per invocation: `self-check`, which
    // imports two browser drivers and then does nothing, took 12.9s while a full resume
    // parse took 10.9s. When doing nothing costs more than doing the work, the number is
    // startup, not workload. The desktop app spawns this worker once per document parse,
    // so every upload paid it twice over, and the packaged end-to-end smoke failed on it:
    // two parses could not finish inside that phase's 25s budget.
    //
    // --onedir writes the same binary next to its dependencies and loads them in place,
    // so the extraction happens once at build time instead of once per run. The directory
    // is what ships; electron-builder copies it to the same resources/automation-python
    // path the app already resolves, so nothing downstream changes. Same two commands
    // after the switch: self-check 2.3s, parse-source 1.1s. The trade is disk, since a
    // onedir bundle is not compressed: 148 MB of executable becomes about 376 MB of
    // directory.
    "--onedir",
    "--name",
    "applyocalypse-worker",
    "--paths",
    serviceDir,
    "--distpath",
    distDir,
    "--workpath",
    join(buildDir, "pyinstaller"),
    "--specpath",
    join(buildDir, "specs"),
    ...hiddenImportArgs,
    ...collectAllArgs,
    join(serviceDir, "applyocalypse_worker_entry.py")
  ]);

  const bundleDir = join(distDir, "applyocalypse-worker");
  const binaryPath = join(bundleDir, workerBinaryName);
  if (!existsSync(binaryPath)) {
    throw new Error(`PyInstaller finished without producing ${binaryPath}`);
  }

  const manifest = {
    product: "Applyocalypse",
    artifact: "automation-worker",
    entry: workerBinaryName,
    platform: process.platform,
    arch: process.arch,
    sha256: await sha256File(binaryPath),
    createdAt: new Date().toISOString()
  };

  await writeFile(join(bundleDir, "worker-manifest.json"), `${JSON.stringify(manifest, null, 2)}\n`, "utf8");
};

main().catch((error) => {
  console.error(error instanceof Error ? error.message : error);
  process.exit(1);
});
