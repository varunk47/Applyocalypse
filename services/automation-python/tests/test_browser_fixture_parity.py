"""Does the offline HTML twin actually agree with a real browser?

Every other portal test in this suite runs against ``html_replay``, a pure-Python
reimplementation of the discovery script we inject into the page. That twin is
fast, deterministic and completely unverified: nothing until now compared what it
reports against what Chrome reports for the same markup. A twin that has drifted
turns the whole offline suite into a test of itself, and the drift would only ever
surface on a real portal, in front of a user, on an application that cannot be
resent.

So this module serves one fixture page over real HTTP, drives a real Chrome
through the real adapter, and asserts three things:

* the fields Chrome finds are the fields the twin predicts,
* the selectors the twin invents resolve to exactly one element in a real DOM,
* a written answer is genuinely in the document afterwards.

It is deselected from the default gate (``-m 'not browser'`` in pyproject) and
runs from ``pnpm test:python:browser``, because it needs a browser, takes seconds
rather than milliseconds, and opens a window on the developer's desktop.
"""

from __future__ import annotations

import asyncio
import contextlib
import tempfile
import threading
from collections.abc import Iterator
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from applyocalypse_automation.browser.adapter import BrowserField
from applyocalypse_automation.browser.chrome_discovery import discover_chrome_executable
from applyocalypse_automation.browser.html_replay import analyze_portal_html_fixture
from applyocalypse_automation.browser.nodriver_adapter import NodriverBrowserAdapter

pytestmark = pytest.mark.browser


# A Greenhouse-shaped application form. Every control here exists to exercise one
# path the two implementations have to agree on: each way of attaching a label,
# a picker with no <select> behind it, a file input hidden behind a dropzone, and
# the controls that must never be offered to the user at all.
FIXTURE_HTML = """<!doctype html>
<html>
  <head><title>Apply: Staff Platform Engineer at Northstar</title></head>
  <body>
    <main>
      <h1>Staff Platform Engineer</h1>
      <form id="application-form">
        <label for="first_name">First Name</label>
        <input id="first_name" name="first_name" type="text" required>

        <label>Last Name
          <input name="last_name" type="text" required>
        </label>

        <input id="email" name="email" type="email" aria-label="Email" required>

        <input name="phone" type="tel" placeholder="Phone number">

        <input name="linkedinProfile" type="url">

        <span id="salary-label">Desired annual salary</span>
        <input name="salary" type="text" aria-labelledby="salary-label">

        <label for="pronouns">Pronouns</label>
        <select id="pronouns" name="pronouns">
          <option value="">Select...</option>
          <option value="she">She/her</option>
          <option value="he">He/him</option>
          <option value="they">They/them</option>
        </select>

        <label for="why">Why do you want to work here?</label>
        <textarea id="why" name="why" required></textarea>

        <span id="pitch-label">Tell us about a system you have owned</span>
        <div class="ql-container" style="border:1px solid #ccc">
          <div id="pitch" class="ql-editor" contenteditable="true" aria-labelledby="pitch-label"
               aria-required="true" style="min-height:120px"></div>
        </div>

        <label for="relocate">I am willing to relocate</label>
        <input id="relocate" name="relocate" type="checkbox" value="yes">

        <div class="dropzone">
          Drag your resume here
          <input id="resume" name="resume" type="file" accept=".pdf,.docx" required
                 style="width:0;height:0;opacity:0">
        </div>

        <span id="visa-label">Do you now or will you in the future require sponsorship?</span>
        <div id="visa" role="combobox" aria-labelledby="visa-label" aria-required="true"
             aria-expanded="false" aria-controls="visa-options"></div>
        <ul id="visa-options" role="listbox" aria-label="Sponsorship options">
          <li role="option" data-value="no">No</li>
          <li role="option" data-value="yes">Yes</li>
        </ul>

        <input type="hidden" name="csrf_token" value="abc123">
        <input type="search" name="site_search" aria-label="Search this site">
        <textarea name="g-recaptcha-response" style="display:none"></textarea>

        <button type="submit">Submit application</button>
      </form>
    </main>
  </body>
</html>
"""

FIXTURE_PATH = "/careers/northstar/apply"

# Written into the form once the browser is up. The select is addressed by the
# option's visible label, the way a reviewed answer arrives in production.
ANSWERS: dict[str, str] = {
    "#first_name": "Jane",
    "#pitch": "I ran the deploy pipeline for a fleet of about four hundred services.",
    "#why": "Because the platform team owns the thing I want to build.",
    "#pronouns": "They/them",
}
EXPECTED_DOM_VALUES: dict[str, str] = {
    "#first_name": "Jane",
    "#pitch": "I ran the deploy pipeline for a fleet of about four hundred services.",
    "#why": "Because the platform team owns the thing I want to build.",
    "#pronouns": "they",
}


