"""The drivers the adapters reach for at launch, checked without launching anything."""

from __future__ import annotations

import inspect

import pytest

from applyocalypse_automation.browser import (
    nodriver_adapter,
    playwright_adapter,
    seleniumbase_adapter,
)
from applyocalypse_automation.browser.driver_check import (
    _DRIVERS,
    DriverStatus,
    check_all_drivers,
    check_driver,
    missing_required,
)


def test_the_automatic_chain_is_what_is_required() -> None:
    """nodriver and seleniumbase are the pair the fallback chain actually uses.

    Playwright is reported so a build can say what it has, but it is deliberately not a
    dependency, so demanding it would fail every honest build.
    """
    required = {adapter for adapter, (_m, _a, is_required) in _DRIVERS.items() if is_required}

    assert required == {"nodriver", "seleniumbase"}
    assert _DRIVERS["playwright"][2] is False


@pytest.mark.parametrize(
    ("adapter", "module", "statement"),
    [
        ("nodriver", nodriver_adapter, "import nodriver"),
        ("seleniumbase", seleniumbase_adapter, "from seleniumbase import SB"),
        ("playwright", playwright_adapter, "from playwright.async_api import async_playwright"),
    ],
)
def test_each_entry_imports_what_its_adapter_imports(adapter: str, module: object, statement: str) -> None:
    """A check against a different symbol would pass while the real launch import fails.

    Reading the adapter source is the only way to notice that drift, because the import
    lives inside ``launch()`` and never runs during a test that does not open a browser.
    """
    assert statement in inspect.getsource(module), f"{adapter} no longer imports {statement!r}"

    module_name, attribute, _required = _DRIVERS[adapter]
    assert module_name in statement
    if attribute is not None:
        assert attribute in statement


def test_a_present_driver_reports_available(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(_DRIVERS, "nodriver", ("json", "loads", True))

    status = check_driver("nodriver")

    assert status.available is True
    assert status.error is None
    assert status.module == "json"


@pytest.mark.parametrize(
    ("entry", "expected"),
    [
        (("applyocalypse_no_such_driver", None, True), "ModuleNotFoundError"),
        # A driver that imports but lost the symbol is just as broken as one that is gone,
        # and it is the failure a bundle trimmed too aggressively actually produces.
        (("json", "no_such_attribute", True), "AttributeError"),
    ],
)
def test_a_broken_driver_reports_why(
    entry: tuple[str, str | None, bool], expected: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(_DRIVERS, "nodriver", entry)

    status = check_driver("nodriver")

    assert status.available is False
    assert status.error is not None
    assert status.error.startswith(expected)


def test_missing_required_ignores_an_absent_optional_driver() -> None:
    statuses = [
        DriverStatus("nodriver", "nodriver", True, True, None),
        DriverStatus("seleniumbase", "seleniumbase", True, True, None),
        DriverStatus("playwright", "playwright.async_api", False, False, "ModuleNotFoundError: x"),
    ]

    assert missing_required(statuses) == []


def test_missing_required_names_the_absent_one() -> None:
    broken = DriverStatus("nodriver", "nodriver", True, False, "ModuleNotFoundError: x")
    statuses = [broken, DriverStatus("seleniumbase", "seleniumbase", True, True, None)]

    assert missing_required(statuses) == [broken]


def test_check_all_drivers_covers_every_entry() -> None:
    statuses = check_all_drivers()

    assert {status.adapter for status in statuses} == set(_DRIVERS)
    assert all(isinstance(status.to_payload()["available"], bool) for status in statuses)
