"""Read worker secrets from an env-pointed file, falling back to plain env vars."""
from __future__ import annotations

import json
import os
from functools import lru_cache


@lru_cache(maxsize=1)
def _secrets_from_file() -> dict[str, str]:
    path = os.getenv("APPLYO_SECRETS_FILE", "")
    if not path:
        return {}
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        return {str(k): str(v) for k, v in data.items()} if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def get_secret(name: str) -> str | None:
    value = _secrets_from_file().get(name)
    if value:
        return value
    return os.getenv(name) or None


def apply_provider_secrets_to_env() -> None:
    """Export provider credentials from the secrets file into this process env.

    LiteLLM and boto read provider API keys from ``os.environ``. The Electron
    main process keeps those keys out of the child-process spawn env and ships
    them in the 0600 secrets file instead, so the worker exports them itself
    before any LLM call. Worker-internal ``APPLYO_*`` secrets stay file-only.
    """
    for name, value in _secrets_from_file().items():
        if name.startswith("APPLYO_") or not value:
            continue
        os.environ[name] = value
