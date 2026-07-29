"""Email verification links.

Some portals do not mail a numeric code; they mail a one-click confirmation
link. That link authenticates whoever holds it, so it is a credential in the
same sense an OTP is: it must never be logged, persisted, or emitted in a
worker event. Only :func:`redact_link` output is safe to hand upstream.

An inbox is also untrusted input. Any message that happens to arrive during a
run could carry a link, so a candidate is only ever offered to the user when it
resolves to the same portal as the page the run is sitting on.
"""

from __future__ import annotations

import html
import re
from urllib.parse import urlparse

from ..browser.portal_registry import detect_portal

# A verification mail carries a handful of links at most (the button, a
# plaintext fallback, an unsubscribe footer). Anything past this is noise.
MAX_CANDIDATE_LINKS = 20

# Path segments longer than this are assumed to be tokens rather than route
# names, so they are elided before a link is described to anyone.
_MAX_SAFE_SEGMENT_LENGTH = 12

# https only: a magic link fetched over http is a credential in cleartext.
_LINK_PATTERN = re.compile(r"https://[^\s<>\"'\\]+")

_TRAILING_NOISE = ".,;:!?)]}>\"'"

# Portals whose verification mail links to a different registrable domain than
# the one the application is served from. Without an entry here a legitimate
# link would be rejected as foreign; with a wrong entry an attacker's domain
# would be trusted, so only add a domain the portal demonstrably owns.
PORTAL_VERIFICATION_DOMAINS: dict[str, tuple[str, ...]] = {
    # Applications run on *.myworkdayjobs.com; account mail links to myworkday.com.
    "workday": ("myworkday.com",),
}


def extract_verification_links(text: str) -> tuple[str, ...]:
    """Pull candidate https links out of an email body, in order, deduplicated."""
    if not text:
        return ()
    unescaped = html.unescape(text)
    seen: dict[str, None] = {}
    for match in _LINK_PATTERN.finditer(unescaped):
        candidate = match.group(0).rstrip(_TRAILING_NOISE)
        if not urlparse(candidate).hostname:
            continue
        seen.setdefault(candidate, None)
        if len(seen) >= MAX_CANDIDATE_LINKS:
            break
    return tuple(seen)


def redact_link(url: str) -> str:
    """Render a link in the only shape that is safe to persist or display.

    Drops the query and fragment outright and elides token-shaped path
    segments, leaving just enough for a human to judge where the link goes.
    """
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        return "[unparseable link]"
    segments = [
        "[...]" if len(segment) > _MAX_SAFE_SEGMENT_LENGTH else segment
        for segment in parsed.path.split("/")
        if segment
    ]
    path = "/".join(segments)
    return f"https://{parsed.hostname}/{path}" if path else f"https://{parsed.hostname}"


def link_is_trusted_for_portal(url: str, portal_id: str) -> bool:
    """True when ``url`` belongs to the portal identified by ``portal_id``."""
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        return False
    link_portal = detect_portal(url)
    if link_portal is not None and link_portal.portal_id == portal_id:
        return True
    host = parsed.hostname.lower()
    return any(
        host == domain or host.endswith(f".{domain}")
        for domain in PORTAL_VERIFICATION_DOMAINS.get(portal_id, ())
    )


def select_trusted_verification_link(links: tuple[str, ...], portal_url: str) -> str | None:
    """Pick the first link that provably belongs to the portal being applied to.

    Returns ``None`` rather than a best guess. A link that cannot be tied to the
    live page is not surfaced at all, because approving an unknown destination
    mid-run is exactly the redirect an injected email would be aiming for.
    """
    portal = detect_portal(portal_url)
    if portal is None:
        return None
    for candidate in links:
        if link_is_trusted_for_portal(candidate, portal.portal_id):
            return candidate
    return None
