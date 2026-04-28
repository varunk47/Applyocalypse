from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass
import json
import os


@dataclass(frozen=True, slots=True)
class ProviderMatrixEntry:
    provider: str
    api_key_env: str
    default_model: str
    extra_required_env: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "provider": self.provider,
            "api_key_env": self.api_key_env,
            "default_model": self.default_model,
            "extra_required_env": list(self.extra_required_env),
        }


PROVIDER_MATRIX: tuple[ProviderMatrixEntry, ...] = (
    ProviderMatrixEntry("openai", "OPENAI_API_KEY", "openai/gpt-4.1-mini"),
    ProviderMatrixEntry("anthropic", "ANTHROPIC_API_KEY", "anthropic/claude-3-5-haiku-latest"),
    ProviderMatrixEntry("gemini", "GEMINI_API_KEY", "gemini/gemini-1.5-flash"),
    ProviderMatrixEntry("xai", "XAI_API_KEY", "xai/grok-2-latest"),
    ProviderMatrixEntry("groq", "GROQ_API_KEY", "groq/llama-3.1-8b-instant"),
    ProviderMatrixEntry("nvidia_nim", "NVIDIA_NIM_API_KEY", "nvidia_nim/meta/llama-3.1-8b-instruct"),
    ProviderMatrixEntry("openrouter", "OPENROUTER_API_KEY", "openrouter/openai/gpt-4o-mini"),
    ProviderMatrixEntry("azure_openai", "AZURE_API_KEY", "azure/gpt-4.1-mini", ("AZURE_API_VERSION", "LITELLM_API_BASE")),
    ProviderMatrixEntry("aws_bedrock", "AWS_SECRET_ACCESS_KEY", "bedrock/anthropic.claude-3-haiku-20240307-v1:0", ("AWS_ACCESS_KEY_ID", "AWS_REGION")),
)


def provider_entry(provider: str) -> ProviderMatrixEntry:
    for entry in PROVIDER_MATRIX:
        if entry.provider == provider:
            return entry
    raise ValueError(f"Unsupported provider: {provider}")


def provider_readiness(entry: ProviderMatrixEntry, environ: dict[str, str]) -> dict[str, object]:
    missing = [name for name in (entry.api_key_env, *entry.extra_required_env) if not environ.get(name)]
    return {
        **entry.to_dict(),
        "status": "READY" if not missing else "BLOCKED",
        "missing_env": missing,
    }


async def live_smoke(entry: ProviderMatrixEntry) -> dict[str, object]:
    try:
        from litellm import acompletion  # type: ignore
    except ImportError as exc:
        return {**entry.to_dict(), "status": "FAIL", "error": f"litellm_unavailable:{type(exc).__name__}"}

    try:
        response = await acompletion(
            model=os.environ.get("LITELLM_MODEL", entry.default_model),
            messages=[
                {"role": "system", "content": "Return a compact JSON object."},
                {"role": "user", "content": "{\"ok\": true}"},
            ],
            response_format={"type": "json_object"},
            max_tokens=32,
        )
        content = response["choices"][0]["message"]["content"]
        return {**entry.to_dict(), "status": "PASS", "content_length": len(str(content))}
    except Exception as exc:  # noqa: BLE001 - provider SDKs raise heterogeneous errors.
        return {**entry.to_dict(), "status": "FAIL", "error": type(exc).__name__}


async def run_provider_matrix(*, live: bool, environ: dict[str, str] | None = None) -> dict[str, object]:
    env = environ if environ is not None else dict(os.environ)
    readiness = [provider_readiness(entry, env) for entry in PROVIDER_MATRIX]
    if not live:
        return {
            "report_type": "BYOK_PROVIDER_MATRIX",
            "live": False,
            "providers": readiness,
        }

    live_results = []
    for entry in PROVIDER_MATRIX:
        ready = provider_readiness(entry, env)
        if ready["status"] != "READY":
            live_results.append(ready)
            continue
        live_results.append(await live_smoke(entry))
    return {
        "report_type": "BYOK_PROVIDER_MATRIX",
        "live": True,
        "providers": live_results,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run Applyocalypse BYOK provider matrix checks.")
    parser.add_argument("--live", action="store_true", help="Make live litellm calls. Requires real provider keys.")
    args = parser.parse_args(argv)

    live = args.live and os.environ.get("APPLYO_BYOK_LIVE_TESTS") == "1"
    payload = asyncio.run(run_provider_matrix(live=live))
    print(json.dumps(payload, indent=2, sort_keys=True))
    if live and any(provider["status"] == "FAIL" for provider in payload["providers"]):  # type: ignore[index]
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
