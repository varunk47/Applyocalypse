"""Executable tests for the coordinate a click is aimed at.

``element.click()`` produces an event carrying ``isTrusted: false``, which is
the cheapest signal a bot detector has and the first one it reads. So the click
scripts now have a second mode: instead of pressing the control, they measure
it and hand back a point for the worker to dispatch a real mouse event at.

A coordinate is only worth having if it lands on the control, which is a
question about layout, stacking and hit testing rather than about strings.
These run the REAL scripts against the DOM stub so the geometry is actually
exercised, and feed the output through the REAL parser, because that pair is
the whole path a production click takes.
"""
from __future__ import annotations

import json

import pytest
from js_bridge import run_browser_script

from applyocalypse_automation.browser.field_detection import (
    build_click_by_text_script,
    build_final_submit_script,
    parse_click_by_text_result,
    parse_final_submit_result,
)

ORIGIN = "https://jobs.example.com"

# Somewhere down the page, so a stub element left at the default origin cannot
# accidentally satisfy the hit test.
BUTTON_RECT = {"left": 100, "top": 200, "width": 200, "height": 30}
BUTTON_CENTRE = (200.0, 215.0)


def page(*elements: dict) -> dict:
    return {"origin": ORIGIN, "elements": [{"tag": "form", "children": list(elements)}]}


def apply_button(**overrides: object) -> dict:
    return {"tag": "button", "text": "Apply now", "rect": BUTTON_RECT, **overrides}


def banner(rect: dict, *, z_index: str = "10") -> dict:
    return {"tag": "div", "text": "We use cookies", "rect": rect, "style": {"z-index": z_index}}


def locate(spec: dict, labels: list[str] | None = None) -> dict:
    """Run the locate script and return what the adapter would actually see."""
    script = build_click_by_text_script(labels or ["Apply now"], locate_only=True)
    raw = run_browser_script(script, spec)["result"]
    return parse_click_by_text_result(json.dumps(raw)).payload


# ---------------------------------------------------------------------------
# where the press is aimed
# ---------------------------------------------------------------------------


def test_the_point_is_the_middle_of_the_control() -> None:
    payload = locate(page(apply_button()))

    assert payload["click_target"]["x"] == BUTTON_CENTRE[0]
    assert payload["click_target"]["y"] == BUTTON_CENTRE[1]


def test_the_jitter_box_stays_inside_the_control() -> None:
    """Two clicks on one button must not land on the same pixel, or on its border."""
    target = locate(page(apply_button()))["click_target"]

    assert target["x"] - target["jx"] > BUTTON_RECT["left"]
    assert target["x"] + target["jx"] < BUTTON_RECT["left"] + BUTTON_RECT["width"]
    assert target["y"] - target["jy"] > BUTTON_RECT["top"]
    assert target["y"] + target["jy"] < BUTTON_RECT["top"] + BUTTON_RECT["height"]


def test_a_small_control_gets_a_proportionally_small_box() -> None:
    """A checkbox-sized control cannot afford the same wander as a banner button."""
    small = {"left": 100, "top": 200, "width": 40, "height": 20}

    target = locate(page(apply_button(rect=small)))["click_target"]

    assert target["jx"] == pytest.approx(small["width"] * 0.2)
    assert target["jy"] == pytest.approx(small["height"] * 0.2)


def test_a_full_width_button_does_not_get_a_full_width_jitter_box() -> None:
    """A page-wide call to action would otherwise scatter presses across half a screen."""
    wide = {"left": 0, "top": 400, "width": 1200, "height": 90}

    target = locate(page(apply_button(rect=wide)))["click_target"]

    assert target["jx"] == 12
    assert target["jy"] == 8


def test_a_button_reports_where_it_is_not_that_it_was_pressed() -> None:
    """The label and tag still come back, so an approval prompt reads the same."""
    payload = locate(page(apply_button()))

    assert payload["clicked_label"] == "Apply now"
    assert payload["clicked_tag"] == "button"


def test_an_apply_link_still_carries_its_destination() -> None:
    spec = page({"tag": "a", "text": "Apply now", "attrs": {"href": "/apply"}, "rect": BUTTON_RECT})

    payload = locate(spec)

    assert payload["href"] == f"{ORIGIN}/apply"
    assert payload["click_target"]["x"] == BUTTON_CENTRE[0]


def test_asking_the_page_to_click_gets_no_coordinates() -> None:
    """The press script is unchanged, and must stay that way: it is the fallback."""
    script = build_click_by_text_script(["Apply now"], locate_only=False)

    raw = run_browser_script(script, page(apply_button()))["result"]

    assert raw["ok"] is True
    assert "click_target" not in raw


