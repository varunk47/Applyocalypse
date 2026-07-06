# Applyocalypse landing page

A self-contained static marketing page in the app's Dossier design language
(paper and ink, sealing-wax accent). No build step, no framework, no CDN. The
animation stack (GSAP, ScrollTrigger, Lenis) and every font are served from
`assets/`, so it works offline and leaks nothing.

## Preview

Open `index.html` directly, or serve the folder:

```bash
npx serve landing
# or
python -m http.server 8080 --directory landing
```

## Deploy

Upload the `landing/` folder to any static host (GitHub Pages, Cloudflare Pages,
Netlify, S3). There is nothing to compile.

## Files

- `index.html`: the page, semantic and accessible (skip link, aria, native `details` FAQ).
- `styles.css`: the full Dossier system: tokens, components, responsive, reduced-motion.
- `main.js`: the full choreography (Lenis smooth scroll, hero masked-rise intro, scroll de-tilt, word-fill, scrolly steps, 3D showcase, count-ups, animated FAQ). Falls back to a fully static, readable page under `prefers-reduced-motion`.
- `assets/fonts/`: Instrument Serif, Hanken Grotesk, JetBrains Mono (OFL, self-hosted).
- `assets/vendor/`: GSAP 3.12.5, ScrollTrigger, Lenis 1.1.14 (self-hosted, no CDN).
- `assets/favicon.svg`, `assets/og.svg`: brand marks and share card.

## House rule

No em dashes anywhere, in copy or code. The product ships an em-dash gate for
generated documents; the site that sells it holds the same line.

## To wire before launch

- The download buttons point at `github.com/varunk47/Applyocalypse/releases/latest`.
  Swap in a signed installer URL once a release is cut.
- `assets/og.svg` renders on platforms that accept SVG share cards. For the
  widest reach, export it to a 1200x630 PNG and update the `og:image` meta.
