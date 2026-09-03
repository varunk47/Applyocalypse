"""Does the injected blocker script actually run in a real browser?

``detect_blockers`` wraps the injection in ``except Exception: return []``. That
is the right call at runtime -- a page that breaks the scan should not crash a
run -- but it means a syntax error in the script is indistinguishable from a
clean page with nothing to report. The offline suite cannot see the difference
either: its twin is Python, so it would keep passing while the shipped detector
returned nothing on every page in the world.

So this module serves challenge-shaped pages over real HTTP, drives real Chrome
through the real adapter, and asserts the script comes back with the vendor it
should. Deselected from the default gate (``-m 'not browser'``) and run from
``pnpm test:python:browser``, for the same reasons as the parity suite.
"""

from __future__ import annotations

import asyncio
import contextlib
import tempfile
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from applyocalypse_automation.browser.chrome_discovery import discover_chrome_executable
from applyocalypse_automation.browser.nodriver_adapter import NodriverBrowserAdapter

pytestmark = pytest.mark.browser


def _page(body: str, title: str = "Apply: Staff Platform Engineer") -> str:
    return f"<!doctype html><html><head><title>{title}</title></head><body>{body}</body></html>"


# The vendor iframes below point at hosts that will never resolve. That is on
# purpose: the detector reads the src attribute and the element's box, never the
# frame's content, so a fixture must not depend on reaching a captcha vendor from
# a test machine. The explicit size is what makes each one count as a visible
# challenge rather than a hidden badge.
_FRAME_STYLE = "width:302px;height:422px;border:1px solid #ccc"

# Verbatim from a Greenhouse form: the sentence that once matched on the word
# "recaptcha" and paused runs against forms with nothing to solve.
PASSIVE_NOTICE = (
    "This site is protected by reCAPTCHA and the Google Privacy Policy and "
    "Terms of Service apply."
)

PAGES: dict[str, str] = {
    # Arkose serves its client API from a per-customer subdomain, so the stable
    # half of the match is the registrable domain, not the host. LinkedIn is the
    # portal that puts this vendor in our path.
    "/arkose": _page(f'<iframe src="https://northstar-api.arkoselabs.com/v2/enforcement" style="{_FRAME_STYLE}"></iframe>'),
    "/perimeterx": _page(
        f'<div id="px-captcha" style="{_FRAME_STYLE}">Press and hold to confirm you are human</div>'
    ),
    "/hcaptcha": _page(f'<iframe src="https://newassets.hcaptcha.com/captcha/v1/frame" style="{_FRAME_STYLE}"></iframe>'),
    # No vendor we can name, which is the case the phrase backstop exists for.
    "/unknown": _page(
        f'<div class="shield-challenge" style="{_FRAME_STYLE}"><h1>Select all images with a bus</h1></div>'
    ),
    # An invisible v3 badge plus the footer notice, on a page that is genuinely a
    # form. This must stay clean: pausing here is the phantom block.
    "/passive": _page(
        '<form><label for="email">Email</label><input id="email" name="email" type="email">'
        '<div class="grecaptcha-badge" style="width:256px;height:60px">'
        '<iframe src="https://www.google.com/recaptcha/api2/anchor?size=invisible" style="width:256px;height:60px"></iframe>'
        f"</div><p>{PASSIVE_NOTICE}</p></form>"
    ),
}


class _FixtureHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler's spelling
        encoded = PAGES.get(self.path, _page("<p>Northstar</p>")).encode("utf-8")
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
    server = _QuietServer(("127.0.0.1", 0), _FixtureHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


async def _drive(origin: str, user_data_dir: Path) -> dict[str, list[dict[str, object]]]:
    adapter = NodriverBrowserAdapter()
    launched = await adapter.launch(run_id="blocker-detection", user_data_dir=user_data_dir)
    if not launched.ok:
        pytest.skip(f"no browser available: {launched.message}")
    try:
        seen: dict[str, list[dict[str, object]]] = {}
        for path in PAGES:
            opened = await adapter.open_url(f"{origin}{path}")
            assert opened.ok, opened.message
            # A cross-origin frame that will never resolve still has to be given
            # its layout box before the script measures it.
            await asyncio.sleep(0.4)
            seen[path] = [
                {"type": blocker.blocker_type, "metadata": blocker.metadata}
                for blocker in await adapter.detect_blockers()
            ]
        return seen
    finally:
        with contextlib.suppress(Exception):
            await adapter.close()


@pytest.fixture(scope="module")
def blockers() -> Iterator[dict[str, list[dict[str, object]]]]:
    """One browser, every fixture page."""
    if discover_chrome_executable() is None:
        pytest.skip("no Chrome installation was found")
    with _serve() as origin, tempfile.TemporaryDirectory(prefix="applyo-blockers-") as profile_dir:
        loop = asyncio.new_event_loop()
        # nodriver reaches for the current event loop rather than the running one.
        asyncio.set_event_loop(loop)
        try:
            yield loop.run_until_complete(_drive(origin, Path(profile_dir)))
        finally:
            loop.run_until_complete(asyncio.sleep(0.25))
            loop.close()
            asyncio.set_event_loop(None)


def _captcha(reported: list[dict[str, object]]) -> dict[str, object] | None:
    for blocker in reported:
        if blocker["type"] == "CAPTCHA":
            return blocker
    return None


def test_the_script_survives_injection(blockers: dict[str, list[dict[str, object]]]) -> None:
    """The floor: a swallowed syntax error looks exactly like a clean page."""
    assert any(_captcha(reported) for reported in blockers.values()), (
        "no page reported a CAPTCHA, which is what a broken script looks like "
        "through detect_blockers' except-and-return-[]"
    )


@pytest.mark.parametrize(
    ("path", "vendor"),
    [("/arkose", "arkose"), ("/perimeterx", "perimeterx"), ("/hcaptcha", "hcaptcha"), ("/unknown", "unknown")],
)
def test_a_challenge_is_reported_with_its_vendor(
    blockers: dict[str, list[dict[str, object]]], path: str, vendor: str
) -> None:
    found = _captcha(blockers[path])
    assert found is not None, f"{path} was not recognised as a challenge"
    assert (found["metadata"] or {}).get("vendor") == vendor


def test_a_passive_badge_on_a_real_form_does_not_block(
    blockers: dict[str, list[dict[str, object]]],
) -> None:
    """The phantom block, checked in the browser rather than against the twin."""
    assert _captcha(blockers["/passive"]) is None
