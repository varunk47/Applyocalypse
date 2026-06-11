import { existsSync, readFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { spawnSync } from "node:child_process";

const rootDir = resolve(import.meta.dirname, "../..");
const desktopDir = join(rootDir, "apps", "desktop");
const releaseDir = join(desktopDir, "release");
const packagedExe = process.platform === "win32" ? join(releaseDir, "win-unpacked", "Applyocalypse.exe") : join(releaseDir, "Applyocalypse");
const requireReady = process.env.APPLYO_REQUIRE_RELEASE_READY === "1";

const checkGit = () => {
  const inside = spawnSync("git", ["-C", rootDir, "rev-parse", "--is-inside-work-tree"], { encoding: "utf8" });
  if (inside.status !== 0 || inside.stdout.trim() !== "true") {
    return { ok: false, blocker: "applyocalypse_is_not_a_git_repository" };
  }
  const remote = spawnSync("git", ["-C", rootDir, "remote", "get-url", "origin"], { encoding: "utf8" });
  if (remote.status !== 0 || !remote.stdout.trim()) {
    return { ok: false, blocker: "origin_remote_missing" };
  }
  const status = spawnSync("git", ["-C", rootDir, "status", "--short", "--untracked-files=no"], { encoding: "utf8" });
  return {
    ok: true,
    origin: remote.stdout.trim(),
    dirty: Boolean(status.stdout.trim())
  };
};

const hasSigningConfig = () => {
  if (process.platform === "win32") {
    return Boolean(process.env.WINDOWS_SIGNTOOL_PATH && process.env.WINDOWS_CERT_SHA1);
  }
  if (process.platform === "darwin") {
    return Boolean(process.env.APPLE_CODESIGN_IDENTITY);
  }
  return true;
};

const checks = [
  { id: "packaged_executable", ok: existsSync(packagedExe), detail: packagedExe },
  {
    id: "worker_signing_config",
    ok: hasSigningConfig(),
    blocker: process.platform === "win32" ? "WINDOWS_SIGNTOOL_PATH_or_WINDOWS_CERT_SHA1_missing" : "APPLE_CODESIGN_IDENTITY_missing"
  },
  { id: "release_readiness_doc", ok: existsSync(join(rootDir, "docs", "release-readiness.md")) },
  { id: "live_certification_targets_template", ok: existsSync(join(rootDir, "certification", "live-portal-targets.example.json")) },
  { id: "electron_builder_config", ok: readFileSync(join(desktopDir, "electron-builder", "electron-builder.yml"), "utf8").includes("afterSign") }
];

const git = checkGit();
checks.push({ id: "git_repository", ok: git.ok, blocker: git.blocker, detail: git.origin });
checks.push({ id: "git_worktree_clean", ok: git.ok && git.dirty === false, blocker: git.dirty ? "worktree_has_uncommitted_changes" : git.blocker });

const payload = {
  report_type: "RELEASE_PREFLIGHT",
  require_ready: requireReady,
  platform: process.platform,
  packaged_executable: packagedExe,
  checks
};

console.log(JSON.stringify(payload, null, 2));

if (requireReady && checks.some((check) => !check.ok)) {
  process.exit(1);
}
