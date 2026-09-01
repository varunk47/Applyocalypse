"""Does a real Chrome agree that the answer landed in the embedded form?

``test_nested_root_fields.py`` drives the same scripts against the Node DOM stub,
which is fast and deterministic and written by the same hand as the code it
checks. The one thing it cannot establish is that a browser behaves the way that
stub says it does, and every claim in this change is a claim about the browser:
that ``getRootNode()`` hands back a shadow root, that a same-origin iframe's
``contentDocument`` is reachable while a cross-origin one is not, that a label
inside a shadow root is invisible to the top document's ``querySelector``.

So this module serves a real employer page that embeds a real same-origin ATS
form and renders a real web component, drives a real Chrome through the real
adapter, and reads every answer back off the page rather than through the adapter
that wrote it.

The same-origin case cannot be folded into ``test_browser_fixture_parity.py``:
that suite asserts the pure-Python twin predicts what Chrome finds, and the twin
parses one HTML document and cannot see into an embed. Adding one there would
break parity by design rather than test it.

Deselected from the default gate (``-m 'not browser'`` in pyproject) and run from
``pnpm test:python:browser``, for the same reasons as its sibling.
"""

from __future__ import annotations

import asyncio
import contextlib
import tempfile
import threading
from collections.abc import Iterator
from dataclasses import dataclass, replace
from dataclasses import field as dataclass_field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

from applyocalypse_automation.browser.adapter import BrowserField
from applyocalypse_automation.browser.chrome_discovery import discover_chrome_executable
from applyocalypse_automation.browser.field_detection import dom_path_for
from applyocalypse_automation.browser.nodriver_adapter import NodriverBrowserAdapter

pytestmark = pytest.mark.browser


EMPLOYER_PATH = "/careers/northstar/apply"
EMBED_PATH = "/embed/northstar/apply"

# The employer's own page. It keeps a newsletter box under the *same id* the ATS
# uses for its email question, which is the collision that makes an unaddressed
# write land somewhere plausible and wrong instead of failing loudly.
EMPLOYER_HTML = f"""<!doctype html>
<html>
  <head>
    <title>Staff Platform Engineer at Northstar</title>
    <style>location-picker {{ display: block; }}</style>
  </head>
  <body>
    <main>
      <h1>Staff Platform Engineer</h1>

      <form id="newsletter">
        <label for="email">Newsletter email</label>
        <input id="email" name="email" type="email">
      </form>

      <iframe id="ats-embed" title="Application form" src="{EMBED_PATH}"
              width="760" height="520"></iframe>

      <location-picker id="location-picker"></location-picker>
      <script>
        customElements.define('location-picker', class extends HTMLElement {{
          connectedCallback() {{
            // Open on purpose. A closed root is unreachable by design and staying
            // out of it is the correct behaviour rather than a gap.
            const root = this.attachShadow({{ mode: 'open' }});
            root.innerHTML =
              '<label for="location">Preferred location</label>' +
              '<input id="location" name="location" type="text">';
          }}
        }});
      </script>
    </main>
  </body>
</html>
"""

# What the ATS serves into the iframe. Same origin as the page above, so Chrome
# keeps it in the parent's renderer and it never becomes a CDP target of its own:
# the adapter's frame enumeration cannot see it, and the DOM walk is the only way
# in. That is precisely the shape this change exists for.
EMBED_HTML = """<!doctype html>
<html>
  <head><title>Apply</title></head>
  <body>
    <form id="application-form">
      <label for="email">Email</label>
      <input id="email" name="email" type="email" required>

      <label for="first_name">First Name</label>
      <input id="first_name" name="first_name" type="text" required>

      <button type="submit">Submit application</button>
    </form>
  </body>
</html>
"""

ANSWERS: dict[str, str] = {
    "Email": "ada@example.com",
    "Preferred location": "Remote (EU)",
}

# Read back off the page itself. Each expression starts from the top document and
# crosses exactly one boundary, so a passing assertion is evidence about where the
# value physically is rather than about what the writer believed.
READBACK_JS: dict[str, str] = {
    "embedded email": "document.querySelector('#ats-embed').contentDocument.querySelector('#email').value",
    "newsletter email": "document.querySelector('#email').value",
    "shadow location": "document.querySelector('#location-picker').shadowRoot.querySelector('#location').value",
}


