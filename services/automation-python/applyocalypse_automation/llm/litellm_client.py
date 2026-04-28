from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class LiteLlmClient:
    model: str

    async def complete_json(self, *, system: str, user: str, schema_name: str) -> dict[str, Any]:
        try:
            from litellm import acompletion  # type: ignore
        except ImportError as exc:
            raise RuntimeError("litellm is required for BYOK provider access") from exc

        response = await acompletion(
            model=self.model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            response_format={"type": "json_object"},
        )
        content = response["choices"][0]["message"]["content"]
        if not isinstance(content, str):
            raise RuntimeError(f"{schema_name} response did not contain text content")

        import json

        parsed = json.loads(content)
        if not isinstance(parsed, dict):
            raise RuntimeError(f"{schema_name} response must be a JSON object")
        return parsed
