from __future__ import annotations

from .adapter import BrowserAdapter
from .playwright_adapter import PlaywrightBrowserAdapter
from .portal_workflows import PortalWorkflow
from .seleniumbase_adapter import SeleniumBaseBrowserAdapter

SUPPORTED_BROWSER_ADAPTERS = ("playwright", "seleniumbase")


def create_browser_adapter(adapter_name: str | None) -> BrowserAdapter:
    normalized = (adapter_name or "playwright").strip().lower()
    if normalized == "playwright":
        return PlaywrightBrowserAdapter()
    if normalized == "seleniumbase":
        return SeleniumBaseBrowserAdapter()
    raise ValueError(f"Unsupported browser adapter: {adapter_name}")


# The Playwright-protocol adapter first, then seleniumbase last.
#
# playwright_adapter.py enumerates cross-origin frames, resolves a field inside the frame
# that owns it and clicks across frames, and seleniumbase_adapter.py does none of that, so
# seleniumbase stays where it belongs: the last thing tried before giving up. nodriver
# used to lead this chain; it was removed because its AGPL-3.0 licence could not ship in
# the app and it had no path to parity on macOS.
_FALLBACK_ORDER: tuple[str, ...] = ("playwright", "seleniumbase")


def adapter_candidates_for_workflow(workflow: PortalWorkflow, preferred_adapter_name: str | None = None) -> tuple[str, ...]:
    preferred = (preferred_adapter_name or workflow.default_adapter or "playwright").strip().lower()
    if preferred not in SUPPORTED_BROWSER_ADAPTERS:
        raise ValueError(f"Unsupported browser adapter: {preferred_adapter_name}")

    ordered = [preferred]
    for adapter_name in (workflow.default_adapter, *_FALLBACK_ORDER):
        normalized = adapter_name.strip().lower()
        if normalized in SUPPORTED_BROWSER_ADAPTERS and normalized not in ordered:
            ordered.append(normalized)
    return tuple(ordered)
