"""Fields that live in a same-origin iframe or an open shadow root.

Discovery used to be a single ``document.querySelectorAll`` over the document the
script was injected into. A portal that renders its form inside a same-origin
``<iframe>``, or inside a web component, was therefore invisible: the run reported
no fields and paused with nothing to show, on a page a human can see and fill.

Making discovery walk those roots is only half of it, and the dangerous half alone.
The selector it invents is resolved again later by the write script and once more by
the verify script, both of which also started from ``document``. So a field found at
``#email`` inside the embedded form would be written to whatever ``#email`` the
*parent* page happens to hold, and then read back from that same wrong element and
reported as verified. The run reaches the submit gate believing a required question
was answered. That is strictly worse than not finding the field at all.

So the field carries the hops it took to reach it, and all three scripts replay them
through one shared resolver. These tests run the REAL scripts against a DOM stub
that has real nested roots, and the assertions are mostly about which of two
identically named inputs a write actually landed in.
"""
from __future__ import annotations

import json
from typing import Any

import pytest
from js_bridge import run_browser_script

from applyocalypse_automation.browser.field_detection import (
    DOM_FIELD_DISCOVERY_SCRIPT,
    build_apply_field_value_script,
    build_verify_field_value_script,
    dom_path_for,
    fields_from_dom_snapshot,
    parse_apply_field_result,
)

# An employer careers page that embeds its ATS form, keeps a newsletter signup of
# its own, and renders the location question as a web component. Every one of the
# three roots has an input the others also have a name for.
EMBEDDED_PORTAL = {
    "elements": [
        {
            "tag": "form",
            "children": [
                {"tag": "label", "attrs": {"for": "email"}, "text": "Newsletter email"},
                {"tag": "input", "attrs": {"id": "email", "name": "email", "type": "email"}},
            ],
        },
        {
            "tag": "iframe",
            "attrs": {"id": "grnhse_iframe", "src": "https://job-boards.greenhouse.io/acme/jobs/1"},
            "frame": {
                "elements": [
                    {
                        "tag": "form",
                        "children": [
                            {"tag": "label", "attrs": {"for": "email"}, "text": "Email"},
                            {"tag": "input", "attrs": {"id": "email", "name": "email", "type": "email"}},
                            {"tag": "label", "attrs": {"for": "first_name"}, "text": "First name"},
                            {"tag": "input", "attrs": {"id": "first_name", "name": "first_name"}},
                        ],
                    }
                ]
            },
        },
        {
            "tag": "location-picker",
            "attrs": {"id": "location-picker"},
            "shadow": [
                {"tag": "label", "attrs": {"for": "location"}, "text": "Preferred location"},
                {"tag": "input", "attrs": {"id": "location", "name": "location"}},
            ],
        },
    ]
}


def discover(spec: dict[str, Any]) -> list[Any]:
    """Run the real discovery script and map it the way an adapter does."""
    outcome = run_browser_script(DOM_FIELD_DISCOVERY_SCRIPT, spec)
    return fields_from_dom_snapshot(outcome["result"])


def field_named(fields: list[Any], label: str) -> Any:
    matches = [field for field in fields if field.label == label]
    assert len(matches) == 1, f"expected exactly one {label!r}, got {[f.label for f in matches]}"
    return matches[0]


def value_in(state: list[dict[str, Any]], root: str, element_id: str) -> Any:
    """The value of one control, addressed by root as well as by id.

    ``state_for`` matches on id alone and returns the first hit, which is precisely
    the ambiguity these tests exist to detect. A test that used it would pass while
    the write landed in the wrong document.
    """
    for entry in state:
        if entry.get("id") == element_id and entry.get("root") == root:
            return entry.get("value")
    raise AssertionError(f"no #{element_id} in root {root!r}; roots present: {sorted({e['root'] for e in state})}")


