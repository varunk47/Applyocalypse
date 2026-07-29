/**
 * Rasterizes the landing SVG marks into the PNGs `landing/index.html` asks for.
 *
 * The page references `favicon-32.png`, `apple-touch-icon.png`, and an
 * `og:image` PNG. Those cannot be replaced by the SVGs: iOS ignores SVG for
 * touch icons, and no social crawler renders an SVG `og:image`. So they have to
 * be produced, and re-produced whenever the palette moves.
 *
 * There is no rasterizer in the dependency tree, but Electron is already a
 * first-class dependency of the desktop app, so this borrows its renderer
 * instead of adding sharp/resvg/puppeteer just for three files.
 *
 * It draws into a `<canvas>` rather than calling `capturePage()`, because a
 * window capture comes back at the host display's scale factor (a 150% display
 * turned a 32x32 request into 50x48). Canvas dimensions are raw pixels.
 * The tradeoff is that an SVG rasterized through an `<img>` cannot reach the
 * document's fonts, so the faces are inlined into the SVG as data URIs first.
 *
 * Run from the repo root:
 *     apps/desktop/node_modules/.bin/electron scripts/landing/rasterize-icons.mjs
 */
import { app, BrowserWindow } from "electron";
import { readFileSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..", "..");
const ASSETS = resolve(ROOT, "landing", "assets");
const FONTS = resolve(ASSETS, "fonts");

/** The brand faces the marks call for, so nothing falls back to a host serif. */
const FONT_FACES = [
  { family: "Instrument Serif", file: "InstrumentSerif-Regular.woff2", style: "normal", weight: "400" },
  { family: "Instrument Serif", file: "InstrumentSerif-Italic.woff2", style: "italic", weight: "400" },
  { family: "Hanken Grotesk", file: "HankenGrotesk-Variable.woff2", style: "normal", weight: "100 900" },
  { family: "JetBrains Mono", file: "JetBrainsMono-Variable.woff2", style: "normal", weight: "100 800" },
];

const TARGETS = [
  { source: "favicon.svg", out: "favicon-32.png", width: 32, height: 32 },
  {
    source: "favicon.svg",
    out: "apple-touch-icon.png",
    width: 180,
    height: 180,
    // iOS masks the icon itself. Shipping our own 14/64 radius on top of that
    // produces a visible double-round, so this one goes out full-bleed.
    transform: (svg) => svg.replace(' rx="14"', ""),
  },
  { source: "og.svg", out: "og.png", width: 1200, height: 630 },
];

const fontStyleBlock = () => {
  const faces = FONT_FACES.map(({ family, file, style, weight }) => {
    const data = readFileSync(resolve(FONTS, file)).toString("base64");
    return `@font-face{font-family:'${family}';src:url(data:font/woff2;base64,${data}) format('woff2');font-style:${style};font-weight:${weight};}`;
  });
  // CDATA so the base64 payload cannot be mistaken for markup.
  return `<style type="text/css"><![CDATA[\n${faces.join("\n")}\n]]></style>`;
};

/** Inlines the fonts just inside the root <svg> element. */
const withFonts = (svg, styleBlock) => {
  const openTagEnd = svg.indexOf(">", svg.indexOf("<svg"));
  if (openTagEnd === -1) throw new Error("no <svg> root element");
  return `${svg.slice(0, openTagEnd + 1)}\n${styleBlock}${svg.slice(openTagEnd + 1)}`;
};

/**
 * Runs in the renderer. Draws the SVG at exact pixel dimensions and hands back
 * a PNG data URL. `decode()` resolves only once the embedded faces are parsed,
 * so the text is never captured mid-fallback.
 */
const DRAW = (svgBase64, width, height) => `
  (async () => {
    const img = new Image(${width}, ${height});
    img.src = "data:image/svg+xml;base64,${svgBase64}";
    await img.decode();
    const canvas = document.createElement("canvas");
    canvas.width = ${width};
    canvas.height = ${height};
    const ctx = canvas.getContext("2d");
    ctx.drawImage(img, 0, 0, ${width}, ${height});
    return canvas.toDataURL("image/png");
  })()
`;

const rasterize = async (win, styleBlock, { source, out, width, height, transform }) => {
  const raw = readFileSync(resolve(ASSETS, source), "utf8");
  const svg = withFonts(transform ? transform(raw) : raw, styleBlock);
  const svgBase64 = Buffer.from(svg, "utf8").toString("base64");

  const dataUrl = await win.webContents.executeJavaScript(DRAW(svgBase64, width, height));
  const prefix = "data:image/png;base64,";
  if (!dataUrl.startsWith(prefix)) throw new Error(`${out}: renderer returned ${dataUrl.slice(0, 40)}`);

  const png = Buffer.from(dataUrl.slice(prefix.length), "base64");
  writeFileSync(resolve(ASSETS, out), png);
  process.stdout.write(`${out.padEnd(22)} ${width}x${height}  ${(png.length / 1024).toFixed(1)} KB\n`);
};

app.disableHardwareAcceleration();

app.whenReady().then(async () => {
  const win = new BrowserWindow({ show: false, webPreferences: { offscreen: true } });
  let exitCode = 0;
  try {
    await win.loadURL("data:text/html;charset=utf-8,<!doctype html><meta charset=utf-8>");
    const styleBlock = fontStyleBlock();
    for (const target of TARGETS) await rasterize(win, styleBlock, target);
  } catch (error) {
    process.stderr.write(`${error instanceof Error ? error.message : String(error)}\n`);
    exitCode = 1;
  } finally {
    win.destroy();
    app.exit(exitCode);
  }
});
