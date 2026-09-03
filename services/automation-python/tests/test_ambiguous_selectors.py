"""Two fields that answer to one selector must not both be written blind.

``selectorFor`` emits ``#id`` for any control carrying an id, and the write and verify
scripts resolve it with ``document.querySelector``, which returns the first match. A
page with a repeated section, or a mobile copy of the same form, produces two controls
under one id. Without a guard the second answer overwrites the first, verify reads that
same element back, and both writes report success.
"""

from __future__ import annotations

import pytest

from applyocalypse_automation.browser.field_detection import FrameRef, fields_from_dom_snapshot


def _raw(label: str, selector: str | None, field_type: str = "text") -> dict[str, object]:
    return {
        "label": label,
        "label_source": "label_for",
        "field_type": field_type,
        "selector": selector,
        "required": True,
        "metadata": {},
    }


def test_a_selector_two_fields_share_is_dropped_from_both() -> None:
    """Neither one may keep it: there is no way to tell which element is which."""
    fields = fields_from_dom_snapshot([_raw("Email", "#email"), _raw("Confirm email", "#email")])

    assert len(fields) == 2
    assert [field.selector for field in fields] == [None, None]
    for field in fields:
        assert field.metadata["ambiguous_selector"] == "#email"
        assert field.metadata["requires_human_selector_review"] is True


def test_the_field_is_surfaced_not_dropped() -> None:
    """A question nobody can see is worse than one nobody can fill (audit finding F6)."""
    fields = fields_from_dom_snapshot([_raw("Email", "#email"), _raw("Confirm email", "#email")])

    assert [field.label for field in fields] == ["Email", "Confirm email"]
    assert all(field.required for field in fields)


def test_an_ambiguous_field_carries_the_confidence_of_a_selectorless_one() -> None:
    """It is exactly as writable as a field discovery never found a selector for."""
    ambiguous = fields_from_dom_snapshot([_raw("Email", "#email"), _raw("Email", "#email")])
    selectorless = fields_from_dom_snapshot([_raw("Email", None)])

    assert {field.confidence for field in ambiguous} == {selectorless[0].confidence}


def test_a_unique_selector_is_untouched() -> None:
    fields = fields_from_dom_snapshot([_raw("Email", "#email"), _raw("Phone", "#phone")])

    assert [field.selector for field in fields] == ["#email", "#phone"]
    for field in fields:
        assert "ambiguous_selector" not in field.metadata
        assert "requires_human_selector_review" not in field.metadata


@pytest.mark.parametrize(
    ("first", "second"),
    [
        # A radio group shares a name on purpose; selectorFor disambiguates it by value,
        # so the two selectors differ and neither may be treated as a collision.
        ('input[name="eeo_gender"][value="female"]', 'input[name="eeo_gender"][value="male"]'),
        ("#first_name", "#last_name"),
        ('input[name="street"]', 'input[name="city"]'),
    ],
)
def test_distinct_selectors_never_collide(first: str, second: str) -> None:
    fields = fields_from_dom_snapshot([_raw("One", first, "radio"), _raw("Two", second, "radio")])

    assert [field.selector for field in fields] == [first, second]


def test_fields_with_no_selector_do_not_collide_with_each_other() -> None:
    """Two absent selectors are not one shared selector."""
    fields = fields_from_dom_snapshot([_raw("One", None), _raw("Two", None)])

    assert [field.selector for field in fields] == [None, None]
    for field in fields:
        assert "ambiguous_selector" not in field.metadata


def test_the_same_selector_in_two_frames_is_not_a_collision() -> None:
    """Discovery runs per frame and each field remembers its own, so these resolve apart.

    Greenhouse embeds its form from job-boards.greenhouse.io onto an employer domain,
    so an id repeated between the host page and the embedded form is two elements in
    two documents, each addressed correctly.
    """
    top = fields_from_dom_snapshot([_raw("Email", "#email")])
    embedded = fields_from_dom_snapshot(
        [_raw("Email", "#email")], frame=FrameRef(url="https://job-boards.greenhouse.io/x", index=1)
    )

    assert top[0].selector == "#email"
    assert embedded[0].selector == "#email"


def test_three_way_collision_drops_all_three() -> None:
    fields = fields_from_dom_snapshot([_raw(name, "#email") for name in ("A", "B", "C")])

    assert [field.selector for field in fields] == [None, None, None]


def test_only_the_colliding_selector_is_dropped() -> None:
    fields = fields_from_dom_snapshot(
        [_raw("Email", "#email"), _raw("Phone", "#phone"), _raw("Confirm", "#email")]
    )

    assert [field.selector for field in fields] == [None, "#phone", None]