class TestDiscovery:
    def test_it_finds_the_fields_the_top_document_cannot_see(self) -> None:
        labels = sorted(field.label for field in discover(EMBEDDED_PORTAL))

        assert labels == ["Email", "First name", "Newsletter email", "Preferred location"]

    @pytest.mark.parametrize(
        ("label", "expected_path"),
        [
            ("Newsletter email", []),
            (
                "Email",
                [{"kind": "frame", "selector": "#grnhse_iframe", "index": 0}],
            ),
            (
                "First name",
                [{"kind": "frame", "selector": "#grnhse_iframe", "index": 0}],
            ),
            (
                "Preferred location",
                [{"kind": "shadow", "selector": "#location-picker", "index": 0}],
            ),
        ],
    )
    def test_every_field_records_how_to_get_back_to_it(
        self, label: str, expected_path: list[dict[str, Any]]
    ) -> None:
        assert dom_path_for(field_named(discover(EMBEDDED_PORTAL), label)) == expected_path

    def test_a_page_that_embeds_nothing_carries_no_path_at_all(self) -> None:
        """The metadata of an ordinary portal is byte for byte what it always was."""
        plain = {
            "elements": [
                {
                    "tag": "form",
                    "children": [
                        {"tag": "label", "attrs": {"for": "email"}, "text": "Email"},
                        {"tag": "input", "attrs": {"id": "email", "name": "email"}},
                    ],
                }
            ]
        }

        assert "dom_path" not in discover(plain)[0].metadata

    def test_a_label_inside_a_shadow_root_is_read_from_that_root(self) -> None:
        """``label[for]`` is scoped to the root it lives in.

        Resolved against the top document it finds nothing, and a field the page
        shows plainly labelled is reported unlabelled and sent for human review.
        """
        field = field_named(discover(EMBEDDED_PORTAL), "Preferred location")

        assert field.metadata["label_source"] == "label_for"
        assert not field.metadata.get("label_synthetic")


class TestFrameFiltering:
    def test_it_does_not_walk_into_a_captcha_frame(self) -> None:
        """A CAPTCHA frame really does hold inputs, which is what makes it dangerous.

        Scanning it hands the model a challenge box dressed as an application
        question. The deny list is the one the adapter already applies to
        out-of-process frames, shared with the injected script by construction so
        the two cannot drift apart.
        """
        page = {
            "elements": [
                {
                    "tag": "iframe",
                    "attrs": {"id": "captcha", "src": "https://www.google.com/recaptcha/api2/anchor"},
                    "frame": {
                        "elements": [
                            {"tag": "label", "attrs": {"for": "g-recaptcha-response"}, "text": "I am not a robot"},
                            {"tag": "input", "attrs": {"id": "g-recaptcha-response", "name": "g-recaptcha-response"}},
                        ]
                    },
                }
            ]
        }

        assert discover(page) == []

    def test_it_still_enters_a_frame_the_portal_wrote_itself(self) -> None:
        """An empty src is a srcdoc or script-built frame, which is where a portal
        puts a form it renders itself. Only a URL that names a known non-form frame
        is skipped."""
        page = {
            "elements": [
                {
                    "tag": "iframe",
                    "attrs": {"id": "app"},
                    "frame": {
                        "elements": [
                            {"tag": "label", "attrs": {"for": "phone"}, "text": "Phone"},
                            {"tag": "input", "attrs": {"id": "phone", "name": "phone"}},
                        ]
                    },
                }
            ]
        }

        assert [field.label for field in discover(page)] == ["Phone"]


class TestAmbiguity:
    def test_the_same_id_in_two_roots_is_two_fields_and_not_a_collision(self) -> None:
        for label in ("Newsletter email", "Email"):
            field = field_named(discover(EMBEDDED_PORTAL), label)
            assert field.selector == "#email"
            assert not field.metadata.get("ambiguous_selector")

    def test_the_same_id_twice_in_one_root_is_still_a_collision(self) -> None:
        """The protection this replaces must survive being made root-aware.

        Two controls under one id in a single document are two questions whose
        selectors are the same element: the second answer overwrites the first and
        verify reads that one element back and calls both writes successful.
        """
        duplicated = {
            "elements": [
                {
                    "tag": "iframe",
                    "attrs": {"id": "app"},
                    "frame": {
                        "elements": [
                            {"tag": "label", "attrs": {"for": "email"}, "text": "Email"},
                            {"tag": "input", "attrs": {"id": "email", "name": "email"}},
                            {"tag": "label", "attrs": {"for": "email"}, "text": "Email (mobile)"},
                            {"tag": "input", "attrs": {"id": "email", "name": "email"}},
                        ]
                    },
                }
            ]
        }

        fields = discover(duplicated)

        assert len(fields) == 2
        for field in fields:
            assert field.selector is None
            assert field.metadata["requires_human_selector_review"] is True