class _FixtureHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler's spelling
        if self.path == EMPLOYER_PATH:
            body = EMPLOYER_HTML
        elif self.path == EMBED_PATH:
            body = EMBED_HTML
        else:
            body = "<html><body>Northstar</body></html>"
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
        """Chrome drops keep-alive sockets on close; that is not a test failure."""


@contextlib.contextmanager
def _serve() -> Iterator[str]:
    """Serve both documents from one origin, so the embed really is same-origin."""
    server = _QuietServer(("127.0.0.1", 0), _FixtureHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}{EMPLOYER_PATH}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@dataclass(frozen=True, slots=True)
class _BrowserRun:
    """Everything the browser told us, collected in one launch."""

    fields: tuple[BrowserField, ...] = ()
    write_results: dict[str, tuple[bool, str]] = dataclass_field(default_factory=dict)
    stale_write: tuple[bool, str] = (True, "")
    readbacks: dict[str, str] = dataclass_field(default_factory=dict)


async def _await_embedded_form(adapter: NodriverBrowserAdapter) -> None:
    """Wait for the iframe's own document, which is a second navigation.

    Discovery that runs before the embed commits sees an empty frame and reports
    nothing, which would make this suite pass or fail on timing rather than on
    behaviour. Polling for the control itself is the condition that actually
    matters; a fixed sleep is either too short on a loaded machine or wasted.
    """
    probe = (
        "(() => { const frame = document.querySelector('#ats-embed');"
        " return frame && frame.contentDocument"
        " && frame.contentDocument.querySelector('#first_name') ? 1 : 0; })()"
    )
    for _ in range(100):
        if int(await adapter._page.evaluate(probe)) == 1:  # noqa: SLF001 - no public read-through
            return
        await asyncio.sleep(0.1)
    raise AssertionError("the embedded application form never loaded")


async def _drive(url: str, user_data_dir: Path) -> _BrowserRun:
    adapter = NodriverBrowserAdapter()
    launched = await adapter.launch(run_id="nested-roots", user_data_dir=user_data_dir)
    if not launched.ok:
        pytest.skip(f"no browser available: {launched.message}")
    try:
        opened = await adapter.open_url(url)
        assert opened.ok, opened.message
        await _await_embedded_form(adapter)

        fields = tuple(await adapter.detect_fields())
        by_label = {field.label: field for field in fields}

        write_results: dict[str, tuple[bool, str]] = {}
        for label, value in ANSWERS.items():
            target = by_label.get(label)
            assert target is not None, f"{label!r} was never discovered, so nothing could be written to it"
            result = await adapter.apply_field_value(target, value)
            write_results[label] = (result.ok, result.message)

        # The same question, re-addressed to a frame that is not there. Run before
        # the read-backs so the newsletter box can be checked for damage: a
        # fallback to the top document would fill it with this value.
        stale_metadata: dict[str, Any] = {
            **by_label["Email"].metadata,
            "dom_path": [{"kind": "frame", "selector": "#no-such-embed", "index": 9}],
        }
        stale = await adapter.apply_field_value(
            replace(by_label["Email"], metadata=stale_metadata), "wrong@example.com"
        )

        readbacks = {
            name: str(await adapter._page.evaluate(expression))  # noqa: SLF001 - deliberate: see above
            for name, expression in READBACK_JS.items()
        }
        return _BrowserRun(
            fields=fields,
            write_results=write_results,
            stale_write=(stale.ok, stale.message),
            readbacks=readbacks,
        )
    finally:
        with contextlib.suppress(Exception):
            await adapter.close()


@pytest.fixture(scope="module")
def browser_run() -> Iterator[_BrowserRun]:
    """One page, one browser, one launch, shared by every test below."""
    if discover_chrome_executable() is None:
        pytest.skip("no Chrome installation was found")
    with _serve() as url, tempfile.TemporaryDirectory(prefix="applyo-nested-") as profile_dir:
        loop = asyncio.new_event_loop()
        # nodriver reaches for the current event loop rather than the running one,
        # so this has to be installed the way asyncio.run installs it.
        asyncio.set_event_loop(loop)
        try:
            yield loop.run_until_complete(_drive(url, Path(profile_dir)))
        finally:
            # Chrome's subprocess transport tears down asynchronously; give it a
            # turn before the loop closes out from under it.
            loop.run_until_complete(asyncio.sleep(0.25))
            loop.close()
            asyncio.set_event_loop(None)


