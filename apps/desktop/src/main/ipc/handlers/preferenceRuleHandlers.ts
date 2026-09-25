import { IpcContracts } from "@applyocalypse/ipc-contracts";
import { handleContract, type IpcHandlerContext } from "./context";

export const registerPreferenceRuleHandlers = (ctx: IpcHandlerContext): void => {
  const { preferenceRuleRepository } = ctx;

  handleContract(IpcContracts.preferenceRulesList, ({ profileId }) => ({
    items: preferenceRuleRepository.listByProfile(profileId)
  }));
  handleContract(IpcContracts.preferenceRulesUpsert, (input) => preferenceRuleRepository.upsert(input));
  handleContract(IpcContracts.preferenceRulesDelete, ({ id }) => ({ deleted: preferenceRuleRepository.delete(id) }));
};
