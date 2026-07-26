from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

# OpenAI-compatible providers whose API key lives under a provider-specific env var.
# When a custom base URL is configured (e.g. NVIDIA NIM), the request must be driven
# through litellm's openai-compatible path with that base + key, or the model id has
# no valid route and every call fails (silently falling back to a template document).
_OPENAI_COMPATIBLE_KEY_ENV: dict[str, str] = {
    "openai": "OPENAI_API_KEY",
    "zai": "ZAI_API_KEY",
    "xai": "XAI_API_KEY",
    "groq": "GROQ_API_KEY",
    "nvidia_nim": "NVIDIA_NIM_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
}


@dataclass(frozen=True, slots=True)
class LiteLlmClient:
    model: str

    async def complete_json(self, *, system: str, user: str, schema_name: str) -> dict[str, Any]:
        try:
            from litellm import acompletion  # type: ignore
        except ImportError as exc:
            raise RuntimeError("litellm is required for BYOK provider access") from exc

        call_kwargs: dict[str, Any] = dict(
            model=self.model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            response_format={"type": "json_object"},
            # A hung provider must not freeze the run forever, and a runaway
            # completion must not accrue unbounded cost.
            timeout=180,
            max_tokens=4096,
        )
        api_base = (os.getenv("LITELLM_API_BASE") or "").strip()
        provider = (os.getenv("LITELLM_PROVIDER") or "").strip().lower()
        if api_base and provider in _OPENAI_COMPATIBLE_KEY_ENV:
            # Route custom OpenAI-compatible endpoints (NVIDIA NIM, OpenRouter, zai, vLLM,
            # LM Studio, ...) through the openai path with the configured base + provider key,
            # so the model id is sent verbatim instead of being guessed from a prefix.
            call_kwargs["api_base"] = api_base
            call_kwargs["custom_llm_provider"] = "openai"
            api_key = os.getenv(_OPENAI_COMPATIBLE_KEY_ENV[provider])
            if api_key:
                call_kwargs["api_key"] = api_key

        response = await acompletion(**call_kwargs)
        content = response["choices"][0]["message"]["content"]
        if not isinstance(content, str):
            raise RuntimeError(f"{schema_name} response did not contain text content")

        import json

        try:
            parsed = json.loads(content)
        except json.JSONDecodeError as exc:
            # ValueError keeps callers' retry-on-malformed-output branches working.
            raise ValueError(f"{schema_name} response was not valid JSON") from exc
        if not isinstance(parsed, dict):
            raise RuntimeError(f"{schema_name} response must be a JSON object")
        return parsed