# ---------------------------------------------------------------------------
# controls something else is sitting on
# ---------------------------------------------------------------------------


def test_a_cookie_banner_over_the_button_refuses_the_coordinate() -> None:
    """Pressing here would accept cookies instead, and on a form that is not safe."""
    covering = banner({"left": 0, "top": 150, "width": 800, "height": 200})

    payload = locate(page(covering, apply_button()))

    assert payload["fallback"] == "injected_js"
    assert "click_target" not in payload


def test_a_banner_covering_only_one_corner_refuses_too() -> None:
    """The whole jitter box has to be clear, not just the point in the middle.

    Checking only the centre would let a press land on a modal edge whenever the
    draw went that way, which is a bug that shows up once in a few runs and
    reads like flakiness rather than a bug.
    """
    edge = banner({"left": 205, "top": 190, "width": 300, "height": 60})

    payload = locate(page(edge, apply_button()))

    assert payload["fallback"] == "injected_js"


def test_a_button_behind_a_lower_layer_is_still_reachable() -> None:
    """An overlapping element only occludes if it actually paints on top."""
    underneath = banner({"left": 0, "top": 150, "width": 800, "height": 200}, z_index="-1")

    payload = locate(page(underneath, apply_button()))

    assert payload["click_target"]["x"] == BUTTON_CENTRE[0]


def test_the_control_own_children_do_not_count_as_covering_it() -> None:
    """A button is usually a span in a button. Hit testing returns the span."""
    labelled = apply_button(text="", children=[{"tag": "span", "text": "Apply now", "rect": BUTTON_RECT}])

    payload = locate(page(labelled))

    assert payload["click_target"]["x"] == BUTTON_CENTRE[0]


def test_a_covered_control_is_marked_for_the_click_the_page_can_still_do() -> None:
    """``fallback`` is the contract with the adapter: retry, do not give up.

    An injected click reaches the element directly, so a banner cannot stop it.
    Losing that would turn a cosmetic overlay into a failed application.
    """
    covering = banner({"left": 0, "top": 150, "width": 800, "height": 200})

    payload = locate(page(covering, apply_button()))
    pressed = run_browser_script(
        build_click_by_text_script(["Apply now"], locate_only=False),
        page(covering, apply_button()),
    )["result"]

    assert payload["fallback"] == "injected_js"
    assert pressed["ok"] is True


# ---------------------------------------------------------------------------
# refusals that are not about coordinates
# ---------------------------------------------------------------------------


def test_nothing_matching_is_not_a_fallback() -> None:
    """Pressing would find the same nothing, so the adapter must not ask twice."""
    payload = locate(page(apply_button()), ["Start application"])

    assert payload.get("fallback") is None
    assert "no matching safe portal action" in payload["message"]


def test_an_ambiguous_match_is_not_a_fallback() -> None:
    """Two ways to apply is a question for a human, and pressing one would answer it."""
    spec = page(
        apply_button(text="Apply now"),
        {"tag": "a", "text": "Apply now", "attrs": {"href": "/apply"}, "rect": BUTTON_RECT},
    )

    payload = locate(spec)

    assert payload["ambiguity_code"] == "AMBIGUOUS_PORTAL_ACTION"
    assert payload.get("fallback") is None


def test_a_submit_button_is_still_off_limits_to_the_safe_click() -> None:
    """Locating rather than pressing must not become a way around the approval gate."""
    payload = locate(page(apply_button(text="Submit application")), ["Submit application"])

    assert payload.get("click_target") is None
    assert payload.get("fallback") is None


# ---------------------------------------------------------------------------
# the final submit, which is the click that costs something to get wrong
# ---------------------------------------------------------------------------


def test_the_submit_button_reports_a_point_too() -> None:
    spec = page({"tag": "button", "text": "Submit application", "rect": BUTTON_RECT})
    script = build_final_submit_script(["Submit application"], locate_only=True)

    raw = run_browser_script(script, spec)["result"]
    payload = parse_final_submit_result(json.dumps(raw)).payload

    assert payload["action"] == "final_submit"
    assert payload["click_target"]["x"] == BUTTON_CENTRE[0]
    assert payload["click_target"]["y"] == BUTTON_CENTRE[1]


def test_a_covered_submit_button_falls_back_rather_than_pressing_the_overlay() -> None:
    spec = page(
        banner({"left": 0, "top": 150, "width": 800, "height": 200}),
        {"tag": "button", "text": "Submit application", "rect": BUTTON_RECT},
    )
    script = build_final_submit_script(["Submit application"], locate_only=True)

    raw = run_browser_script(script, spec)["result"]
    payload = parse_final_submit_result(json.dumps(raw)).payload

    assert payload["fallback"] == "injected_js"
    assert "click_target" not in payload
