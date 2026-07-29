import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { buildProviderRuntimeEnv } from "../apps/desktop/src/main/services/providerRuntimeEnv";

/**
 * Locks the TS PROVIDER_DEFAULT_MODEL table to the REAL PROVIDER_MATRIX in the
 * Python worker.
 *
 * These two tables live in different languages and are edited by different
 * concerns, so they drift silently. When they drift the failure is invisible:
 * the worker guards every LLM call on LITELLM_MODEL, so a provider whose
 * default the main process gets wrong degrades JD analysis, resume tailoring
 * and the cover letter to deterministic templates with no error anywhere.
 */

const PROVIDER_MATRIX_PY = resolve(
  __dirname,
  "..",
  "services",
  "automation-python",
  "applyocalypse_automation",
  "llm",
  "provider_matrix.py"
);

/** Parses the ProviderMatrixEntry(...) rows into provider -> default_model. */
const readPythonDefaults = (): Map<string, string> => {
  const py = readFileSync(PROVIDER_MATRIX_PY, "utf8");
  const block = py.slice(
    py.indexOf("PROVIDER_MATRIX: tuple[ProviderMatrixEntry, ...] = ("),
    py.indexOf("\n)", py.indexOf("PROVIDER_MATRIX: tuple[ProviderMatrixEntry, ...] = ("))
  );
  // ProviderMatrixEntry("openai", "OPENAI_API_KEY", "openai/gpt-5.5"[, (...)])
  const row = /ProviderMatrixEntry\(\s*"([^"]+)"\s*,\s*"([^"]+)"\s*,\s*"([^"]+)"/g;
  const defaults = new Map<string, string>();
  for (const [, provider, , defaultModel] of block.matchAll(row)) {
    defaults.set(provider, defaultModel);
  }
  return defaults;
};

describe("provider default-model parity (TS main <-> Python worker)", () => {
  const pythonDefaults = readPythonDefaults();

  it("parses the Python matrix", () => {
    // Guards the regex itself: a refactor of provider_matrix.py that breaks
    // parsing must fail loudly rather than silently assert over an empty map.
    expect(pythonDefaults.size).toBe(10);
    expect(pythonDefaults.get("openai")).toBe("openai/gpt-5.5");
  });

  it("emits the Python default model for every provider when the model field is blank", () => {
    for (const [provider, defaultModel] of pythonDefaults) {
      const { env } = buildProviderRuntimeEnv({
        provider: provider as Parameters<typeof buildProviderRuntimeEnv>[0]["provider"],
        apiKey: "test-key",
        metadata: undefined
      });
      expect(
        env.LITELLM_MODEL,
        `${provider} must route to the same default the worker expects`
      ).toBe(defaultModel);
    }
  });

  it("prefers an explicitly configured model over the default", () => {
    const { env } = buildProviderRuntimeEnv({
      provider: "openai",
      apiKey: "test-key",
      metadata: { defaultModel: "openai/gpt-4.1-custom" }
    });
    expect(env.LITELLM_MODEL).toBe("openai/gpt-4.1-custom");
  });

  it("falls back to the default when the model field is blank or whitespace", () => {
    for (const blank of ["", "   "]) {
      const { env } = buildProviderRuntimeEnv({
        provider: "anthropic",
        apiKey: "test-key",
        metadata: { defaultModel: blank }
      });
      expect(env.LITELLM_MODEL).toBe("anthropic/claude-sonnet-4-6");
    }
  });
});
