/**
 * Builds the Windows application icon from the brand mark.
 *
 * electron-builder reported "default Electron icon is used" for every package,
 * so the installer, the desktop shortcut, the taskbar button and the uninstall
 * entry all wore Electron's logo instead of the product's. The mark already
 * exists as `landing/assets/favicon.svg`; this turns it into the multi
 * resolution `.ico` Windows wants and commits the result, so packaging stays
 * deterministic and needs no converter at build time.
 *
 * Like scripts/landing/rasterize-icons.mjs this borrows Electron's renderer
 * rather than adding sharp/resvg, and draws into a `<canvas>` at explicit pixel
 * dimensions so a scaled host display cannot change the output size.
 *
 * Run from repo root:
 *   apps/desktop/node_modules/.bin/electron scripts/build/generate-app-icon.mjs
 */
import { app, BrowserWindow } from "electron";
import { readFileSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..", "..");
const SOURCE = resolve(ROOT, "landing", "assets", "favicon.svg");
const OUT = resolve(ROOT, "apps", "desktop", "electron-builder", "icon.ico");

// Windows asks for the icon at every one of these. 256 is the one
// electron-builder validates; 16 is the one the taskbar actually shows most.
const SIZES = [16, 24, 32, 48, 64, 128, 256];

// Below this the dashed orbit ring collapses into a grey smear and the disc
// underneath loses the letter, so small sizes get the mark without the ring.
const RING_DROPS_BELOW = 40;

/**
 * The full mark is a dashed orbit around a solid disc. At 16 and 32 pixels the
 * ring is not legible, and it steals the radius the letter needs, so it is
 * removed and the disc grows into the space it vacated. Both edits assert, so a
 * reshaped favicon.svg fails the build instead of silently shipping a mark that
 * no longer matches the source.
 */
const simplifyForSmallSizes = (svg) => {
  const withoutRing = svg.replace(/\s*<circle[^>]*stroke-dasharray[^>]*\/>/, "");
  if (withoutRing === svg) {
    throw new Error("expected a dashed orbit circle in favicon.svg");
  }
  const grown = withoutRing.replace('r="15"', 'r="21"');
  if (grown === withoutRing) {
    throw new Error('expected the disc to be r="15" in favicon.svg');
  }
  return grown.replace('font-size="24"', 'font-size="32"').replace('y="41"', 'y="44"');
};

/**
 * Runs in the renderer. `decode()` resolves once the SVG is parsed and laid
 * out, so the letter is never captured mid-fallback.
 */
const DRAW = (svgBase64, size) => `
  (async () => {
    const img = new Image(${size}, ${size});
    img.src = "data:image/svg+xml;base64,${svgBase64}";
    await img.decode();
    const canvas = document.createElement("canvas");
    canvas.width = ${size};
    canvas.height = ${size};
    const ctx = canvas.getContext("2d");
    ctx.drawImage(img, 0, 0, ${size}, ${size});
    return canvas.toDataURL("image/png");
  })()
`;

/**
 * Packs PNG frames into an ICO. Every Windows release that can run Electron
 * reads PNG compressed entries, so the frames go in untouched rather than being
 * re-encoded as bottom-up BMP with a separate transparency mask.
 */
const packIco = (frames) => {
  const HEADER_BYTES = 6;
  const ENTRY_BYTES = 16;

  const header = Buffer.alloc(HEADER_BYTES);
  header.writeUInt16LE(0, 0); // reserved
  header.writeUInt16LE(1, 2); // 1 = icon, 2 = cursor
  header.writeUInt16LE(frames.length, 4);

  let offset = HEADER_BYTES + ENTRY_BYTES * frames.length;
  const entries = frames.map(({ size, png }) => {
    const entry = Buffer.alloc(ENTRY_BYTES);
    // A 256 pixel side is stored as 0: the field is one byte wide.
    entry.writeUInt8(size === 256 ? 0 : size, 0);
    entry.writeUInt8(size === 256 ? 0 : size, 1);
    entry.writeUInt8(0, 2); // palette size, 0 for truecolour
    entry.writeUInt8(0, 3); // reserved
    entry.writeUInt16LE(1, 4); // colour planes
    entry.writeUInt16LE(32, 6); // bits per pixel
    entry.writeUInt32LE(png.length, 8);
    entry.writeUInt32LE(offset, 12);
    offset += png.length;
    return entry;
  });

  return Buffer.concat([header, ...entries, ...frames.map(({ png }) => png)]);
};

const rasterize = async (win, svg, size) => {
  const svgBase64 = Buffer.from(svg, "utf8").toString("base64");
  const dataUrl = await win.webContents.executeJavaScript(DRAW(svgBase64, size));
  const prefix = "data:image/png;base64,";
  if (!dataUrl.startsWith(prefix)) {
    throw new Error(`unexpected canvas output at ${size}px: ${dataUrl.slice(0, 40)}`);
  }
  return { size, png: Buffer.from(dataUrl.slice(prefix.length), "base64") };
};

app.disableHardwareAcceleration();

app.whenReady().then(async () => {
  const win = new BrowserWindow({ show: false, width: 512, height: 512 });
  let exitCode = 0;

  try {
    await win.loadURL("data:text/html;charset=utf-8,<!doctype html><meta charset=utf-8>");
    const full = readFileSync(SOURCE, "utf8");
    const small = simplifyForSmallSizes(full);

    const frames = [];
    for (const size of SIZES) {
      frames.push(await rasterize(win, size < RING_DROPS_BELOW ? small : full, size));
    }

    const ico = packIco(frames);
    writeFileSync(OUT, ico);
    process.stdout.write(
      `icon.ico  ${SIZES.join("/")}  ${(ico.length / 1024).toFixed(1)} KB\n`
    );
  } catch (error) {
    process.stderr.write(`${error instanceof Error ? error.message : error}\n`);
    exitCode = 1;
  }

  win.destroy();
  app.exit(exitCode);
});
