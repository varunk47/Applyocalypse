import pytest

from applyocalypse_automation.browser.jev_page import (
    REDACTED,
    JevPage,
    jev_state,
    page_from_frames,
    redact_text,
)

PERSONAL = ["Jordan Rivera", "jordan.rivera@example.com", "Jordan", "+1 555 010 2030", "NY"]


def raw_element(i, tag="button", **extra):
    return {"i": i, "tag": tag, "field": False, "label": "", "text": "", "placeholder": "",
            "filled": None, "required": False, "disabled": False, "expanded": None,
            "options": [], "href": "", "hidden": False, **extra}


def main_frame(elements, **extra):
    return {"url": "https://jobs.example.com/apply?email=jordan.rivera%40example.com#step2",
            "title": "Apply", "text": "", "dialogs": [], "elements": elements, **extra}


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Signed in as Jordan Rivera", f"Signed in as {REDACTED}"),
        ("JORDAN.RIVERA@EXAMPLE.COM is verified", f"{REDACTED} is verified"),
        ("Call +1 555 010 2030", f"Call {REDACTED}"),
        # the longer value wins, so the full name is not split into "[redacted] Rivera"
        ("Hi Jordan Rivera, welcome Jordan", f"Hi {REDACTED}, welcome {REDACTED}"),
        # values shorter than three characters are too common to cut out
        ("NY office in Albany, NY", "NY office in Albany, NY"),
        ("No personal data here", "No personal data here"),
    ],
)
def test_redact_text(text, expected):
    assert redact_text(text, PERSONAL) == expected


def test_state_sends_filled_or_empty_never_a_value():
    page = page_from_frames([("https://jobs.example.com/apply", main_frame([
        raw_element(0, "input:email", field=True, label="Email", filled=True, required=True),
        raw_element(1, "input:password", field=True, label="Password", filled=False),
        raw_element(2, "select", field=True, label="Country", filled=False,
                    options=[str(n) for n in range(10)]),
        raw_element(3, "button", text="Next"),
    ]))])

    state = jev_state(page, PERSONAL)

    assert '[0] input:email label="Email" filled required' in state
    assert '[1] input:password label="Password" empty' in state
    assert "options=[0, 1, 2, 3, 4, 5, 6, 7, ...]" in state
    assert '[3] button text="Next"' in state
    assert "elements (4):" in state


def test_state_strips_query_and_redacts_page_text_and_dialogs():
    page = page_from_frames([("https://jobs.example.com/apply", main_frame(
        [raw_element(0, "a", text="Profile of Jordan Rivera", href="/me")],
        title="Jordan Rivera | Careers",
        text="Welcome back jordan.rivera@example.com",
        dialogs=["Is +1 555 010 2030 still your number?"],
    ))])

    state = jev_state(page, PERSONAL)

    assert "url: https://jobs.example.com/apply\n" in state
    for value in PERSONAL[:4]:
        assert value.lower() not in state.lower()
    assert f"title: {REDACTED} | Careers" in state
    assert f"dialogs: Is {REDACTED} still your number?" in state
    assert f'text="Profile of {REDACTED}" href=/me' in state


def test_frames_are_merged_and_child_elements_name_their_frame():
    page = page_from_frames([
        ("https://jobs.example.com/apply", main_frame([raw_element(0, text="Apply")])),
        ("https://boards.example.net/embed?token=secret", {"elements": [raw_element(1, text="Upload")]}),
    ])

    assert [e.index for e in page.elements] == [0, 1]
    assert page.elements[0].frame_url == ""
    assert page.element(1).frame_url == "https://boards.example.net/embed?token=secret"
    state = jev_state(page, [])
    assert "frame=https://boards.example.net/embed" in state
    assert "secret" not in state


def test_element_name_falls_back_through_label_text_placeholder_href_tag():
    page = page_from_frames([("u", main_frame([
        raw_element(0, label="L", text="T"),
        raw_element(1, text="T", placeholder="P"),
        raw_element(2, placeholder="P"),
        raw_element(3, "a", href="/x"),
        raw_element(4, "div[button]"),
    ]))])

    assert [e.name for e in page.elements] == ["L", "T", "P", "/x", "div[button]"]


def test_fingerprint_changes_when_a_field_is_filled():
    before = JevPage("u", "t", "x", (), page_from_frames([("u", main_frame([
        raw_element(0, "input:text", field=True, filled=False)]))]).elements)
    after = JevPage("u", "t", "x", (), page_from_frames([("u", main_frame([
        raw_element(0, "input:text", field=True, filled=True)]))]).elements)

    assert before.fingerprint() != after.fingerprint()
    assert before.fingerprint() == JevPage("u", "t", "x", (), before.elements).fingerprint()
