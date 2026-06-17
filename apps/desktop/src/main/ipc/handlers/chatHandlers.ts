import { IpcContracts } from "@applyocalypse/ipc-contracts";
import { handleContract, type IpcHandlerContext } from "./context";

export const registerChatHandlers = (ctx: IpcHandlerContext): void => {
  const { chatRepository } = ctx;

  handleContract(IpcContracts.chatAppendMessage, (input) =>
    chatRepository.appendMessage({
      batchId: input.batchId ?? null,
      runId: input.runId ?? null,
      jobId: input.jobId ?? null,
      role: input.role,
      kind: input.kind,
      content: input.content,
      metadata: input.metadata ?? {}
    })
  );
  handleContract(IpcContracts.chatList, ({ limit, offset }) => chatRepository.list(limit, offset));
};
