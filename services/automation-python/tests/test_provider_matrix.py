from __future__ import annotations

import asyncio

from applyocalypse_automation.llm.provider_matrix import PROVIDER_MATRIX, provider_entry, provider_readiness, run_provider_matrix


def test_provider_matrix_covers_required_byok_providers() -> None:
    assert {entry.provider for entry in PROVIDER_MATRIX} == {
        "openai",
        "anthropic",
        "gemini",
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
