"""Whether the drivers the adapters import at launch are actually in this build.

Every adapter imports its driver *inside* ``launch()`` and turns a missing one into a
soft ``"<name> is not installed"`` step failure. That is right at runtime, because the
fallback chain is built on it, but it also means a driver that fell out of the
PyInstaller bundle stays invisible until it happens in front of a user, halfway through
an application. Nothing else in the build asks: PyInstaller finds these imports by
static analysis alone, and seleniumbase already needs hand-maintained ``--hidden-import``
entries to survive that analysis, so the margin is thinner than it looks.

Each entry below imports the same module and binds the same attribute as the adapter it
stands for. Checking a different symbol would let this pass while the real import fails,
which is worse than not checking at all. No browser is started and no network is
touched, so a packaged binary can be asked the question directly and cheaply.
"""

from __future__ import annotations

import importlib
from dataclasses import dataclass

# adapter name -> (module, attribute the adapter binds, is it in the automatic chain)
_DRIVERS: dict[str, tuple[str, str | None, bool]] = {
    # nodriver_adapter.py: ``import nodriver as uc``
    "nodriver": ("nodriver", None, True),
    # seleniumbase_adapter.py: ``from seleniumbase import SB``
    "seleniumbase": ("seleniumbase", "SB", True),
    # playwright_adapter.py: ``from patchright.async_api import async_playwright``.
    # The adapter is named for the protocol it speaks, the module for the driver that
    # speaks it. This one used to be optional, on the grounds that Playwright was not a
    # dependency and the bundle carried none of it; Patchright is a dependency and the
    # bundle carries it, so an absent module here now means a build that lost its middle
    # fallback, which is exactly the failure this file exists to catch before a user does.
    "playwright": ("patchright.async_api", "async_playwright", True),
}


@dataclass(frozen=True)
class DriverStatus:
    adapter: str
    module: str
    required: bool
    available: bool
    error: str | None

    def to_payload(self) -> dict[str, object]:
        return {
            "adapter": self.adapter,
            "module": self.module,
            "required": self.required,
            "available": self.available,
            "error": self.error,
        }


def check_driver(adapter: str) -> DriverStatus:
    module_name, attribute, required = _DRIVERS[adapter]
    try:
        module = importlib.import_module(module_name)
        if attribute is not None:
            getattr(module, attribute)
    except Exception as exc:  # noqa: BLE001 - a broken driver raises whatever it likes
        return DriverStatus(adapter, module_name, required, False, f"{type(exc).__name__}: {exc}")
    return DriverStatus(adapter, module_name, required, True, None)


def check_all_drivers() -> list[DriverStatus]:
    return [check_driver(adapter) for adapter in _DRIVERS]


def missing_required(statuses: list[DriverStatus]) -> list[DriverStatus]:
    return [status for status in statuses if status.required and not status.available]
