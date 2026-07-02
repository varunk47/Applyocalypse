import { createIpcHandlerContext, type RegisterIpcHandlersInput } from "./handlers/context";
import { registerSettingsHandlers } from "./handlers/settingsHandlers";
import { registerProviderHandlers } from "./handlers/providerHandlers";
import { registerDocumentHandlers } from "./handlers/documentHandlers";
import { registerProfileHandlers } from "./handlers/profileHandlers";
import { registerFileHandlers } from "./handlers/fileHandlers";
import { registerJobQueueHandlers } from "./handlers/jobQueueHandlers";
import { registerRunHandlers } from "./handlers/runHandlers";
import { registerRunQueryHandlers } from "./handlers/runQueryHandlers";
import { registerChatHandlers } from "./handlers/chatHandlers";
import { registerSystemHandlers } from "./handlers/systemHandlers";

export type { RegisterIpcHandlersInput };

/**
 * Composition root for the renderer↔main IPC surface. Each domain's handlers
 * live in its own module under `./handlers`; this wires them onto a shared
 * context. Registration order across distinct channels does not matter
 * (ipcMain.handle/on key by channel), so modules are grouped by domain.
 */
export const registerIpcHandlers = (input: RegisterIpcHandlersInput): void => {
  const ctx = createIpcHandlerContext(input);

  registerSystemHandlers(ctx); // app version, theme (incl. themeGetInitialState ipcMain.on), gmail, converters
  registerSettingsHandlers(ctx);
  registerProviderHandlers(ctx);
  registerDocumentHandlers(ctx);
  registerProfileHandlers(ctx);
  registerFileHandlers(ctx);
  registerJobQueueHandlers(ctx);
  registerRunHandlers(ctx);
  registerRunQueryHandlers(ctx);
  registerChatHandlers(ctx);
};
