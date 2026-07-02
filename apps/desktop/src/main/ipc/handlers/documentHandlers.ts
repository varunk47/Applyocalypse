import { IpcContracts } from "@applyocalypse/ipc-contracts";
import { handleContract, type IpcHandlerContext } from "./context";

export const registerDocumentHandlers = (ctx: IpcHandlerContext): void => {
  const { documentIngestionService, uploadRepository, parsedDocumentRepository, auditRepository, requirePickedPath } = ctx;

  handleContract(IpcContracts.documentsIngestResumeSource, ({ profileId, localPath }) =>
    documentIngestionService.ingestResumeSource({ profileId, localPath: requirePickedPath(localPath) })
  );
  handleContract(IpcContracts.documentsConfirmEditableMaster, async ({ uploadedFileId }) => {
    const uploadedFile = uploadRepository.getById(uploadedFileId);
    if (uploadedFile.fileKind !== "RESUME" || uploadedFile.sourceFormat !== "DOCX") {
      throw new Error("Only DOCX resume candidates can be confirmed as editable masters");
    }
    const confirmed = uploadRepository.updateStatus(uploadedFileId, "VERIFIED_EDITABLE_MASTER");
    for (const parsedDocument of parsedDocumentRepository.list({ uploadedFileId: confirmed.id })) {
      parsedDocumentRepository.mergeIntoProfile(parsedDocument);
    }
    auditRepository.append({
      action: "document.editable_master_confirmed",
      entityType: "uploaded_file",
      entityId: confirmed.id,
      metadata: { sourceFormat: confirmed.sourceFormat }
    });
    try {
      await documentIngestionService.repairEditableMasterAnchors({ uploadedFileId: confirmed.id });
    } catch {
      // Non-fatal: repair may fail if the file is already anchored or cannot be processed
    }
    return confirmed;
  });
  handleContract(IpcContracts.documentsRepairEditableMasterAnchors, async ({ uploadedFileId }) => {
    const result = await documentIngestionService.repairEditableMasterAnchors({ uploadedFileId });
    auditRepository.append({
      action: "document.editable_master_anchor_repair_created",
      entityType: "uploaded_file",
      entityId: result.anchoredCandidate.id,
      metadata: {
        sourceUploadedFileId: uploadedFileId,
        addedPlaceholders: result.addedPlaceholders,
        warningCount: result.warnings.length
      }
    });
    return result;
  });
  handleContract(IpcContracts.documentsListParsed, ({ uploadedFileId, profileId }) => ({
    items: parsedDocumentRepository.list({
      ...(uploadedFileId ? { uploadedFileId } : {}),
      ...(profileId !== undefined ? { profileId } : {})
    })
  }));
};
