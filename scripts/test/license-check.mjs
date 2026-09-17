/**
 * Dependency licence gate.
 *
 * Applyocalypse is distributed as a signed desktop binary with a Python worker
 * bundled inside it. Distribution is what makes copyleft bite: a strong
 * copyleft library linked into that binary carries its terms to the whole work.
 * Finding that out after release means either relicensing the product or
 * pulling it, so the check runs with the rest of the gates instead.
 *
 * The rule, in full, is docs/dependency-licenses.md. This file enforces it.
 */
import { spawn } from "node:child_process";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const rootDir = resolve(dirname(fileURLToPath(import.meta.url)), "../..");
const serviceDir = join(rootDir, "services", "automation-python");
const venvPython =
  process.platform === "win32"
    ? join(serviceDir, ".venv-build", "Scripts", "python.exe")
    : join(serviceDir, ".venv-build", "bin", "python");

/** Licences that may be added without anyone being asked. */
const PERMISSIVE = [
  "0BSD", "APACHE", "BSD",
  "BSD-2-CLAUSE", "BSD-3-CLAUSE", "BSD 3-CLAUSE", "CC0-1.0", "ISC", "MIT",
  "MIT LICENSE", "MIT-0", "PSF", "PSF-2.0", "PSFL", "PYTHON-2.0",
  "UNLICENSE", "WTFPL", "ZLIB"
];

/**
 * File-level copyleft. Safe to ship unmodified, because the obligation covers
 * the licensed files themselves and not the program they are bundled with. If
 * we ever patch one of these in place, it stops being safe.
 */
const FILE_LEVEL_COPYLEFT = ["MPL-2.0", "MOZILLA PUBLIC LICENSE 2.0", "EPL-2.0", "CDDL-1.0"];

/** Carries its terms to anything it is linked into. Needs a decision, not a shrug. */
const STRONG_COPYLEFT = [
  "AGPL", "GPL-2.0", "GPL-3.0", "GPLV2", "GPLV3",
  "GNU GENERAL PUBLIC", "GNU AFFERO", "LGPL", "GNU LGPL", "GNU LIBRARY",
  "SSPL", "BUSL", "COMMONS CLAUSE"
];

/**
 * Packages allowed past the rule, each with the reason it is allowed and, where
 * the reason is "not resolved yet", what has to happen before release.
 *
 * Nothing is added here without reading the licence. An entry is a decision on
 * the record, which is the only thing that makes the exception different from
 * the rule not being enforced.
 */
const EXCEPTIONS = {
  pyinstaller: {
    reason:
      "GPLv2-or-later with the author's explicit exception permitting the building " +
      "and distribution of non-free programs. A build tool: never imported at runtime " +
      "and not part of the shipped work.",
    resolved: true
  },
  gsap: {
    reason:
      "Not an OSI licence. GSAP's standard no-charge licence covers the use made of " +
      "it here (animation in an app that is not itself sold as an animation tool).",
    resolved: true,
    verifyBeforeRelease:
      "Confirm the no-charge terms still cover a paid desktop product before charging for one."
  },
  nodriver: {
    reason:
      "AGPL-3.0, and currently the FIRST browser engine tried by adapter_factory. " +
      "Bundled into the PyInstaller binary, so distributing that binary would put the " +
      "whole application under AGPL-3.0.",
    resolved: false,
    verifyBeforeRelease:
      "Decide before the app is distributed: drop nodriver in favour of patchright " +
      "(Apache-2.0) or seleniumbase (MIT), or release Applyocalypse itself under AGPL-3.0. " +
      "Personal, undistributed use triggers neither obligation."
  },
  "pyinstaller-hooks-contrib": {
    reason:
      "Dual Apache-2.0 or GPL-2.0, the same arrangement as PyInstaller itself, and " +
      "taken under the Apache half. Build tooling, not part of the shipped work.",
    resolved: true
  },
  pynose: {
    reason:
      "LGPL, reached only through seleniumbase, which is the third-choice engine. " +
      "LGPL permits distribution alongside a proprietary work; it is listed so the " +
      "dependency is not mistaken for permissive.",
    resolved: true
  }
};

