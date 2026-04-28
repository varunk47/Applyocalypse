from __future__ import annotations

from .portal_workflows import PortalWorkflow
from .adapter import BrowserAdapter
from .nodriver_adapter import NodriverBrowserAdapter
from .playwright_adapter import PlaywrightBrowserAdapter

SUPPORTED_BROWSER_ADAPTERS = ("nodriver", "playwright")


def create_browser_adapter(adapter_name: str | None) -> BrowserAdapter:
    normalized = (adapter_name or "nodriver").strip().lower()
    if normalized == "playwright":
        return PlaywrightBrowserAdapter()
    if normalized == "nodriver":
        return NodriverBrowserAdapter()
    raise ValueError(f"Unsupported browser adapter: {adapter_name}")


def adapter_candidates_for_workflow(workflow: PortalWorkflow, preferred_adapter_name: str | None = None) -> tuple[str, ...]:
    preferred = (preferred_adapter_name or workflow.default_adapter or "nodriver").strip().lower()
    if preferred not in SUPPORTED_BROWSER_ADAPTERS:
        raise ValueError(f"Unsupported browser adapter: {preferred_adapter_name}")

    if workflow.requires_high_stealth:
        return ("nodriver",)

    ordered = [preferred]
    for adapter_name in (workflow.default_adapter, "playwright", "nodriver"):
        normalized = adapter_name.strip().lower()
        if normalized in SUPPORTED_BROWSER_ADAPTERS and normalized not in ordered:
            ordered.append(normalized)
    return tuple(ordered)
