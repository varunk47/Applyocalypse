import { ipcMain } from "electron";
import { IpcChannels, IpcContracts } from "@applyocalypse/ipc-contracts";
import { GmailOAuthService } from "../../services/gmailOAuthService";
import { checkConverters } from "../../services/converterDiagnostics";
import { handleContract, type IpcHandlerContext } from "./context";

export const registerSystemHandlers = (ctx: IpcHandlerContext): void => {
  const { themeController, settingsRepository, getMainWindow } = ctx;

  ipcMain.on(IpcChannels.themeGetInitialState, (event) => {
    event.returnValue = themeController.getState();
  });

  handleContract(IpcContracts.appGetVersion, () => ({ version: process.env.npm_package_version ?? "0.1.0" }));
  handleContract(IpcContracts.themeSetPreference, ({ preference }) => themeController.setPreference(preference));

  const gmailOAuthService = new GmailOAuthService(settingsRepository);
  handleContract(IpcContracts.gmailStartOAuth, ({ clientId, clientSecret }) =>
    gmailOAuthService.startOAuthFlow(clientId, clientSecret)
  );
  handleContract(IpcContracts.gmailGetOAuthStatus, () => gmailOAuthService.getStatus());
  handleContract(IpcContracts.gmailDisconnectOAuth, () => {
    gmailOAuthService.disconnect();
    return { ok: true };
  });

  handleContract(IpcContracts.systemCheckConverters, () => ({
    converters: checkConverters()
  }));

  handleContract(IpcContracts.systemWindowControl, ({ action }) => {
    const mainWindow = getMainWindow();
    if (!mainWindow) {
      throw new Error("Main window is not available");
    }
    if (action === "minimize") {
      mainWindow.minimize();
    } else if (action === "toggle-maximize") {
      if (mainWindow.isMaximized()) {
        mainWindow.unmaximize();
      } else {
        mainWindow.maximize();
      }
    } else {
      mainWindow.close();
    }
    return { ok: true as const, isMaximized: mainWindow.isDestroyed() ? false : mainWindow.isMaximized() };
  });
};