class _FixtureHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler's spelling
        body = FIXTURE_HTML if self.path == FIXTURE_PATH else "<html><body>Northstar</body></html>"
        encoded = body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, *args: object) -> None:
        """Silence the default stderr access log."""


class _QuietServer(ThreadingHTTPServer):
    def handle_error(self, *args: object) -> None:
        """Chrome drops keep-alive sockets on close; that is not a test failure.

        The default handler prints a ConnectionResetError traceback from a worker
        thread, which trains a reader to skip tracebacks in this file's output.
        """


@contextlib.contextmanager
def _serve() -> Iterator[str]:
    """Serve the fixture over real HTTP.

    A file:// page would be a different origin class with different iframe and
    isolated-world behaviour, and the adapter's own warm-up navigates to the
    origin root before the target, so the page has to come from a real server.
    """
    server = _QuietServer(("127.0.0.1", 0), _FixtureHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}{FIXTURE_PATH}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@dataclass(frozen=True, slots=True)
class _BrowserRun:
    """Everything the browser told us, collected in one launch."""

    url: str
    real_fields: tuple[BrowserField, ...] = ()
    write_results: dict[str, tuple[bool, str]] = dataclass_field(default_factory=dict)
    dom_values: dict[str, str] = dataclass_field(default_factory=dict)
    selector_matches: dict[str, int] = dataclass_field(default_factory=dict)


async def _drive(url: str, user_data_dir: Path) -> _BrowserRun:
    adapter = NodriverBrowserAdapter()
    launched = await adapter.launch(run_id="fixture-parity", user_data_dir=user_data_dir)
    if not launched.ok:
        pytest.skip(f"no browser available: {launched.message}")
    try:
        opened = await adapter.open_url(url)
        assert opened.ok, opened.message

        real_fields = tuple(await adapter.detect_fields())
        by_selector = {field.selector: field for field in real_fields if field.selector}

        write_results: dict[str, tuple[bool, str]] = {}
        for selector, value in ANSWERS.items():
            target = by_selector.get(selector)
            assert target is not None, f"{selector} was never discovered, so nothing could be written to it"
            result = await adapter.apply_field_value(target, value)
            write_results[selector] = (result.ok, result.message)

        # Read back through the page rather than through the adapter. Verifying a
        # write with the same code path that performed it proves only that the
        # path is self-consistent, which is exactly the failure mode this module
        # exists to rule out.
        dom_values = {
            selector: str(
                await adapter._page.evaluate(  # noqa: SLF001 - deliberate: see above
                    # An editing surface has no ``value``; what a person sees in it
                    # is its rendered text. Trimmed because a browser is entitled to
                    # leave a trailing break behind an insertion, which is a
                    # rendering detail and not a difference in the answer.
                    f"(() => {{ const el = document.querySelector({selector!r}); "
                    "return el.isContentEditable ? el.innerText.trim() : el.value; })()"
                )
            )
            for selector in ANSWERS
        }
        selector_matches = {
            selector: int(
                await adapter._page.evaluate(  # noqa: SLF001 - deliberate: see above
                    f"document.querySelectorAll({selector!r}).length"
                )
            )
            for selector in sorted(
                {
                    field.selector
                    for field in analyze_portal_html_fixture(url, FIXTURE_HTML).fields
                    if field.selector
                }
            )
        }
        return _BrowserRun(
            url=url,
            real_fields=real_fields,
            write_results=write_results,
            dom_values=dom_values,
            selector_matches=selector_matches,
        )
    finally:
        with contextlib.suppress(Exception):
            await adapter.close()


@pytest.fixture(scope="module")
def browser_run() -> Iterator[_BrowserRun]:
    """One page, one browser, one launch, shared by every test below."""
    if discover_chrome_executable() is None:
        pytest.skip("no Chrome installation was found")
    with _serve() as url, tempfile.TemporaryDirectory(prefix="applyo-parity-") as profile_dir:
        loop = asyncio.new_event_loop()
        # nodriver reaches for the current event loop rather than the running one,
        # so this has to be installed the way asyncio.run installs it.
        asyncio.set_event_loop(loop)
        try:
            yield loop.run_until_complete(_drive(url, Path(profile_dir)))
        finally:
            # Chrome's subprocess transport tears down asynchronously. Closing the
            # loop out from under it prints an ignored "Event loop is closed" at
            # interpreter exit, so give it a turn to finish first.
            loop.run_until_complete(asyncio.sleep(0.25))
            loop.close()
            asyncio.set_event_loop(None)


