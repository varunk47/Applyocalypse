import { describe, expect, it } from "vitest";
import { buildProviderRuntimeEnv } from "./providerRuntimeEnv";

describe("provider runtime env", () => {
  it("covers every BYOK provider required by the product matrix", () => {
    const expected = [
      ["openai", "OPENAI_API_KEY"],
      ["anthropic", "ANTHROPIC_API_KEY"],
      ["gemini", "GEMINI_API_KEY"],
      ["zai", "ZAI_API_KEY"],
      ["xai", "XAI_API_KEY"],
      ["groq", "GROQ_API_KEY"],
      ["nvidia_nim", "NVIDIA_NIM_API_KEY"],
      ["openrouter", "OPENROUTER_API_KEY"],
      ["azure_openai", "AZURE_API_KEY"],
      ["aws_bedrock", "AWS_SECRET_ACCESS_KEY"]
    ] as const;
    for (const [provider, envName] of expected) {
      const { env, secretEnv } = buildProviderRuntimeEnv({
        provider,
        apiKey: `${provider}-secret`,
        metadata: { defaultModel: `${provider}/model` }
      });
      expect(secretEnv[envName]).toBe(`${provider}-secret`);
      expect(env[envName]).toBeUndefined();
      expect(env.LITELLM_PROVIDER).toBe(provider);
      expect(env.LITELLM_MODEL).toBe(`${provider}/model`);
    }
  });

  it("keeps the API key out of the spawn env and in secretEnv only", () => {
    const { env, secretEnv } = buildProviderRuntimeEnv({
      provider: "openai",
      apiKey: "sk-test",
      metadata: { defaultModel: "gpt-4.1" }
    });
    expect(secretEnv.OPENAI_API_KEY).toBe("sk-test");
    expect(Object.values(env)).not.toContain("sk-test");
    expect(env.LITELLM_PROVIDER).toBe("openai");
    expect(env.LITELLM_MODEL).toBe("gpt-4.1");
  });

  it("sets LITELLM_MODEL_STRONG and LITELLM_MODEL_FAST when strongModel and fastModel are in metadata", () => {
    const { env } = buildProviderRuntimeEnv({
      provider: "openai",
      apiKey: "sk-test",
      metadata: {
        defaultModel: "openai/gpt-5.5",
        strongModel: "openai/gpt-5.5",
        fastModel: "groq/openai/gpt-oss-120b"
      }
    });
    expect(env.LITELLM_MODEL).toBe("openai/gpt-5.5");
    expect(env.LITELLM_MODEL_STRONG).toBe("openai/gpt-5.5");
    expect(env.LITELLM_MODEL_FAST).toBe("groq/openai/gpt-oss-120b");
  });

  it("leaves LITELLM_MODEL_STRONG and LITELLM_MODEL_FAST unset without metadata", () => {
    const { env } = buildProviderRuntimeEnv({
      provider: "openai",
      apiKey: "sk-test",
      metadata: { defaultModel: "openai/gpt-5.5" }
    });
    expect(env.LITELLM_MODEL_STRONG).toBeUndefined();
    expect(env.LITELLM_MODEL_FAST).toBeUndefined();
  });

  it("supports ZAI via ZAI_API_KEY", () => {
    const { env, secretEnv } = buildProviderRuntimeEnv({
      provider: "zai",
      apiKey: "zai-secret",
      metadata: { defaultModel: "zai/glm-5" }
    });
    expect(secretEnv.ZAI_API_KEY).toBe("zai-secret");
    expect(env.LITELLM_PROVIDER).toBe("zai");
    expect(env.LITELLM_MODEL).toBe("zai/glm-5");
  });

  it("supports Azure OpenAI with api base and version", () => {
    const { env, secretEnv } = buildProviderRuntimeEnv({
      provider: "azure_openai",
      apiKey: "test-key",
      metadata: {
        defaultModel: "azure/gpt-4.1",
        apiBase: "https://example.openai.azure.com",
        apiVersion: "2025-01-01-preview"
      }
    });
    expect(secretEnv.AZURE_API_KEY).toBe("test-key");
    expect(env.LITELLM_MODEL).toBe("azure/gpt-4.1");
    expect(env.LITELLM_API_BASE).toBe("https://example.openai.azure.com");
    expect(env.AZURE_API_VERSION).toBe("2025-01-01-preview");
  });

  it("supports AWS Bedrock and keeps only the secret access key out of the spawn env", () => {
    const { env, secretEnv } = buildProviderRuntimeEnv({
      provider: "aws_bedrock",
      apiKey: "test-key",
      metadata: {
        defaultModel: "bedrock/anthropic.claude-3-5-sonnet-20240620-v1:0",
        awsAccessKeyId: "AKIA_TEST",
        awsRegion: "us-east-1"
      }
    });
    expect(secretEnv.AWS_SECRET_ACCESS_KEY).toBe("test-key");
    expect(env.AWS_SECRET_ACCESS_KEY).toBeUndefined();
    expect(env.AWS_ACCESS_KEY_ID).toBe("AKIA_TEST");
    expect(env.AWS_REGION).toBe("us-east-1");
    expect(env.AWS_DEFAULT_REGION).toBe("us-east-1");
    expect(env.LITELLM_MODEL).toContain("bedrock/");
  });
});
