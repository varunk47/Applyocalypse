"""Label-resolution tests for audit finding F4/F6: unlabeled fields were dropped.

`field_detection.py` (injected JavaScript) and `html_replay.py` (offline replay of
saved portal HTML) implement the SAME label chain. If they drift, the replay
fixtures stop being evidence about the browser, so the parity test below pins the
two implementations to one shared ordering and one shared set of expectations.
"""
from __future__ import annotations

import json

import pytest
from js_bridge import require_node, run_browser_script, run_node_expression, state_for  # noqa: F401

from applyocalypse_automation.browser.field_detection import (
    DOM_FIELD_DISCOVERY_SCRIPT,
    LABEL_RESOLUTION_JS,
    LABEL_SOURCE_ORDER,
    SYNTHETIC_LABEL,
    fields_from_dom_snapshot,
    humanize_identifier,
    resolve_field_label,
)
from applyocalypse_automation.browser.html_replay import analyze_portal_html_fixture

# One table, exercised by the Python chain AND by the JavaScript chain.
LABEL_SOURCE_CASES: tuple[tuple[str, dict[str, str], str, str], ...] = (
    (
        "label_for wins over everything below it",
        {
            "label_for": "First name",
            "wrapping_label": "wrapper",
            "aria_labelledby": "referenced",
            "aria_label": "aria",
            "legend": "legend",
            "title": "title",
            "placeholder": "placeholder",
            "name_or_id": "First Name",
        },
        "First name",
        "label_for",
    ),
    (
        "wrapping label is next",
        {"wrapping_label": "Email address", "aria_label": "aria", "name_or_id": "Email"},
        "Email address",
        "wrapping_label",
    ),
    (
        "aria-labelledby beats aria-label",
        {"aria_labelledby": "Work authorization status", "aria_label": "aria", "title": "title"},
        "Work authorization status",
        "aria_labelledby",
    ),
    ("aria-label is used when nothing above it resolves", {"aria_label": "Phone"}, "Phone", "aria_label"),
    ("legend of the enclosing fieldset", {"legend": "Veteran status", "title": "t"}, "Veteran status", "legend"),
    ("title attribute", {"title": "Desired salary", "placeholder": "p"}, "Desired salary", "title"),
    ("placeholder attribute", {"placeholder": "you@example.com"}, "you@example.com", "placeholder"),
    ("humanized name or id", {"name_or_id": "Candidate First Name"}, "Candidate First Name", "name_or_id"),
    ("nothing at all becomes a flagged synthetic label", {}, SYNTHETIC_LABEL, "synthetic"),
    ("whitespace only is treated as absent", {"aria_label": "   ", "title": "Cover letter"}, "Cover letter", "title"),
)

HUMANIZE_CASES: tuple[tuple[str, str], ...] = (
    ("firstName", "First Name"),
    ("first_name", "First Name"),
    ("first-name", "First Name"),
    ("candidate.firstName", "Candidate First Name"),
    ("job_application[resume]", "Job Application Resume"),
    ("XMLHttpRequest", "XML Http Request"),
    ("email", "Email"),
    ("", ""),
)


@pytest.mark.parametrize(
    ("description", "sources", "expected_label", "expected_source"),
    [pytest.param(*case, id=case[0]) for case in LABEL_SOURCE_CASES],
)
def test_python_label_chain(description, sources, expected_label, expected_source) -> None:
    label, source, synthetic = resolve_field_label(sources)

    assert label == expected_label
    assert source == expected_source
    assert synthetic is (expected_source == "synthetic")


@pytest.mark.parametrize(("raw", "expected"), HUMANIZE_CASES)
def test_python_humanize_identifier(raw, expected) -> None:
    assert humanize_identifier(raw) == expected


def test_javascript_label_chain_matches_the_python_chain_exactly() -> None:
    """The injected JS and the replay Python must agree, case for case."""
    require_node()
    payload = json.dumps([case[1] for case in LABEL_SOURCE_CASES])
    identifiers = json.dumps([case[0] for case in HUMANIZE_CASES])
    source = f"""
const document = {{ querySelector: () => null, getElementById: () => null }};
const CSS = {{ escape: (value) => String(value) }};
{LABEL_RESOLUTION_JS}
process.stdout.write(JSON.stringify({{
  order: LABEL_SOURCE_ORDER,
  synthetic_label: SYNTHETIC_LABEL,
  resolved: {payload}.map(resolveLabelFromSources),
  humanized: {identifiers}.map(humanizeIdentifier)
}}));
"""
    observed = run_node_expression(source)

    assert observed["order"] == list(LABEL_SOURCE_ORDER)
    assert observed["synthetic_label"] == SYNTHETIC_LABEL
    assert observed["humanized"] == [expected for _, expected in HUMANIZE_CASES]
    assert observed["resolved"] == [
        {"label": expected_label, "label_source": expected_source, "label_synthetic": expected_source == "synthetic"}
        for _, _, expected_label, expected_source in LABEL_SOURCE_CASES
    ]


