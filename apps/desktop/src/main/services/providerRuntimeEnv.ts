import type { LlmProviderType } from "@applyocalypse/db";

const PROVIDER_API_KEY_ENV: Record<LlmProviderType, string> = {
  openai: "OPENAI_API_KEY",
  anthropic: "ANTHROPIC_API_KEY",
  gemini: "GEMINI_API_KEY",
  zai: "ZAI_API_KEY",
  xai: "XAI_API_KEY",
  groq: "GROQ_API_KEY",
  nvidia_nim: "NVIDIA_NIM_API_KEY",
  openrouter: "OPENROUTER_API_KEY",
  azure_openai: "AZURE_API_KEY",
  aws_bedrock: "AWS_SECRET_ACCESS_KEY"
};

const metadataString = (metadata: Record<string, unknown> | undefined, key: string): string | null => {
  const value = metadata?.[key];
  return typeof value === "string" && value.trim() ? value.trim() : null;
};

export type ProviderRuntimeEnv = {
  /** Non-secret runtime configuration, safe to pass via child-process env vars. */
  env: Record<string, string>;
  /** Provider credentials; must reach the worker via the 0600 secrets file, never spawn env. */
  secretEnv: Record<string, string>;
};

export const buildProviderRuntimeEnv = (input: {
  provider: LlmProviderType;
  apiKey: string;
  metadata?: Record<string, unknown>;
}): ProviderRuntimeEnv => {
  const envName = PROVIDER_API_KEY_ENV[input.provider];
  const secretEnv: Record<string, string> = {
    [envName]: input.apiKey
  };
  const env: Record<string, string> = {
    LITELLM_PROVIDER: input.provider
  };

  const defaultModel = metadataString(input.metadata, "defaultModel");
  if (defaultModel) {
    env.LITELLM_MODEL = defaultModel;
  }

  const strongModel = metadataString(input.metadata, "strongModel");
  if (strongModel) {
    env.LITELLM_MODEL_STRONG = strongModel;
  }

  const fastModel = metadataString(input.metadata, "fastModel");
  if (fastModel) {
    env.LITELLM_MODEL_FAST = fastModel;
  }

  const apiBase = metadataString(input.metadata, "apiBase");
  if (apiBase) {
    env.LITELLM_API_BASE = apiBase;
  }

  const apiVersion = metadataString(input.metadata, "apiVersion");
  if (input.provider === "azure_openai" && apiVersion) {
    env.AZURE_API_VERSION = apiVersion;
  }

  if (input.provider === "aws_bedrock") {
    const accessKeyId = metadataString(input.metadata, "awsAccessKeyId");
    const region = metadataString(input.metadata, "awsRegion");
    if (accessKeyId) {
      env.AWS_ACCESS_KEY_ID = accessKeyId;
    }
    if (region) {
      env.AWS_REGION = region;
      env.AWS_DEFAULT_REGION = region;
    }
  }

  return { env, secretEnv };
};
