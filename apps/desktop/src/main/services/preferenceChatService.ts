import { spawn } from "node:child_process";
import { randomUUID } from "node:crypto";
import { mkdirSync, rmSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import type { JobFilterRepository, PreferenceRuleRepository, ProfileAddressRepository, ProviderRepository } from "@applyocalypse/db";
import { buildProviderRuntimeEnv } from "./providerRuntimeEnv";
import { resolvePythonWorkerLaunch } from "./pythonWorkerPaths";
import type { SecureSecretStore } from "./secureSecretStore";

const CHAT_TIMEOUT_MS = 60_000;

export type PreferenceChatDeps = {
  scratchRoot: string;
  preferenceRuleRepository: PreferenceRuleRepository;
  jobFilterRepository: JobFilterRepository;
  profileAddressRepository: ProfileAddressRepository;
  providerRepository: ProviderRepository;
  secureSecretStore: SecureSecretStore;
};

/**
 * Asks the worker to turn one chat message into preference proposals. Nothing
 * is saved here; the renderer shows the proposals and saves the ones the user
 * keeps. The model key reaches the worker through a 0600 file that is removed
 * as soon as the worker exits, as for queued runs.
 */
export const runPreferenceChat = async (
  deps: PreferenceChatDeps,
  input: { profileId: string; message: string }
): Promise<unknown> => {
  const scratchDir = join(deps.scratchRoot, randomUUID());
  mkdirSync(scratchDir, { recursive: true });
  try {
    const inputFile = join(scratchDir, "chat.json");
    writeFileSync(
      inputFile,
      JSON.stringify({
        message: input.message,
        known: {
          answerRules: deps.preferenceRuleRepository.workerRules(input.profileId),
          jobFilters: deps.jobFilterRepository.workerFilters(input.profileId),
          addresses: deps.profileAddressRepository.workerAddresses(input.profileId)
        }
      }),
      { encoding: "utf8", mode: 0o600 }
    );

    let env: Record<string, string | undefined> = { ...process.env };
    const providerSecret = deps.providerRepository.getFirstConnectedSecretReference();
    if (providerSecret) {
      const runtime = buildProviderRuntimeEnv({
        provider: providerSecret.provider,
        apiKey: deps.secureSecretStore.decryptSecret(providerSecret.encryptedReference),
        metadata: providerSecret.metadata
      });
      const secretsFile = join(scratchDir, "worker-secrets.json");
      writeFileSync(secretsFile, JSON.stringify(runtime.secretEnv), { encoding: "utf8", mode: 0o600 });
      env = { ...env, ...runtime.env, APPLYO_SECRETS_FILE: secretsFile };
    }

    return await spawnChat(inputFile, env);
  } finally {
    rmSync(scratchDir, { recursive: true, force: true });
  }
};

const spawnChat = (inputFile: string, env: Record<string, string | undefined>): Promise<unknown> => {
  const launch = resolvePythonWorkerLaunch();
  const args = [...launch.baseArgs, "pipeline", "chat-preferences", "--input-file", inputFile];

  return new Promise((resolve, reject) => {
    const child = spawn(launch.executable, args, { cwd: launch.cwd, env, shell: false, windowsHide: true });
    const timer = setTimeout(() => {
      child.kill();
      reject(new Error("The preference chat took too long to answer."));
    }, CHAT_TIMEOUT_MS);

    let stdout = "";
    let stderr = "";
    child.stdout.on("data", (chunk: Buffer) => {
      stdout += chunk.toString("utf8");
    });
    child.stderr.on("data", (chunk: Buffer) => {
      stderr += chunk.toString("utf8");
    });
    child.on("error", (error) => {
      clearTimeout(timer);
      reject(error);
    });
    child.on("exit", (code) => {
      clearTimeout(timer);
      if (code !== 0) {
        reject(new Error(stderr.trim().split("\n").pop() || `Preference chat exited with code ${code ?? "unknown"}`));
        return;
      }
      try {
        resolve(JSON.parse(stdout.trim().split("\n").pop() ?? ""));
      } catch (error) {
        reject(error);
      }
    });
  });
};
