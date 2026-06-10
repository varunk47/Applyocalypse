from __future__ import annotations

import asyncio

import pytest

from applyocalypse_automation.llm.provider_matrix import PROVIDER_MATRIX, provider_entry, provider_readiness, run_provider_matrix


def test_provider_matrix_covers_required_byok_providers() -> None:
    assert {entry.provider for entry in PROVIDER_MATRIX} == {
        "openai",
        "anthropic",
        "gemini",
        "zai",
        "xai",
        "groq",
        "nvidia_nim",
        "openrouter",
        "azure_openai",
        "aws_bedrock",
    }


def test_provider_readiness_reports_missing_env_without_exposing_secret_values() -> None:
    readiness = provider_readiness(provider_entry("azure_openai"), {"AZURE_API_KEY": "secret"})

    assert readiness["status"] == "BLOCKED"
    assert readiness["missing_env"] == ["AZURE_API_VERSION", "LITELLM_API_BASE"]
    assert "secret" not in str(readiness)


def test_provider_matrix_offline_mode_is_machine_readable() -> None:
    payload = asyncio.run(run_provider_matrix(live=False, environ={}))

    assert payload["report_type"] == "BYOK_PROVIDER_MATRIX"
    assert payload["live"] is False
    assert len(payload["providers"]) == len(PROVIDER_MATRIX)
    assert all(provider["status"] == "BLOCKED" for provider in payload["providers"])


def test_jd_analysis_uses_fast_model_when_set(monkeypatch: pytest.MonkeyPatch) -> None:
    """LITELLM_MODEL_FAST takes precedence over LITELLM_MODEL for JD analysis."""
    import os

    monkeypatch.setenv("LITELLM_MODEL", "openai/default-model")
    monkeypatch.setenv("LITELLM_MODEL_FAST", "groq/openai/gpt-oss-120b")

    # Import after monkeypatching so os.getenv reads the patched env
    import importlib
    import applyocalypse_automation.jd_analysis as jd_mod
    importlib.reload(jd_mod)

    model_used: list[str] = []

    class CaptureLlm:
        def __init__(self, *, model: str) -> None:
            model_used.append(model)

        async def complete_json(self, **_kwargs: object) -> dict[str, object]:
            raise RuntimeError("short-circuit")

    original = jd_mod.LiteLlmClient
    monkeypatch.setattr(jd_mod, "LiteLlmClient", CaptureLlm)
    asyncio.run(jd_mod.analyze_with_optional_llm("Python developer role"))
    monkeypatch.setattr(jd_mod, "LiteLlmClient", original)

    assert model_used and model_used[0] == "groq/openai/gpt-oss-120b"


def test_jd_analysis_falls_back_to_litellm_model_when_fast_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    """Falls back to LITELLM_MODEL when LITELLM_MODEL_FAST is not set."""
    import os

    monkeypatch.delenv("LITELLM_MODEL_FAST", raising=False)
    monkeypatch.setenv("LITELLM_MODEL", "openai/gpt-5.5")

    import importlib
    import applyocalypse_automation.jd_analysis as jd_mod
    importlib.reload(jd_mod)

    model_used: list[str] = []

    class CaptureLlm:
        def __init__(self, *, model: str) -> None:
            model_used.append(model)

        async def complete_json(self, **_kwargs: object) -> dict[str, object]:
            raise RuntimeError("short-circuit")

    monkeypatch.setattr(jd_mod, "LiteLlmClient", CaptureLlm)
    asyncio.run(jd_mod.analyze_with_optional_llm("Python developer role"))

    assert model_used and model_used[0] == "openai/gpt-5.5"
