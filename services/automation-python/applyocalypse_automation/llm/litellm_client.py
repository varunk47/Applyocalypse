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

# Providers that need the cache boundary spelled out in the request. Everyone
# else either reuses a repeated prefix on their own (OpenAI, Deepseek, recent
# Gemini) or does not cache at all, and in both cases the right request is the
# one with the stable half first and nothing else added to it.
_EXPLICIT_CACHE_PROVIDERS = frozenset({"anthropic", "bedrock", "vertex_ai"})

# Anthropic will not cache a prefix under 1024 tokens, or 2048 on the small
# models, so a breakpoint on a short block is a breakpoint that does nothing.
# Four characters to the token is the usual rough conversion; erring high only
# means a small prefix goes uncached, which is what would have happened anyway.
_MIN_CACHEABLE_PREFIX_CHARS = 4096


def _wants_explicit_cache_breakpoint(model: str, forced_provider: str | None) -> bool:
    """Whether this model needs the cache boundary marked in the request itself.

    Both halves of the answer come from litellm's own tables rather than a list
    kept by hand here, because a model added to a provider next month should not
    need this file edited to be cached or to keep working.
    """
    if forced_provider is not None:
        # A custom OpenAI-compatible endpoint. Whatever is behind it, the request
        # being made is an OpenAI one, and cache_control is not in that schema.
        return False
    try:
        from litellm import get_llm_provider  # type: ignore
        from litellm.utils import supports_prompt_caching  # type: ignore
    except ImportError:
        return False
    try:
        provider = get_llm_provider(model=model)[1]
    except Exception:
        # An unrecognised model id. It still has to be able to make the call, so
        # this is a refusal to decorate the request, not a refusal to send it.
        return False
    if provider not in _EXPLICIT_CACHE_PROVIDERS:
        return False
    try:
        return bool(supports_prompt_caching(model=model))
    except Exception:
        return False


def _user_content(user: str, cached_prefix: str, *, explicit_breakpoint: bool) -> Any:
    """The user turn, stable half first, with the boundary marked where that helps.

    The ordering is the part that matters everywhere. A provider that caches on
    its own can only reuse a prefix that is genuinely a prefix, so putting the
    material that is identical across a batch behind the material that changes
    every time means nothing is ever shared. The breakpoint on top of that is
    what turns the same request into a cache hit on Anthropic, which does not
    cache anything it was not asked to.
    """
    if not cached_prefix:
        return user
    if explicit_breakpoint and len(cached_prefix) >= _MIN_CACHEABLE_PREFIX_CHARS:
        return [
            {"type": "text", "text": cached_prefix, "cache_control": {"type": "ephemeral"}},
            {"type": "text", "text": user},
        ]
    return f"{cached_prefix}\n\n{user}"


@dataclass(frozen=True, slots=True)
class LiteLlmClient:
    model: str

    async def complete_json(
        self,
        *,
        system: str,
        user: str,
        schema_name: str,
        cached_prefix: str = "",
    ) -> dict[str, Any]:
        """One JSON completion.

        ``cached_prefix`` is the part of the user turn that is the same on every
        call in a batch, such as the candidate's resume when twenty applications
        are being tailored against it. It is sent ahead of ``user`` so a provider
        can reuse it, and marked as a cache breakpoint on the providers that need
        to be told. Leaving it empty sends exactly the request this made before
        any of that existed.
        """
        try:
            from litellm import acompletion  # type: ignore
        except ImportError as exc:
            raise RuntimeError("litellm is required for BYOK provider access") from exc

        api_base = (os.getenv("LITELLM_API_BASE") or "").strip()
        provider = (os.getenv("LITELLM_PROVIDER") or "").strip().lower()
        routed_through_openai = bool(api_base) and provider in _OPENAI_COMPATIBLE_KEY_ENV

        call_kwargs: dict[str, Any] = dict(
            model=self.model,
            messages=[
                {"role": "system", "content": system},
                {
                    "role": "user",
                    "content": _user_content(
                        user,
                        cached_prefix,
                        explicit_breakpoint=_wants_explicit_cache_breakpoint(
                            self.model, "openai" if routed_through_openai else None
                        ),
                    ),
                },
            ],
            response_format={"type": "json_object"},
            # A hung provider must not freeze the run forever, and a runaway
            # completion must not accrue unbounded cost.
            timeout=180,
            max_tokens=4096,
            # Tailoring twenty applications is twenty calls against one key, which
            # is exactly the shape that trips a rate limit, and until now a single
            # 429 ended the run and dropped the user back to a template document.
            # litellm retries only what is worth retrying (429, 5xx, timeouts) and
            # backs off between attempts; a bad request or a rejected key still
            # fails on the first try. The costs it does not retry through are the
            # ones the caller already handles: malformed JSON comes back as a
            # successful response, so that retry stays where it is.
            num_retries=2,
        )
        if routed_through_openai:
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
