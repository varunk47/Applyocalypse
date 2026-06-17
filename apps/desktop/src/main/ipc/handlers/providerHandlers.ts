import { IpcContracts } from "@applyocalypse/ipc-contracts";
import { handleContract, type IpcHandlerContext } from "./context";

export const registerProviderHandlers = (ctx: IpcHandlerContext): void => {
  const { providerRepository, secureSecretStore, auditRepository } = ctx;

  handleContract(IpcContracts.providersList, () => ({ items: providerRepository.list() }));
  handleContract(IpcContracts.providersSaveApiKey, ({ provider, displayName, apiKey, metadata }) => {
    const encryptedReference = secureSecretStore.encryptSecret(apiKey);
    const secretRefId = providerRepository.createEncryptedSecretReference({
      provider,
      keyName: "api_key",
      encryptedReference,
      redactedHint: secureSecretStore.redactedHint(apiKey)
    });
    const connection = providerRepository.upsertConnection({
      provider,
      displayName,
      status: "CONNECTED",
      secretRefId,
      metadata: metadata ?? {}
    });
    auditRepository.append({
      action: "provider.api_key_saved",
      entityType: "provider_connection",
      entityId: connection.id,
      metadata: { provider, secretRefId }
    });
    return connection;
  });
};
