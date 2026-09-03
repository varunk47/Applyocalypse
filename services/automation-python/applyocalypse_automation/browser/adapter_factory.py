from __future__ import annotations

from .adapter import BrowserAdapter
from .nodriver_adapter import NodriverBrowserAdapter
from .playwright_adapter import PlaywrightBrowserAdapter
from .portal_workflows import PortalWorkflow
from .seleniumbase_adapter import SeleniumBaseBrowserAdapter

SUPPORTED_BROWSER_ADAPTERS = ("nodriver", "playwright", "seleniumbase")


def create_browser_adapter(adapter_name: str | None) -> BrowserAdapter:
    normalized = (adapter_name or "nodriver").strip().lower()
    if normalized == "playwright":
        return PlaywrightBrowserAdapter()
    if normalized == "nodriver":
        return NodriverBrowserAdapter()
    if normalized == "seleniumbase":
        return SeleniumBaseBrowserAdapter()
    raise ValueError(f"Unsupported browser adapter: {adapter_name}")


# nodriver first, then the Playwright-protocol adapter, then seleniumbase last.
#
# The middle slot used to be empty: Playwright was not a dependency and the PyInstaller
# build carried none of it, so every automatic attempt at it failed on the spot and wrote
# a misleading "playwright is not installed" line into the record the UI shows, ahead of
# the fallback that could actually work. Dropping it was right then. It is wrong now that
# the driver is Patchright and ships in the bundle, because of what the two remaining
# adapters can each do: playwright_adapter.py enumerates cross-origin frames, resolves a
# field inside the frame that owns it and clicks across frames, and seleniumbase_adapter.py
# does none of that. Falling straight from nodriver to seleniumbase means falling straight
# out of iframe support, which is most of what an ATS application form is made of. So the
# adapter that keeps the capability goes ahead of the one that drops it, and seleniumbase
# stays where it belongs: the last thing tried before giving up.
_FALLBACK_ORDER: tuple[str, ...] = ("nodriver", "playwright", "seleniumbase")


def adapter_candidates_for_workflow(workflow: PortalWorkflow, preferred_adapter_name: str | None = None) -> tuple[str, ...]:
    preferred = (preferred_adapter_name or workflow.default_adapter or "nodriver").strip().lower()
    if preferred not in SUPPORTED_BROWSER_ADAPTERS:
        raise ValueError(f"Unsupported browser adapter: {preferred_adapter_name}")

    ordered = [preferred]
    for adapter_name in (workflow.default_adapter, *_FALLBACK_ORDER):
        normalized = adapter_name.strip().lower()
        if normalized in SUPPORTED_BROWSER_ADAPTERS and normalized not in ordered:
            ordered.append(normalized)
    return tuple(ordered)
