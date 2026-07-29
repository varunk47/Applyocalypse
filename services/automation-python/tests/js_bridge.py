"""Runs the worker's injected JavaScript against the Node-based DOM stub.

The browser-facing half of ``field_detection.py`` is JavaScript embedded in
Python string constants. Asserting on the *text* of those constants proves
nothing, so these tests execute the real snippets instead. Node ships with the
repo toolchain (pnpm workspace); when it is genuinely unavailable the tests skip
with an explicit reason rather than silently passing.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

_RUNNER = Path(__file__).parent / "js" / "run_script.mjs"


def require_node() -> str:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not available; cannot execute the injected browser scripts")
    return node


def run_browser_script(script: str, spec: dict[str, Any]) -> dict[str, Any]:
    """Evaluate ``script`` against a stub DOM built from ``spec``.

    Returns ``{"result": <parsed JSON returned by the script>, "state": [...]}``
    where ``state`` is a per-field snapshot (value, checked, focus/blur counts,
    native prototype setter call counts, and whether a React value tracker
    observed the change).
    """
    node = require_node()
    payload = json.dumps({"spec": spec, "script": script})
    completed = subprocess.run(
        [node, str(_RUNNER)],
        input=payload,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        check=False,
    )
    if not completed.stdout.strip():
        raise AssertionError(f"node produced no output: {completed.stderr}")
    envelope = json.loads(completed.stdout)
    if "error" in envelope:
        raise AssertionError(f"injected script raised: {envelope['error']}")
    result = envelope.get("result")
    if isinstance(result, str):
        result = json.loads(result)
    return {"result": result, "state": envelope.get("state", [])}


def run_node_expression(source: str) -> Any:
    """Evaluate a self-contained JS expression and return its JSON value."""
    node = require_node()
    completed = subprocess.run(
        [node, "--input-type=module", "-e", source],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        check=False,
    )
    if completed.returncode != 0:
        raise AssertionError(f"node failed: {completed.stderr}")
    return json.loads(completed.stdout)


def state_for(state: list[dict[str, Any]], element_id: str) -> dict[str, Any]:
    for entry in state:
        if entry.get("id") == element_id:
            return entry
    raise AssertionError(f"no element with id {element_id!r} in stub DOM state")
