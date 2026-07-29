// The landing page has no build step, so nothing catches a reference to a file
// that was renamed or never committed: the deploy succeeds and the page loads
// with no fonts and no animation. This walks every local reference in the HTML
// and CSS and fails if one does not resolve.
//
// It also enforces the site's own promise. The README says every asset is
// self-hosted so the page works offline and leaks nothing; a stylesheet, script,
// font, or image pulled from another origin would quietly break that, and a
// visitor's IP would reach a third party before they clicked anything.
import { existsSync, readFileSync } from "node:fs";
import { dirname, join, normalize, resolve } from "node:path";

const landingDir = resolve(import.meta.dirname, "..", "..", "landing");

// Documents that carry references. Relative URLs resolve against the document
// that holds them: CSS url() is relative to the stylesheet, not to the page.
const SOURCES = [
  join(landingDir, "index.html"),
  join(landingDir, "styles.css"),
  join(landingDir, "main.js"),
];

const REFERENCE_PATTERNS = [
  /\b(?:href|src)\s*=\s*["']([^"']+)["']/gi,
  /url\(\s*["']?([^"')]+)["']?\s*\)/gi,
];

// Off-origin schemes that fetch something at render time. data: and blob: are
// inline, and mailto:/tel: open an app rather than loading a subresource.
const REMOTE_SCHEME = /^(?:https?:)?\/\//i;
// `%23` is an encoded `#`: CSS filter references are written that way so the
// fragment survives the url() token. Both forms point inside the document.
const INERT_SCHEME = /^(?:data:|blob:|mailto:|tel:|javascript:|#|%23)/i;

// Links a visitor clicks are allowed off-origin; subresources the browser
// fetches on its own are not. Only the latter can leak an IP unprompted.
const collectRemoteSubresources = (html) => {
  const offenders = [];
  const tagPattern = /<(link|script|img|source|video|audio|iframe|embed)\b[^>]*>/gi;
  for (const [tag] of html.matchAll(tagPattern)) {
    for (const pattern of REFERENCE_PATTERNS) {
      pattern.lastIndex = 0;
      for (const [, reference] of tag.matchAll(pattern)) {
        if (REMOTE_SCHEME.test(reference)) offenders.push(reference);
      }
    }
  }
  return offenders;
};

const missing = [];
const remote = [];

for (const file of SOURCES) {
  if (!existsSync(file)) {
    missing.push(`${file} (source document itself)`);
    continue;
  }
  const contents = readFileSync(file, "utf8");

  if (file.endsWith(".html")) {
    remote.push(...collectRemoteSubresources(contents).map((r) => `${file}: ${r}`));
  } else {
    for (const pattern of REFERENCE_PATTERNS) {
      pattern.lastIndex = 0;
      for (const [, reference] of contents.matchAll(pattern)) {
        if (REMOTE_SCHEME.test(reference)) remote.push(`${file}: ${reference}`);
      }
    }
  }

  for (const pattern of REFERENCE_PATTERNS) {
    pattern.lastIndex = 0;
    for (const [, raw] of contents.matchAll(pattern)) {
      if (REMOTE_SCHEME.test(raw) || INERT_SCHEME.test(raw)) continue;
      // Strip the query/fragment: cache-busting suffixes are not part of the path.
      const reference = raw.split(/[?#]/)[0];
      if (!reference) continue;
      const resolved = reference.startsWith("/")
        ? join(landingDir, reference)
        : join(dirname(file), reference);
      const withinLanding = normalize(resolved).startsWith(normalize(landingDir));
      if (!withinLanding) {
        missing.push(`${file}: ${raw} (escapes the landing folder)`);
        continue;
      }
      if (!existsSync(resolved)) missing.push(`${file}: ${raw}`);
    }
  }
}

if (missing.length === 0 && remote.length === 0) {
  console.log(`landing-assets:ok (${SOURCES.length} documents checked)`);
  process.exit(0);
}

for (const entry of missing) console.error(`landing-assets:missing ${entry}`);
for (const entry of remote) console.error(`landing-assets:remote-subresource ${entry}`);
process.exit(1);