class TestWriting:
    def test_the_answer_lands_in_the_embedded_form_and_not_the_page(self) -> None:
        """The failure this whole change exists to prevent.

        Without the path the write resolves ``#email`` from the top document, fills
        the employer's newsletter box, reads that box back, and reports the
        application's email question as answered and verified.
        """
        field = field_named(discover(EMBEDDED_PORTAL), "Email")

        outcome = run_browser_script(
            build_apply_field_value_script(field.selector, "ada@example.com", dom_path_for(field)),
            EMBEDDED_PORTAL,
        )

        assert parse_apply_field_result(outcome["result"], field).ok is True
        assert value_in(outcome["state"], "frame:#grnhse_iframe", "email") == "ada@example.com"
        assert value_in(outcome["state"], "document", "email") == ""

    def test_a_field_in_the_page_is_written_exactly_as_it_always_was(self) -> None:
        field = field_named(discover(EMBEDDED_PORTAL), "Newsletter email")
        assert dom_path_for(field) == []

        outcome = run_browser_script(
            build_apply_field_value_script(field.selector, "ada@example.com", dom_path_for(field)),
            EMBEDDED_PORTAL,
        )

        assert value_in(outcome["state"], "document", "email") == "ada@example.com"
        assert value_in(outcome["state"], "frame:#grnhse_iframe", "email") == ""

    def test_it_writes_into_an_open_shadow_root(self) -> None:
        field = field_named(discover(EMBEDDED_PORTAL), "Preferred location")

        outcome = run_browser_script(
            build_apply_field_value_script(field.selector, "Remote", dom_path_for(field)),
            EMBEDDED_PORTAL,
        )

        assert parse_apply_field_result(outcome["result"], field).ok is True
        assert value_in(outcome["state"], "shadow:#location-picker", "location") == "Remote"

    def test_a_path_that_no_longer_resolves_fails_instead_of_falling_back(self) -> None:
        """A frame navigates, a component re-renders, and the path goes stale.

        Resolving from the top document instead is the tempting recovery and the
        wrong one: it finds the newsletter box, writes there, verifies there, and
        reports success. Refusing is the only answer that leaves the run honest.
        """
        gone = [{"kind": "frame", "selector": "#not-here", "index": 9}]

        outcome = run_browser_script(
            build_apply_field_value_script("#email", "ada@example.com", gone), EMBEDDED_PORTAL
        )
        verdict = outcome["result"]

        assert verdict["ok"] is False
        assert "no longer reachable" in verdict["message"]
        assert value_in(outcome["state"], "document", "email") == ""


class TestVerifying:
    def test_it_reads_back_from_the_root_it_wrote_to(self) -> None:
        """Write and verify have to agree on what the address means.

        If only the writer replays the path, the answer lands in the embedded form
        and the verifier reads the empty box in the page, so a write that genuinely
        worked is reported as lost and repaired into the wrong field.
        """
        spec = json.loads(json.dumps(EMBEDDED_PORTAL))
        spec["elements"][1]["frame"]["elements"][0]["children"][1]["value"] = "ada@example.com"
        field = field_named(discover(spec), "Email")

        outcome = run_browser_script(
            build_verify_field_value_script(field.selector, "ada@example.com", dom_path_for(field)), spec
        )

        assert parse_apply_field_result(outcome["result"], field).ok is True

    def test_it_does_not_accept_the_parent_page_as_evidence(self) -> None:
        spec = json.loads(json.dumps(EMBEDDED_PORTAL))
        spec["elements"][0]["children"][1]["value"] = "ada@example.com"
        field = field_named(discover(spec), "Email")

        outcome = run_browser_script(
            build_verify_field_value_script(field.selector, "ada@example.com", dom_path_for(field)), spec
        )

        assert parse_apply_field_result(outcome["result"], field).ok is False
