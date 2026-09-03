"""Guardrails for two stealth mistakes that are easy to make and hard to notice.

Neither is a bug in the worker today. Both are things a reasonable person adds
while trying to help, which is exactly why they are worth pinning: the damage
does not show up in a test run, it shows up as portals that stop answering.
"""
from __future__ import annotations

import re
from pathlib import Path

from applyocalypse_automation.browser import nodriver_adapter

_BROWSER_SOURCES = sorted(Path(nodriver_adapter.__file__).parent.glob("*.py"))

# Every way a style gets written, from Python or from injected JS.
_STYLE_WRITE = re.compile(r"""\.style\.(?P<attr>[A-Za-z-]+)\s*=(?!=)|setProperty\(\s*['"](?P<prop>[A-Za-z-]+)['"]""")

# Properties that change how a page looks without changing what it does. A
# debug highlight is made of these and nothing else.
_DECORATIVE = frozenset(
    {
        "outline",
        "outlineColor",
        "outline-color",
        "border",
        "borderColor",
        "border-color",
        "boxShadow",
        "box-shadow",
        "background",
        "backgroundColor",
        "background-color",
        "filter",
    }
)

_USER_AGENT_OVERRIDES = (
    "setUserAgentOverride",
    "set_user_agent_override",
    "--user-agent",
)


def test_there_is_something_to_check() -> None:
    """A guardrail that scans nothing passes for the wrong reason."""
    assert len(_BROWSER_SOURCES) > 5


def test_nothing_paints_a_marker_onto_a_page_the_user_can_see() -> None:
    """Outlining the field being filled is the first debugging idea anyone has.

    It is also visible to the site: a page can read back its own elements'
    inline styles and a MutationObserver fires on every one of these. Worse,
    the user is watching this browser, and a form that decorates itself is not
    a form a person filled in.

    Functional style writes are fine and the worker makes them: an ATS dropzone
    hides its real file input behind ``display: none``, and it has to be
    revealed before files can be attached to it. That changes what the page
    does, not how it looks.
    """
    offenders = []
    for source in _BROWSER_SOURCES:
        text = source.read_text(encoding="utf-8")
        for match in _STYLE_WRITE.finditer(text):
            written = match.group("attr") or match.group("prop")
            if written in _DECORATIVE:
                line = text.count("\n", 0, match.start()) + 1
                offenders.append(f"{source.name}:{line} writes {written}")

    assert offenders == [], "these paint into the live page: " + ", ".join(offenders)


def test_nothing_overrides_the_user_agent() -> None:
    """A forged UA string is a tell, not a disguise.

    Chrome reports itself in three places that have to agree: the header, the
    ``navigator.userAgent`` string, and the Client Hints in
    ``navigator.userAgentData``. ``setUserAgentOverride`` moves the first two
    and leaves the third, and a version mismatch between them is a cheaper and
    more certain signal than anything the override was hiding. The real Chrome
    this worker drives already sends a real, current UA.
    """
    offenders = [
        f"{source.name} uses {marker}"
        for source in _BROWSER_SOURCES
        for marker in _USER_AGENT_OVERRIDES
        if marker in source.read_text(encoding="utf-8")
    ]

    assert offenders == [], "these forge a user agent: " + ", ".join(offenders)
