"""Can we still tell that a person is being asked to prove they are a person?

Getting this wrong is expensive in both directions. Miss a challenge and the
field scan comes back empty, the run reads the page as "nothing to fill here",
and nobody is asked to step in -- on a page that exists to stop automation.
Cry wolf instead and every ordinary application form pauses, which is the bug
that once matched the word "recaptcha" in page text and hung runs against forms
whose only captcha was a passive footer badge.

The live detector is JavaScript inside a Python string, injected into the page,
and its Python twin in ``html_replay`` re-implements it for the offline fixture
suite. The two used to keep separate copies of the same phrase list. These tests
hold them to one copy and pin what may go in it.
"""

from __future__ import annotations

import json

import pytest

from applyocalypse_automation.browser.field_detection import (
    CAPTCHA_CHALLENGE_PHRASES,
    CAPTCHA_INTERSTITIAL_PHRASES,
    CAPTCHA_VENDOR_SELECTORS,
    DOM_BLOCKER_DISCOVERY_SCRIPT,
)
from applyocalypse_automation.browser.html_replay import analyze_portal_html_fixture

# Verbatim from a Greenhouse form. This is the sentence the phantom-block bug
# tripped on, so it earns a place in the test file rather than a paraphrase.
PASSIVE_NOTICE = (
    "This site is protected by reCAPTCHA and the Google Privacy Policy and "
    "Terms of Service apply. hCaptcha and Cloudflare Turnstile may also apply."
)


def _page(body: str) -> str:
    return f"<!doctype html><html><head><title>Apply</title></head><body>{body}</body></html>"


def _blocker_types(html: str) -> set[str]:
    analysis = analyze_portal_html_fixture("https://boards.greenhouse.io/acme/jobs/1", html)
    return {blocker.blocker_type for blocker in analysis.blockers}


class TestPhraseListIsShared:
    """One list, two consumers. A second copy is how they drifted before."""

    @pytest.mark.parametrize("phrase", CAPTCHA_CHALLENGE_PHRASES)
    def test_every_phrase_reaches_the_injected_script(self, phrase: str) -> None:
        assert phrase in DOM_BLOCKER_DISCOVERY_SCRIPT

    @pytest.mark.parametrize("phrase", CAPTCHA_CHALLENGE_PHRASES + CAPTCHA_INTERSTITIAL_PHRASES)
    def test_every_phrase_blocks_the_offline_twin(self, phrase: str) -> None:
        assert "CAPTCHA" in _blocker_types(_page(f"<h1>{phrase}</h1>"))

    def test_the_script_matches_body_text_against_exactly_this_list(self) -> None:
        """Pins which array the backstop reads, so the next test can be precise."""
        assert json.dumps(list(CAPTCHA_CHALLENGE_PHRASES)) in DOM_BLOCKER_DISCOVERY_SCRIPT

    @pytest.mark.parametrize("phrase", CAPTCHA_INTERSTITIAL_PHRASES)
    def test_interstitial_phrases_stay_out_of_the_body_text_list(self, phrase: str) -> None:
        """These are matched structurally in a live page, not against body text.

        "just a moment" is an ordinary thing for an application form to say while
        it saves something, so the live script reads it from the document title
        ("just a moment..." exactly) and from Cloudflare's own challenge elements.
        Folding these into the body-text list would pause real runs mid-form.
        """
        assert phrase not in CAPTCHA_CHALLENGE_PHRASES


class TestPhrasesCannotNameAVendor:
    """The regression guard for the phantom block.

    Every form that embeds an invisible reCAPTCHA v3 mentions it in a footer. A
    phrase list that names vendors matches that footer, which is how a page with
    nothing to solve became a page that stopped the run.
    """

    @pytest.mark.parametrize(
        "vendor", ["recaptcha", "hcaptcha", "captcha", "turnstile", "cloudflare", "arkose", "datadome"]
    )
    def test_no_phrase_names_a_vendor(self, vendor: str) -> None:
        naming = [phrase for phrase in CAPTCHA_CHALLENGE_PHRASES if vendor in phrase and "the captcha" not in phrase]
        assert naming == []

    def test_the_passive_notice_does_not_block(self) -> None:
        assert "CAPTCHA" not in _blocker_types(_page(f"<p>{PASSIVE_NOTICE}</p>"))

    def test_the_passive_notice_survives_a_real_form(self) -> None:
        html = _page(
            "<form><label for='e'>Email</label><input id='e' name='email' type='email'>"
            f"<p>{PASSIVE_NOTICE}</p></form>"
        )
        assert "CAPTCHA" not in _blocker_types(html)


class TestVendorTable:
    def test_vendor_names_are_unique(self) -> None:
        names = [name for name, _ in CAPTCHA_VENDOR_SELECTORS]
        assert sorted(names) == sorted(set(names))

    @pytest.mark.parametrize(("vendor", "selector"), CAPTCHA_VENDOR_SELECTORS)
    def test_every_entry_reaches_the_injected_script(self, vendor: str, selector: str) -> None:
        assert f'"{vendor}"' in DOM_BLOCKER_DISCOVERY_SCRIPT
        # json.dumps escapes the inner quotes; compare on a distinctive fragment
        # that survives that rather than on the raw selector.
        assert selector.split(",")[0].split("[")[0].strip(' #.') in DOM_BLOCKER_DISCOVERY_SCRIPT

    @pytest.mark.parametrize("vendor", ["arkose", "perimeterx"])
    def test_the_vendors_added_for_linkedin_and_press_and_hold_are_present(self, vendor: str) -> None:
        assert vendor in {name for name, _ in CAPTCHA_VENDOR_SELECTORS}

    def test_no_placeholder_survives_interpolation(self) -> None:
        assert "__CAPTCHA" not in DOM_BLOCKER_DISCOVERY_SCRIPT


class TestUnknownVendorBackstop:
    """The point of the phrase list: a challenge we cannot name still stops us."""

    def test_a_challenge_from_no_known_vendor_still_blocks(self) -> None:
        html = _page("<div class='shield-challenge'><p>Press and hold to confirm you are human</p></div>")
        assert "CAPTCHA" in _blocker_types(html)

    def test_a_challenge_page_offers_no_fields_to_fill(self) -> None:
        """Why the backstop matters: there is nothing here to mistake for a form."""
        analysis = analyze_portal_html_fixture(
            "https://careers.example.com/apply",
            _page("<div><p>Select all images with a bus</p></div>"),
        )
        assert analysis.fields == ()
        assert "CAPTCHA" in {blocker.blocker_type for blocker in analysis.blockers}