def _field(run: _BrowserRun, label: str) -> BrowserField:
    matches = [field for field in run.fields if field.label == label]
    assert len(matches) == 1, f"expected exactly one {label!r}, found {len(matches)}"
    return matches[0]


def test_a_real_browser_offers_the_questions_inside_both_embedded_roots(browser_run: _BrowserRun) -> None:
    """Before this change the run saw one field on this page: the newsletter box.

    The application's own questions live in an iframe and a web component, so
    discovery reported a page with nothing to answer and the user was shown an
    empty review step for a form they could plainly see.
    """
    assert sorted(field.label for field in browser_run.fields) == [
        "Email",
        "First Name",
        "Newsletter email",
        "Preferred location",
    ]


@pytest.mark.parametrize(
    ("label", "kind", "selector"),
    [
        ("Email", "frame", "#ats-embed"),
        ("First Name", "frame", "#ats-embed"),
        ("Preferred location", "shadow", "#location-picker"),
    ],
)
def test_each_field_records_the_root_it_actually_came_from(
    browser_run: _BrowserRun, label: str, kind: str, selector: str
) -> None:
    """The path is the address the write and the verify script resolve later."""
    assert dom_path_for(_field(browser_run, label)) == [{"kind": kind, "selector": selector, "index": 0}]


def test_a_field_in_the_page_itself_carries_no_path(browser_run: _BrowserRun) -> None:
    assert dom_path_for(_field(browser_run, "Newsletter email")) == []


def test_the_same_id_in_two_roots_is_not_reported_as_a_collision(browser_run: _BrowserRun) -> None:
    """Both documents call their email box ``#email`` and both keep the selector.

    Suppressing them as ambiguous would be the safe-looking answer and the wrong
    one: it sends two perfectly addressable questions to manual review on a page
    shape that is completely ordinary for an embedded ATS.
    """
    for label in ("Newsletter email", "Email"):
        field = _field(browser_run, label)
        assert field.selector == "#email"
        assert field.metadata.get("ambiguous_selector") is None


def test_a_label_inside_a_shadow_root_is_resolved_from_that_root(browser_run: _BrowserRun) -> None:
    """``label[for]`` cannot be found from the top document, only from the root.

    Looked up in the wrong root the field comes back unlabelled and synthetic, so
    a plainly labelled question is escalated to a human for no reason.
    """
    field = _field(browser_run, "Preferred location")

    assert field.metadata.get("label_source") == "label_for"
    assert field.metadata.get("label_synthetic") is not True


@pytest.mark.parametrize("label", sorted(ANSWERS))
def test_the_adapter_reports_the_write_as_landed(browser_run: _BrowserRun, label: str) -> None:
    ok, message = browser_run.write_results[label]

    assert ok, message


def test_the_answer_is_physically_in_the_embedded_document(browser_run: _BrowserRun) -> None:
    """The failure this whole change exists to prevent, checked in a real browser.

    Resolved from the top document, ``#email`` is the employer's newsletter box.
    The write would land there, the verify would read it back from there, and the
    run would arrive at the submit gate with the application's own email question
    still empty and marked answered.
    """
    assert browser_run.readbacks["embedded email"] == ANSWERS["Email"]
    assert browser_run.readbacks["newsletter email"] == ""


def test_the_answer_is_physically_in_the_shadow_root(browser_run: _BrowserRun) -> None:
    assert browser_run.readbacks["shadow location"] == ANSWERS["Preferred location"]


def test_a_stale_path_refuses_instead_of_writing_to_the_parent(browser_run: _BrowserRun) -> None:
    """A frame navigates, a component re-renders, and the address goes stale.

    Falling back to the top document is the tempting recovery: it finds a
    same-named control, writes there, and reports success. Refusing is the only
    answer that leaves the run honest about what it did.
    """
    ok, message = browser_run.stale_write

    assert ok is False
    assert "no longer reachable" in message
    assert browser_run.readbacks["newsletter email"] == ""
