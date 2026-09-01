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


def adapter_candidates_for_workflow(workflow: PortalWorkflow, preferred_adapter_name: str | None = None) -> tuple[str, ...]:
    preferred = (preferred_adapter_name or workflow.default_adapter or "nodriver").strip().lower()
    if preferred not in SUPPORTED_BROWSER_ADAPTERS:
        raise ValueError(f"Unsupported browser adapter: {preferred_adapter_name}")

    # high-stealth boards: nodriver -> seleniumbase
    if workflow.requires_high_stealth:
        ordered = [preferred] if preferred in ("nodriver", "seleniumbase") else ["nodriver"]
        for name in ("nodriver", "seleniumbase"):
            if name not in ordered:
                ordered.append(name)
        return tuple(ordered)

    # ATS portals: nodriver -> seleniumbase, the same pair as the high-stealth boards.
    # Playwright is deliberately not in the automatic chain. It is not a dependency of
    # this project and the PyInstaller build carries zero playwright modules, so on a
    # real install every attempt at it fails on the spot. Leaving it here cost the run
    # a launch that could not succeed and wrote a misleading "playwright is not
    # installed" attempt into the record the UI shows, in front of the fallback that
    # can actually work. It stays reachable for anyone who installs it and names it.
    ordered = [preferred]
    for adapter_name in (workflow.default_adapter, "nodriver", "seleniumbase"):
        normalized = adapter_name.strip().lower()
        if normalized in SUPPORTED_BROWSER_ADAPTERS and normalized not in ordered:
            ordered.append(normalized)
    return tuple(ordered)