REPLAY_HTML = """
<html><title>Apply</title><body>
  <form>
    <label for="first">First name</label><input id="first" name="firstName" required>
    <label>Email address<input id="email" name="email" type="email"></label>
    <span id="auth-label">Are you legally authorized to work?</span>
    <select id="auth" name="auth" aria-labelledby="auth-label" required></select>
    <input id="aria" name="aria" aria-label="LinkedIn profile">
    <fieldset>
      <legend>Veteran status</legend>
      <input id="veteran" name="veteran" type="radio" value="no">
    </fieldset>
    <input id="salary" name="salary" title="Desired salary">
    <input id="cover" name="cover" placeholder="Paste your cover letter">
    <input id="candidateFirstName" name="candidate.firstName">
    <input id="mystery" type="text">
    <input type="text">
  </form>
</body></html>
"""

EXPECTED_REPLAY_LABELS: tuple[tuple[str, str, str], ...] = (
    ("first", "First name", "label_for"),
    ("email", "Email address", "wrapping_label"),
    ("auth", "Are you legally authorized to work?", "aria_labelledby"),
    ("aria", "LinkedIn profile", "aria_label"),
    ("veteran", "Veteran status", "legend"),
    ("salary", "Desired salary", "title"),
    ("cover", "Paste your cover letter", "placeholder"),
    ("candidateFirstName", "Candidate First Name", "name_or_id"),
    ("mystery", "Mystery", "name_or_id"),
    ("", SYNTHETIC_LABEL, "synthetic"),
)


def test_html_replay_resolves_every_label_source() -> None:
    analysis = analyze_portal_html_fixture("https://boards.greenhouse.io/acme/jobs/1", REPLAY_HTML)
    observed = [
        (field.metadata.get("id") or "", field.label, field.metadata.get("label_source"))
        for field in analysis.fields
    ]

    assert observed == [tuple(entry) for entry in EXPECTED_REPLAY_LABELS]


def test_html_replay_flags_rather_than_drops_an_unlabeled_field() -> None:
    analysis = analyze_portal_html_fixture("https://boards.greenhouse.io/acme/jobs/1", REPLAY_HTML)
    unlabeled = [field for field in analysis.fields if field.metadata.get("label_synthetic")]

    assert len(unlabeled) == 1
    assert unlabeled[0].label == SYNTHETIC_LABEL
    assert unlabeled[0].metadata["requires_human_label_review"] is True
    assert unlabeled[0].confidence < 0.45


def _replay_html_to_dom_spec() -> dict:
    """The same form as REPLAY_HTML, expressed for the DOM stub."""
    return {
        "elements": [
            {
                "tag": "form",
                "children": [
                    {"tag": "label", "attrs": {"for": "first"}, "text": "First name"},
                    {"tag": "input", "attrs": {"id": "first", "name": "firstName"}, "required": True},
                    {
                        "tag": "label",
                        "text": "Email address",
                        "children": [{"tag": "input", "attrs": {"id": "email", "name": "email", "type": "email"}}],
                    },
                    {"tag": "span", "attrs": {"id": "auth-label"}, "text": "Are you legally authorized to work?"},
                    {"tag": "select", "attrs": {"id": "auth", "name": "auth", "aria-labelledby": "auth-label"}},
                    {"tag": "input", "attrs": {"id": "aria", "name": "aria", "aria-label": "LinkedIn profile"}},
                    {
                        "tag": "fieldset",
                        "children": [
                            {"tag": "legend", "text": "Veteran status"},
                            {
                                "tag": "input",
                                "attrs": {"id": "veteran", "name": "veteran", "type": "radio", "value": "no"},
                            },
                        ],
                    },
                    {"tag": "input", "attrs": {"id": "salary", "name": "salary", "title": "Desired salary"}},
                    {
                        "tag": "input",
                        "attrs": {"id": "cover", "name": "cover", "placeholder": "Paste your cover letter"},
                    },
                    {"tag": "input", "attrs": {"id": "candidateFirstName", "name": "candidate.firstName"}},
                    {"tag": "input", "attrs": {"id": "mystery", "type": "text"}},
                    {"tag": "input", "attrs": {"type": "text"}},
                ],
            }
        ]
    }


def test_browser_discovery_resolves_the_same_labels_and_keeps_unlabeled_fields() -> None:
    outcome = run_browser_script(DOM_FIELD_DISCOVERY_SCRIPT, _replay_html_to_dom_spec())
    observed = [
        (raw["metadata"].get("id") or "", raw["label"], raw["label_source"]) for raw in outcome["result"]
    ]

    assert observed == [tuple(entry) for entry in EXPECTED_REPLAY_LABELS]


def test_fields_from_dom_snapshot_marks_synthetic_labels_for_human_review() -> None:
    fields = fields_from_dom_snapshot(
        [
            {"label": "Email", "field_type": "email", "selector": "#email", "label_source": "label_for"},
            {"label": "", "field_type": "text", "selector": "#mystery", "label_synthetic": True},
        ]
    )

    assert fields[0].metadata["label_source"] == "label_for"
    assert "label_synthetic" not in fields[0].metadata
    assert fields[1].label == SYNTHETIC_LABEL
    assert fields[1].metadata["label_synthetic"] is True
    assert fields[1].metadata["requires_human_label_review"] is True
    assert fields[1].confidence < fields[0].confidence
