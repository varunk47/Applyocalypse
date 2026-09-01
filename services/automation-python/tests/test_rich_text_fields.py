"""A long-form answer box that is not a ``<textarea>``.

Greenhouse, Lever, Ashby and every Workday tenant with a custom question set render
their "tell us about yourself" boxes with Quill, ProseMirror, TipTap or Lexical.
None of those is a form control: the editing surface is a ``contenteditable`` host,
and discovery's ``input, textarea, select`` sweep cannot see one at all. The failure
that produces is the quiet kind. The form reports no missing fields, the run walks
to the submit gate, and the required question is blank.

Writing to one is its own problem. Every editor here keeps its own document model
and treats the DOM as a projection of it, so assigning ``textContent`` updates the
projection and the editor's next render paints the model straight back over it. The
field looks filled for an instant and is empty by the time anyone checks. Only a
real insertion, which raises the ``beforeinput`` the editor listens for, survives.

These tests run the REAL discovery, write and verify scripts against a DOM stub
whose editor behaves that way, so a write that merely looks plausible fails here
rather than on somebody's application.
"""
from __future__ import annotations

from copy import deepcopy
from typing import Any

from js_bridge import run_browser_script

from applyocalypse_automation.browser.field_detection import (
    DOM_FIELD_DISCOVERY_SCRIPT,
    SCRIPTED_WRITE_FIELD_TYPES,
    build_apply_field_value_script,
    build_verify_field_value_script,
    dom_path_for,
    fields_from_dom_snapshot,
    parse_apply_field_result,
)

# A Greenhouse-shaped form: a Quill editor for the long answer, a plain textarea
# beside it, a picker that is editable *and* a combobox, and an editor the page has
# styled away. Every one of these is a way for the new sweep to be wrong.
PORTAL = {
    "elements": [
        {
            "tag": "form",
            "children": [
                {"tag": "span", "attrs": {"id": "pitch-label"}, "text": "Why do you want to work here?"},
                {
                    "tag": "div",
                    "attrs": {"class": "ql-container"},
                    "children": [
                        {
                            "tag": "div",
                            "attrs": {
                                "id": "pitch",
                                "class": "ql-editor",
                                "contenteditable": "true",
                                "aria-labelledby": "pitch-label",
                                "aria-required": "true",
                            },
                            "richTextEditor": True,
                        }
                    ],
                },
                {"tag": "label", "attrs": {"for": "notes"}, "text": "Anything else"},
                {"tag": "textarea", "attrs": {"id": "notes", "name": "notes"}},
                {
                    "tag": "div",
                    "attrs": {
                        "id": "country",
                        "role": "combobox",
                        "contenteditable": "true",
                        "aria-label": "Country",
                    },
                },
                {
                    "tag": "div",
                    "attrs": {"id": "ghost", "contenteditable": "true", "aria-label": "Withdrawn question"},
                    "style": {"display": "none"},
                },
            ],
        }
    ]
}


def discover(spec: dict[str, Any]) -> list[Any]:
    return fields_from_dom_snapshot(run_browser_script(DOM_FIELD_DISCOVERY_SCRIPT, spec)["result"])


def field_named(fields: list[Any], label: str) -> Any:
    matches = [field for field in fields if field.label == label]
    assert len(matches) == 1, f"expected exactly one {label!r}, got {[f.label for f in fields]}"
    return matches[0]


def state_of(state: list[dict[str, Any]], element_id: str, root: str = "document") -> dict[str, Any]:
    for entry in state:
        if entry.get("id") == element_id and entry.get("root") == root:
            return entry
    raise AssertionError(f"no #{element_id} in root {root!r}; present: {[(e['root'], e['id']) for e in state]}")


def write(spec: dict[str, Any], field: Any, value: str) -> dict[str, Any]:
    return run_browser_script(
        build_apply_field_value_script(field.selector, value, dom_path_for(field)), spec
    )