def _shape(fields: tuple[BrowserField, ...]) -> set[tuple[str, str, bool]]:
    return {(field.label, field.field_type, field.required) for field in fields}


def test_the_twin_predicts_the_fields_a_real_browser_finds(browser_run: _BrowserRun) -> None:
    """The offline suite is only worth anything if this holds.

    Compared as sets and reported as two differences, because the useful question
    on a failure is never "which position differs" but "which control did one of
    them invent, and which did it lose".
    """
    predicted = _shape(analyze_portal_html_fixture(browser_run.url, FIXTURE_HTML).fields)
    real = _shape(browser_run.real_fields)

    assert not predicted - real, f"the twin invents fields the browser never offers: {sorted(predicted - real)}"
    assert not real - predicted, f"the twin misses fields the browser finds: {sorted(real - predicted)}"


@pytest.mark.parametrize(
    ("label", "field_type"),
    [
        ("First Name", "text"),
        ("Last Name", "text"),
        ("Email", "email"),
        ("Phone number", "tel"),
        ("Linkedin Profile", "url"),
        ("Desired annual salary", "text"),
        ("Pronouns", "select"),
        ("Why do you want to work here?", "textarea"),
        ("I am willing to relocate", "checkbox"),
        ("Resume", "file"),
        ("Do you now or will you in the future require sponsorship?", "aria_combobox"),
    ],
)
def test_every_way_a_portal_attaches_a_label_survives_a_real_browser(
    browser_run: _BrowserRun, label: str, field_type: str
) -> None:
    """Each row is one labelling strategy real portals use, and one field type."""
    assert (label, field_type) in {(field.label, field.field_type) for field in browser_run.real_fields}


@pytest.mark.parametrize("forbidden", ["csrf_token", "site_search", "g-recaptcha-response"])
def test_the_controls_a_human_must_never_be_asked_about_are_not_offered(
    browser_run: _BrowserRun, forbidden: str
) -> None:
    """A hidden token, a site search box and a captcha are not application questions."""
    names = {field.metadata.get("name") for field in browser_run.real_fields}

    assert forbidden not in names


def test_the_file_input_behind_the_dropzone_is_still_found(browser_run: _BrowserRun) -> None:
    """It is styled to zero size on purpose, and dropping it loses the resume silently."""
    resume = [field for field in browser_run.real_fields if field.field_type == "file"]

    assert len(resume) == 1
    assert resume[0].metadata.get("visually_hidden") is True


def test_the_selectors_the_twin_invents_resolve_in_a_real_document(browser_run: _BrowserRun) -> None:
    """A selector that matches nothing, or matches two things, writes an answer nowhere."""
    assert browser_run.selector_matches
    assert all(count == 1 for count in browser_run.selector_matches.values()), browser_run.selector_matches


@pytest.mark.parametrize("selector", sorted(ANSWERS))
def test_a_written_answer_is_really_in_the_document(browser_run: _BrowserRun, selector: str) -> None:
    """Read back off the page itself, not through the adapter that did the writing."""
    ok, message = browser_run.write_results[selector]

    assert ok, message
    assert browser_run.dom_values[selector] == EXPECTED_DOM_VALUES[selector]


def test_the_twin_cannot_see_css_and_says_so_here(browser_run: _BrowserRun) -> None:
    """The one divergence that cannot be fixed, pinned so nobody rediscovers it live.

    ``html_replay`` parses markup and has no layout engine, so a control hidden by
    a stylesheet, by a class, or by a parent's ``display:none`` is invisible to it
    as a *hidden* control while Chrome drops it. Inline ``style`` on the element
    itself is the only case the twin can catch, and the fixture above relies on
    that for the captcha textarea. Anything subtler will show up here as a field
    the twin predicts and the browser does not.
    """
    hidden_by_a_parent = FIXTURE_HTML.replace(
        '<div class="dropzone">',
        '<div class="dropzone"><div style="display:none"><input name="ghost" type="text"></div>',
    ).replace("</div>\n\n        <span id=\"visa-label\"", "</div></div>\n\n        <span id=\"visa-label\"")
    predicted = analyze_portal_html_fixture(browser_run.url, hidden_by_a_parent).fields

    assert "ghost" in {field.metadata.get("name") for field in predicted}
    assert "ghost" not in {field.metadata.get("name") for field in browser_run.real_fields}