const classify = (raw) => {
  const text = (raw || "").toUpperCase();
  if (!text.trim()) return "UNKNOWN";
  // Checked first: "GPL" appears inside "LGPL", and a dual offer such as
  // "MIT OR GPL-2.0" is satisfiable under the permissive half.
  const permissive = PERMISSIVE.some((id) => text.includes(id));
  if (STRONG_COPYLEFT.some((id) => text.includes(id))) {
    return permissive && / OR /.test(text) ? "PERMISSIVE" : "STRONG_COPYLEFT";
  }
  if (FILE_LEVEL_COPYLEFT.some((id) => text.includes(id))) return "FILE_LEVEL_COPYLEFT";
  if (permissive) return "PERMISSIVE";
  return "UNKNOWN";
};

const capture = (command, args, options = {}) =>
  new Promise((resolvePromise, rejectPromise) => {
    const child = spawn(command, args, {
      cwd: options.cwd ?? rootDir,
      env: process.env,
      // pnpm is a .cmd on Windows, which Node will only start through a shell.
      // The arguments here are all literals, so there is nothing to quote.
      shell: options.shell ?? false,
      windowsHide: true,
      stdio: ["ignore", "pipe", "pipe"]
    });
    let stdout = "";
    let stderr = "";
    child.stdout.on("data", (chunk) => (stdout += chunk));
    child.stderr.on("data", (chunk) => (stderr += chunk));
    child.on("error", rejectPromise);
    child.on("exit", (code) =>
      code === 0
        ? resolvePromise(stdout)
        : rejectPromise(new Error(`${command} exited with ${code}\n${stderr}`))
    );
  });

const PYTHON_PROBE = `
import json
from importlib.metadata import distributions
rows = []
for dist in distributions():
    meta = dist.metadata
    name = meta["Name"]
    if not name:
        continue
    licence = meta["License-Expression"] or meta["License"] or ""
    classifiers = [c for c in (meta.get_all("Classifier") or []) if c.startswith("License ::")]
    rows.append({"name": name, "license": licence[:200], "classifiers": classifiers})
print(json.dumps(rows))
`;

const collect = async () => {
  const found = [];

  const jsRaw = await capture("pnpm", ["licenses", "list", "--prod", "--json"], {
    shell: process.platform === "win32"
  });
  for (const [licence, packages] of Object.entries(JSON.parse(jsRaw))) {
    for (const pkg of packages) found.push({ ecosystem: "js", name: pkg.name, licence });
  }

  const pyRaw = await capture(venvPython, ["-c", PYTHON_PROBE], { cwd: serviceDir });
  for (const row of JSON.parse(pyRaw)) {
    // The classifiers are often more truthful than the free-text field, which
    // several packages fill with the entire licence text.
    const licence = [row.license, ...row.classifiers].join(" ");
    found.push({ ecosystem: "python", name: row.name, licence });
  }

  return found;
};

const main = async () => {
  const packages = await collect();
  const violations = [];
  const allowed = [];

  for (const pkg of packages) {
    const verdict = classify(pkg.licence);
    if (verdict === "PERMISSIVE" || verdict === "FILE_LEVEL_COPYLEFT") continue;
    const exception = EXCEPTIONS[pkg.name.toLowerCase()];
    if (exception) allowed.push({ ...pkg, verdict, exception });
    else violations.push({ ...pkg, verdict });
  }

  console.log(`Checked ${packages.length} packages against docs/dependency-licenses.md`);

  if (allowed.length > 0) {
    console.log("\nRecorded exceptions:");
    for (const item of allowed) {
      const mark = item.exception.resolved ? "ok " : "OPEN";
      console.log(`  [${mark}] ${item.name} (${item.verdict}) - ${item.exception.reason}`);
      if (item.exception.verifyBeforeRelease) {
        console.log(`         before release: ${item.exception.verifyBeforeRelease}`);
      }
    }
  }

  if (violations.length > 0) {
    console.error("\nDependencies with no recorded decision:");
    for (const item of violations) {
      console.error(`  ${item.name} [${item.ecosystem}] ${item.verdict}: ${item.licence.slice(0, 90)}`);
    }
    console.error(
      "\nRead the licence, then either drop the dependency or add it to EXCEPTIONS " +
        "in scripts/test/license-check.mjs with the reason it is acceptable."
    );
    process.exit(1);
  }

  console.log("\nNo undecided licences.");
};

main().catch((error) => {
  console.error(error instanceof Error ? error.message : error);
  process.exit(1);
});
