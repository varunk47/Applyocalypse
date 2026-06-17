import { statSync } from "node:fs";
import { IpcContracts } from "@applyocalypse/ipc-contracts";
import { HARD_MAX_CONCURRENT_APPLICATIONS } from "@applyocalypse/config";
import { handleContract, type IpcHandlerContext } from "./context";

export const registerSettingsHandlers = (ctx: IpcHandlerContext): void => {
  const { settingsRepository, normalizeUserPath } = ctx;

  handleContract(IpcContracts.settingsGet, () => settingsRepository.getAll());
  handleContract(IpcContracts.settingsUpdate, ({ patch }) => {
    for (const [key, value] of Object.entries(patch)) {
      if (key === "automation.maxConcurrentApplications") {
        if (typeof value !== "number" || !Number.isInteger(value)) {
          throw new Error("Maximum concurrent applications must be an integer");
        }
        const clamped = Math.max(1, Math.min(HARD_MAX_CONCURRENT_APPLICATIONS, value));
        settingsRepository.set(key, clamped);
        continue;
      }
      if (key === "automation.autofillApprovedDefaults") {
        if (typeof value !== "boolean") {
          throw new Error("autofillApprovedDefaults must be a boolean");
        }
        settingsRepository.set(key, value);
        continue;
      }
      if (key !== "files.outputDir") {
        throw new Error(`Unsupported setting key: ${key}`);
      }
      if (typeof value !== "string") {
        throw new Error("Output directory must be a string path");
      }
      const outputDir = normalizeUserPath(value);
      if (!statSync(outputDir).isDirectory()) {
        throw new Error("Output directory must exist and be a directory");
      }
      settingsRepository.set(key, outputDir);
    }
    return settingsRepository.getAll();
  });
};
