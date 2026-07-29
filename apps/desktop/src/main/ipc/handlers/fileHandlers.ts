import { app, dialog, shell } from "electron";
import { IpcContracts } from "@applyocalypse/ipc-contracts";
import { resolveOwningProfileId } from "../../services/profileOwnership";
import { handleContract, type IpcHandlerContext } from "./context";

export const registerFileHandlers = (ctx: IpcHandlerContext): void => {
  const {
    getMainWindow,
    normalizeUserPath,
    requirePickedPath,
    requireOpenablePath,
    approvePickedPath,
    uploadRepository,
    profileRepository,
    documentIngestionService
  } = ctx;

  handleContract(IpcContracts.filesPick, async ({ purpose }) => {
    const filters =
      purpose === "resume"
        ? [{ name: "Resume Sources", extensions: ["pdf", "docx", "tex"] }]
        : [{ name: "Documents", extensions: ["pdf", "docx", "tex", "txt", "md"] }];

    const dialogOptions = {
      properties: ["openFile"] as Array<"openFile">,
      filters
    };
    const owner = getMainWindow();
    const result = owner ? await dialog.showOpenDialog(owner, dialogOptions) : await dialog.showOpenDialog(dialogOptions);

    if (result.canceled) {
      return { canceled: true, paths: [] };
    }
    const paths = result.filePaths.map(normalizeUserPath);
    for (const path of paths) {
      approvePickedPath(path);
    }
    return { canceled: false, paths };
  });

  handleContract(IpcContracts.filesOpenLocalPath, async ({ localPath }) => {
    const normalized = requireOpenablePath(localPath);
    const error = await shell.openPath(normalized);
    return { opened: error.length === 0 };
  });

  handleContract(IpcContracts.filesListUploads, ({ profileId }) => ({
    items: uploadRepository.list(profileId ?? null)
  }));

  handleContract(IpcContracts.filesRegisterUpload, ({ profileId, localPath, fileKind }) => {
    if (fileKind === "RESUME") {
      throw new Error("Resume uploads must use the editable-master ingestion flow");
    }
    return documentIngestionService.ingestSourceMaterial({
      profileId: resolveOwningProfileId(profileId, profileRepository),
      localPath: requirePickedPath(localPath),
      fileKind
    });
  });

  handleContract(IpcContracts.foldersOpenDownloads, async () => {
    const error = await shell.openPath(app.getPath("downloads"));
    return { opened: error.length === 0 };
  });

  handleContract(IpcContracts.foldersChooseOutputDir, async () => {
    const owner = getMainWindow();
    const result = owner
      ? await dialog.showOpenDialog(owner, { properties: ["openDirectory"] })
      : await dialog.showOpenDialog({ properties: ["openDirectory"] });
    return {
      canceled: result.canceled,
      localPath: result.canceled ? null : result.filePaths[0] ?? null
    };
  });
};