class TestDiscovery:
    def test_the_editor_is_offered_as_a_field_at_all(self) -> None:
        """Undiscovered, this question is simply never asked."""
        field = field_named(discover(PORTAL), "Why do you want to work here?")

        assert field.field_type == "richtext"
        assert field.required is True
        assert field.selector == "#pitch"

    def test_a_textarea_is_not_reported_a_second_time(self) -> None:
        """The native sweep already owns anything with a ``value``.

        ``<textarea contenteditable>`` is pathological markup and portals do ship
        it. Two entries for one control means two answers written to it, and the
        second one lands on the end of the first.
        """
        both_ways = {
            "elements": [
                {
                    "tag": "textarea",
                    "attrs": {"id": "notes", "contenteditable": "true", "aria-label": "Anything else"},
                }
            ]
        }

        types = [field.field_type for field in discover(both_ways)]

        assert types == ["textarea"]

    def test_an_editable_picker_is_still_a_picker(self) -> None:
        """An editable combobox has options to choose from, not prose to type.

        Typing an answer into one leaves the widget's own value untouched, and the
        write then reads its own text back as proof that it worked.
        """
        assert field_named(discover(PORTAL), "Country").field_type == "aria_combobox"

    def test_an_editor_the_page_has_hidden_is_not_offered(self) -> None:
        labels = [field.label for field in discover(PORTAL)]

        assert "Withdrawn question" not in labels

    def test_nested_editable_regions_report_one_surface(self) -> None:
        """Editability inherits, so a naive sweep finds a field per wrapper.

        Where editors genuinely nest, the outer region is the surface a person types
        into; the inner ones are its implementation.
        """
        nested = {
            "elements": [
                {
                    "tag": "div",
                    "attrs": {"id": "letter", "contenteditable": "true", "aria-label": "Cover letter"},
                    "children": [
                        {"tag": "div", "attrs": {"id": "para-1", "contenteditable": "true"}},
                        {"tag": "div", "attrs": {"id": "para-2", "contenteditable": "true"}},
                    ],
                }
            ]
        }

        fields = discover(nested)

        assert [(field.label, field.selector) for field in fields] == [("Cover letter", "#letter")]

    def test_an_editor_with_no_id_is_still_addressable(self) -> None:
        """A Quill host is often a bare styled div with neither id nor name.

        ``aria-label`` is how these actually get named, and it has to be enough or
        the field is discovered and then unfillable.
        """
        bare = {
            "elements": [
                {"tag": "div", "attrs": {"contenteditable": "true", "aria-label": "Portfolio notes"}}
            ]
        }

        field = discover(bare)[0]

        assert field.label == "Portfolio notes"
        assert field.selector == 'div[aria-label="Portfolio notes"]'

    def test_an_editor_inside_an_embedded_form_records_the_way_back(self) -> None:
        """The ATS is usually in an iframe, so this composes with the path walk."""
        embedded = {
            "elements": [
                {
                    "tag": "iframe",
                    "attrs": {"id": "grnhse_iframe", "src": "https://job-boards.greenhouse.io/acme/jobs/1"},
                    "frame": {
                        "elements": [
                            {
                                "tag": "div",
                                "attrs": {"id": "pitch", "contenteditable": "true", "aria-label": "Pitch"},
                                "richTextEditor": True,
                            }
                        ]
                    },
                }
            ]
        }

        field = field_named(discover(embedded), "Pitch")

        assert field.field_type == "richtext"
        assert dom_path_for(field) == [{"kind": "frame", "selector": "#grnhse_iframe", "index": 0}]


class TestWriting:
    def test_the_answer_reaches_the_editor_and_not_only_the_dom(self) -> None:
        """The test this module exists for.

        The stub's editor ignores a ``textContent`` assignment exactly as Quill,
        ProseMirror, TipTap, Lexical and Draft.js do: the model is the truth and the
        DOM is repainted from it. So a write that took the obvious route reads back
        empty here, which is what it would do on a real portal a moment after
        looking like it worked.
        """
        field = field_named(discover(PORTAL), "Why do you want to work here?")
        answer = "Because the platform team owns the thing I want to build."

        outcome = write(PORTAL, field, answer)

        result = parse_apply_field_result(outcome["result"], field)
        assert result.ok is True, result.message
        assert state_of(outcome["state"], "pitch")["text"] == answer

    def test_the_write_is_reported_as_an_insertion(self) -> None:
        """The action names which mechanism actually carried the answer.

        A run that quietly fell back to the direct write on every portal would still
        be green everywhere else, and would be one editor upgrade away from silently
        losing every long answer.
        """
        field = field_named(discover(PORTAL), "Why do you want to work here?")

        outcome = write(PORTAL, field, "Because of the platform work.")

        assert outcome["result"]["action"] == "insert_text"
        assert state_of(outcome["state"], "pitch")["text_content_writes"] == 0

    def test_a_draft_already_in_the_box_is_replaced_not_extended(self) -> None:
        """``clear()`` does nothing to a contenteditable, which is the trap.

        A portal that restores a saved draft, or a repair pass on a field written
        once already, would otherwise submit the answer twice over.
        """
        drafted = {
            "elements": [
                {
                    "tag": "div",
                    "attrs": {"id": "pitch", "contenteditable": "true", "aria-label": "Pitch"},
                    "text": "Half a sentence I started last",
                    "richTextEditor": True,
                }
            ]
        }
        field = discover(drafted)[0]

        outcome = write(drafted, field, "The finished answer.")

        assert state_of(outcome["state"], "pitch")["text"] == "The finished answer."

    def test_a_plain_editable_div_with_no_editor_behind_it_is_filled(self) -> None:
        """Not every contenteditable is a framework; some are just a div."""
        plain = {
            "elements": [{"tag": "div", "attrs": {"id": "pitch", "contenteditable": "true", "aria-label": "Pitch"}}]
        }
        field = discover(plain)[0]

        outcome = write(plain, field, "A short answer.")

        assert parse_apply_field_result(outcome["result"], field).ok is True
        assert state_of(outcome["state"], "pitch")["text"] == "A short answer."

    def test_when_the_browser_refuses_the_command_the_answer_is_still_written(self) -> None:
        """``execCommand`` is deprecated, and one day a browser will drop it.

        The direct write is wrong for a real editor and right for a plain editable
        region, so falling back to it beats failing, but the result has to say which
        one happened.
        """
        refusing = {
            "execCommandFails": True,
            "elements": [{"tag": "div", "attrs": {"id": "pitch", "contenteditable": "true", "aria-label": "Pitch"}}],
        }
        field = discover(refusing)[0]

        outcome = write(refusing, field, "A short answer.")

        assert parse_apply_field_result(outcome["result"], field).ok is True
        assert outcome["result"]["action"] == "set_text"
        assert state_of(outcome["state"], "pitch")["text"] == "A short answer."

    def test_a_form_control_inside_an_editable_region_is_still_a_form_control(self) -> None:
        """Editability inherits, and that is a trap on the write side too.

        Portals wrap a whole question block in an editable region often enough, and
        the plain input sitting inside it reports ``isContentEditable`` as true. On
        that reading alone the answer would be inserted as prose into the region
        while the control the form actually reads stayed empty. Owning a ``value``
        is what separates a control from an editing surface.
        """
        wrapped = {
            "elements": [
                {
                    "tag": "div",
                    "attrs": {"id": "block", "contenteditable": "true"},
                    "children": [
                        {"tag": "input", "attrs": {"id": "email", "type": "email", "aria-label": "Email"}}
                    ],
                }
            ]
        }
        field = field_named(discover(wrapped), "Email")
        assert field.field_type == "email"

        outcome = write(wrapped, field, "ada@example.com")

        assert outcome["result"]["field_type"] != "richtext"
        assert state_of(outcome["state"], "email")["value"] == "ada@example.com"

    def test_an_editor_in_an_embedded_form_is_written_in_that_document(self) -> None:
        """The wrapper page has an editor of its own, and it must stay empty."""
        embedded = {
            "elements": [
                {"tag": "div", "attrs": {"id": "pitch", "contenteditable": "true", "aria-label": "Newsletter pitch"}},
                {
                    "tag": "iframe",
                    "attrs": {"id": "grnhse_iframe", "src": "https://job-boards.greenhouse.io/acme/jobs/1"},
                    "frame": {
                        "elements": [
                            {
                                "tag": "div",
                                "attrs": {"id": "pitch", "contenteditable": "true", "aria-label": "Pitch"},
                                "richTextEditor": True,
                            }
                        ]
                    },
                },
            ]
        }
        field = field_named(discover(embedded), "Pitch")

        outcome = write(embedded, field, "The real answer.")

        assert state_of(outcome["state"], "pitch", "frame:#grnhse_iframe")["text"] == "The real answer."
        assert state_of(outcome["state"], "pitch", "document")["text"] == ""


