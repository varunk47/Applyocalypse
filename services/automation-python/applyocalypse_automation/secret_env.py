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
