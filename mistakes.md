# Mistakes

Mistakes the coding agent made while working on this repo, and the rule each
one taught. Read this before starting work; add to it when you get something
wrong. Entries say what happened, not who to blame.

## Shipping and verification

- **Pushed the Mac CI change to `main` before CI had run on it, and `main` went
  red on both OSes.** Windows failed on two new pip-audit advisories; macOS failed
  four vitest tests that hard-coded `C:\` paths and so only ever passed on
  Windows. *Rule:* a change to CI is not done until CI is green on every OS it
  adds. Get a green run on the branch (or a PR) before touching `main`, and write
  paths in tests with `path.resolve`, never a drive letter.
- **The profile readiness gate (`388f7c4`) broke the packaged smokes and nobody
  noticed until much later.** The user-flow and full e2e smokes enqueued a job
  with an empty profile, which the new gate correctly refused. *Rule:* a new
  gate on a user path needs the packaged smokes (`pnpm verify:packaged`) re-run,
  not only the unit tests.
- **Assumed the TEX fixture resume would parse into work history.** Its
  Experience section has no employer line, so the parser added no job and the
  e2e smoke still failed the HISTORY check. *Rule:* check what the parser
  actually returns for a fixture before building on it.
- **Two browser suites were run at the same time, then an hour went into
  "debugging" the hang they caused.** Concurrent `pytest -m browser` runs trip a
  browser-launch race that busy-loops forever. *Rule:* one browser suite at a
  time; rule out your own duplicate launch before diagnosing anything else.
- **Two packaging runs overlapped.** A second electron-builder wipes the first's
  `win-unpacked`, and a killed run leaves better-sqlite3 at the Electron ABI so
  vitest then fails. *Rule:* one packaging run at a time; after any aborted run,
  `node scripts/build/restore-node-native-modules.mjs`.

## Claims and documentation

- **CLAUDE.md said the audit step was red because of esbuild long after that
  stopped being the reason.** The real findings were undici, tar, postcss,
  nanoid, brace-expansion and browserslist. *Rule:* when you fix or change a
  known failure, update every doc that describes it in the same commit.
- **A research report made claims about this codebase that turned out to be
  false** (items in its section 3.1), and repeated the belief that the landing
  page download buttons 404, which they do not (GitHub redirects
  `/releases/latest` to `/releases`). *Rule:* verify a claim about the code or a
  URL before writing it down; do not carry beliefs forward from an earlier
  session.
- **Left an unmeasured number in a doc** (the size of the PyInstaller onedir
  build). *Rule:* measure it or leave it out.

## Code

- **Word PDF export never worked.** `pdf_export.py` imported `docx2pdf`, which
  was in neither `requirements.txt` nor the PyInstaller bundle, so the import
  always failed and the Word path silently fell through to "no exporter".
  *Rule:* an optional import that fails silently needs a test that proves the
  dependency is actually installed, or it should not be optional.
- **Signing-path dedupe compared raw strings.** `collectNativeBinaries` builds
  paths with backslashes while callers may pass forward slashes, so the launcher
  landed in the list twice and would be re-signed out of order on macOS.
  *Rule:* compare paths through `path.resolve`, never as strings.
- **A test fake matched the wrong script.** It keyed on `elementFromPoint`,
  which the locate script also calls, so it answered the wrong probe. *Rule:*
  match fakes on the exact, unique probe text.
- **A loop-cap fix had an edge case** that only surfaced in review. *Rule:*
  write the boundary cases (zero, cap, cap plus one) as tests before calling a
  loop fix done.
- **A security scan's exclude filter used `.venv` while the env is
  `.venv-build`**, so it walked site-packages and crashed on a non-UTF-8 file.
  *Rule:* check that exclusions match the real directory names.
- **Tried to bump pins straight in `requirements.txt`.** seleniumbase pins
  `soupsieve~=2.8.4`, so pip refused to resolve, and a full recompile would have
  moved about 80 packages. *Rule:* add the floor to `requirements.in`, then
  `pip-compile -P pkg` only for the affected subtree.

- **A `sed` swap of `pass` for a new call also rewrote an unrelated `pass`** in
  another `except` block of `playwright_adapter.py`. *Rule:* never sed-replace a
  generic line; use the Edit tool with enough context to be unique, then read
  the whole diff.
- **The Word PDF export shipped with a test that only passed on machines without
  Word.** "Nothing on PATH" stopped meaning "no exporter" once Word was found by
  install path, and CI has no Word, so only the local suite caught it. *Rule:*
  when adding a new way to find a tool, grep the tests that stub the old way.
- **The first fix for the Workday navigation failure retried the goto**, and the
  retry was interrupted by the same late error page. *Rule:* find what is
  interrupting before adding a retry; here it was Chrome committing its error
  page after goto had already raised.

## Tooling (Windows, this harness)

- **Heredocs broke on quoting, several times**, including Python heredocs whose
  bodies held `'''` or apostrophes. *Rule:* for anything longer than a few lines,
  write the script to the scratchpad with the Write tool and run the file.
- **Patch scripts failed on CRLF files, and a JS template literal lost its
  newlines.** *Rule:* normalise `\r\n` before matching, restore it on write, and
  prefer the Edit tool for exact replacements.
- **A Node patch script double-escaped backslashes** and wrote broken paths.
  *Rule:* use the Edit tool for any replacement that contains backslashes.
- **`rtk grep` over many files hung**, and `git rev-parse a b c` through rtk
  printed "fatal: Needed a single revision". *Rule:* use the Grep tool or
  `rtk proxy`; rev-parse one ref at a time.
- **The Read tool returns only line 1 in this project** (a claude-mem hook).
  Time went into trusting that "read". *Rule:* read with `cat` or `sed -n`
  through Bash; Edit still works after a Read.
- **Created a file whose name contained a colon**, which NTFS rejects. *Rule:* no
  `:` in file names; this repo is developed on Windows.
- **Called the Monitor tool without loading its schema first.** *Rule:* deferred
  tools need `ToolSearch select:<name>` before the first call.
- **A throwaway check script was written into `C:\Jobs\Codex`, outside the repo
  and the scratchpad**, through a relative `../../../` path. *Rule:* scratch files
  go in the session scratchpad, by absolute path.
- **Ran vitest from `apps/desktop`**, where it runs nothing and prints
  "PASS (0) FAIL (0)", which reads like a pass. *Rule:* run vitest from the repo
  root, and treat a zero test count as a failure.
- **A background "run the Python suite" job chained `rtk grep ... && pnpm
  test:python`.** The grep failed, the suite never ran, and the job was read as
  "still running" for a long time. *Rule:* never gate a test run on a lookup;
  run the suite on its own and check its summary line.
