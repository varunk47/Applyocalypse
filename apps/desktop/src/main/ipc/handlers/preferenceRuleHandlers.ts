import { IpcContracts } from "@applyocalypse/ipc-contracts";
import { app } from "electron";
import { join } from "node:path";
import { PreferenceChatReplySchema } from "@applyocalypse/ipc-contracts";
import { runPreferenceChat } from "../../services/preferenceChatService";
import { handleContract, type IpcHandlerContext } from "./context";

export const registerPreferenceRuleHandlers = (ctx: IpcHandlerContext): void => {
  const { preferenceRuleRepository, jobFilterRepository, profileAddressRepository } = ctx;

  handleContract(IpcContracts.preferenceRulesList, ({ profileId }) => ({
    items: preferenceRuleRepository.listByProfile(profileId)
  }));
  handleContract(IpcContracts.preferenceRulesUpsert, (input) => preferenceRuleRepository.upsert(input));
  handleContract(IpcContracts.preferenceRulesDelete, ({ id }) => ({ deleted: preferenceRuleRepository.delete(id) }));

  handleContract(IpcContracts.jobFiltersList, ({ profileId }) => ({ items: jobFilterRepository.listByProfile(profileId) }));
  handleContract(IpcContracts.jobFiltersUpsert, (input) => jobFilterRepository.upsert(input));
  handleContract(IpcContracts.jobFiltersDelete, ({ id }) => ({ deleted: jobFilterRepository.delete(id) }));

  handleContract(IpcContracts.profileAddressesList, ({ profileId }) => ({
    items: profileAddressRepository.listByProfile(profileId)
  }));
  handleContract(IpcContracts.profileAddressesUpsert, (input) => profileAddressRepository.upsert(input));
  handleContract(IpcContracts.profileAddressesDelete, ({ id }) => ({ deleted: profileAddressRepository.delete(id) }));

  handleContract(IpcContracts.preferenceChatSend, async (input) =>
    PreferenceChatReplySchema.parse(
      await runPreferenceChat(
        {
          scratchRoot: join(app.getPath("userData"), "preference-chat"),
          preferenceRuleRepository,
          jobFilterRepository,
          profileAddressRepository,
          providerRepository: ctx.providerRepository,
          secureSecretStore: ctx.secureSecretStore
        },
        input
      )
    )
  );
};