def portal_holding(pitch: str) -> dict[str, Any]:
    """The same form with the editor already containing ``pitch``.

    Every script runs against a freshly built page, so a write and a read cannot
    share one. Standing the answer up in the markup is how the read-back is tested
    on its own, without the write's word for it.
    """
    spec = deepcopy(PORTAL)
    spec["elements"][0]["children"][1]["children"][0]["text"] = pitch
    return spec


class TestVerification:
    """Read back through the page, never on the write's own report."""

    def verify(self, spec: dict[str, Any], field: Any, value: str) -> dict[str, Any]:
        return run_browser_script(
            build_verify_field_value_script(field.selector, value, dom_path_for(field)), spec
        )["result"]

    def test_the_editor_reads_back_as_the_answer_it_holds(self) -> None:
        answer = "Because the platform team owns the thing I want to build."
        spec = portal_holding(answer)
        field = field_named(discover(spec), "Why do you want to work here?")

        outcome = self.verify(spec, field, answer)

        assert outcome["verified"] is True
        assert outcome["value_matched"] is True
        assert outcome["field_type"] == "richtext"

    def test_an_editor_holding_a_different_answer_is_a_mismatch(self) -> None:
        """A box the write never reached must not read as filled.

        Before this branch existed the verifier reported ``field value cannot be
        read back`` for anything without a ``value``, so a rich-text answer could
        neither be confirmed nor caught as missing.
        """
        spec = portal_holding("Someone else's draft.")
        field = field_named(discover(spec), "Why do you want to work here?")

        outcome = self.verify(spec, field, "An answer nobody wrote.")

        assert outcome["value_matched"] is False
        assert outcome["actual"] == "Someone else's draft."

    def test_a_write_and_a_read_agree_about_the_same_box(self) -> None:
        """The two scripts resolve the selector independently, so they can disagree."""
        answer = "Because the platform team owns the thing I want to build."
        field = field_named(discover(PORTAL), "Why do you want to work here?")

        written = write(PORTAL, field, answer)
        read_back = self.verify(portal_holding(state_of(written["state"], "pitch")["text"]), field, answer)

        assert read_back["value_matched"] is True


def test_a_rich_text_field_never_takes_the_keystroke_path() -> None:
    """Keystrokes would be the stealthier write, and they are still wrong here.

    Every adapter clears the control before typing, and ``clear()`` on a
    contenteditable does nothing at all, so the answer would land on the end of
    whatever draft the box was already holding. The adapters read this set, and
    the write contract suite pins that all three of them honour it.
    """
    assert "richtext" in SCRIPTED_WRITE_FIELD_TYPES
