# Dependency licences

Applyocalypse ships as a signed desktop binary with a PyInstaller-packaged Python
worker inside it. That is distribution, and distribution is what makes copyleft
bite: a strong-copyleft library linked into the binary carries its terms to the
whole work. Finding that out after release means relicensing the product or
pulling it, so the rule is checked by `pnpm licenses:check` alongside the other
gates rather than left as prose someone is supposed to remember.

## The rule

| Class | Examples | May be added |
|-------|----------|--------------|
| Permissive | MIT, ISC, BSD, Apache-2.0, 0BSD, Unlicense, PSF, Zlib | Yes, without asking |
| File-level copyleft | MPL-2.0, EPL-2.0, CDDL-1.0 | Yes, **unmodified**. The obligation covers the licensed files, not the program they are bundled with. Patching one in place ends that. |
| Strong copyleft | GPL, AGPL, LGPL, SSPL, BUSL, Commons Clause | No, unless recorded as an exception below with the reason |
| Unknown / non-OSI | anything the checker cannot classify | No, until someone reads the licence and decides |

Build-time tools are judged separately from shipped code: a GPL tool that is never
imported at runtime and never lands in the binary does not reach the shipped work.
That distinction is the reason for most of the exceptions, and it stops being true
the moment a build tool starts being bundled.

## How it is enforced

`scripts/test/license-check.mjs` reads the production JS tree (`pnpm licenses list
--prod`) and every distribution installed in the worker's `.venv-build`, classifies
each licence, and exits non-zero on anything in the last two rows that is not a
recorded exception. It runs as part of `pnpm verify`.

Adding a dependency whose licence the checker will not accept means one of three
things, in order of preference:

1. Use a permissively licensed alternative.
2. Show the dependency never reaches the shipped binary, and record that.
3. Change what Applyocalypse itself is licensed under.

Adding it to the `EXCEPTIONS` map without reading the licence is not one of them.
An exception is a decision on the record, and that is the only thing separating it
from the rule not being enforced.

## Exceptions on the record

The authoritative copies live in `EXCEPTIONS` in the checker, each with a reason
and, where relevant, what has to be settled before release. Summarised:

- **nodriver (AGPL-3.0) — OPEN.** The first browser engine tried by
  `adapter_factory`, bundled into the PyInstaller binary. Distributing that binary
  as things stand would put the whole application under AGPL-3.0. Personal,
  undistributed use triggers no obligation, so this blocks release, not
  development. Resolving it means dropping nodriver for patchright (Apache-2.0) or
  seleniumbase (MIT), or releasing Applyocalypse itself under AGPL-3.0.
- **pyinstaller (GPLv2-or-later).** Carries the author's explicit exception
  permitting the building and distribution of non-free programs. A build tool:
  never imported at runtime.
- **pyinstaller-hooks-contrib.** Dual Apache-2.0 or GPL-2.0, taken under the
  Apache half. Build tooling.
- **pynose (LGPL).** Reached only through seleniumbase, the third-choice engine.
  LGPL permits distribution alongside a proprietary work; it is recorded so the
  dependency is not mistaken for permissive.
- **gsap.** Not an OSI licence. GSAP's standard no-charge licence covers animation
  inside an app that is not itself sold as an animation tool. Confirm the terms
  still cover a paid desktop product before charging for one.

## Before release

Both `verifyBeforeRelease` notes above are release blockers, not suggestions:
settle nodriver, and re-read the GSAP terms if the app is ever sold.
