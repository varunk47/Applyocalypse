import { BrowserWindow, app } from "electron";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import type { ThemeState } from "@applyocalypse/shared-types";

// The bundle is an ES module, so there is no __dirname; see noCommonJsGlobals.test.ts.
const bundleDir = dirname(fileURLToPath(import.meta.url));

export const createMainWindow = (themeState: ThemeState): BrowserWindow => {
  const window = new BrowserWindow({
    width: 1440,
    height: 980,
    minWidth: 1080,
    minHeight: 760,
    title: "Applyocalypse",
    backgroundColor: themeState.activeTheme === "dark" ? "#141312" : "#F2EFE7",
    show: false,
    frame: false,
    webPreferences: {
      preload: join(bundleDir, "../preload/index.js"),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      devTools: !app.isPackaged || process.env.APPLYO_ENABLE_DEVTOOLS === "1"
    }
  });

  window.once("ready-to-show", () => {
    window.show();
  });

  const rendererUrl = process.env.ELECTRON_RENDERER_URL;
  if (rendererUrl) {
    void window.loadURL(rendererUrl);
    const allowedOrigin = new URL(rendererUrl).origin;
    window.webContents.on("will-navigate", (event, targetUrl) => {
      if (new URL(targetUrl).origin !== allowedOrigin) {
        event.preventDefault();
      }
    });
  } else {
    void window.loadFile(join(bundleDir, "../renderer/index.html"));
    window.webContents.on("will-navigate", (event, targetUrl) => {
      if (!targetUrl.startsWith("file://")) {
        event.preventDefault();
      }
    });
  }

  window.webContents.setWindowOpenHandler(() => ({ action: "deny" }));
  window.webContents.session.setPermissionRequestHandler((_webContents, _permission, callback) => {
    callback(false);
  });

  return window;
};
