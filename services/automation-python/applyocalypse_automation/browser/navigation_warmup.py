"""Arrive at a site the way an applicant does, instead of straight into its form.

A run currently opens an apply URL cold: the first packet a portal ever sees
from this browser profile is a deep link to the page where an application gets
submitted. Nobody reaches that page that way. A person lands on a board or a
careers site, the origin sets its cookies, its bundle and fonts land in cache,
and only then do they follow a link inward.

That difference is visible from the server without any JavaScript at all. The
deep request carries no ``Referer``, arrives with no cookie for the origin, and
is the session's first and only hit -- a shape that reads as automation before a
single fingerprinting script has run. Cloudflare and the bot-management products
ATSes sit behind score a session, not a request, and a session one request long
that starts at the most valuable endpoint on the site is the cheapest thing they
have to score.

So the fix is to make the first request to an origin an ordinary one. The front
door is enough: it is always a real page, it sets whatever cookies the origin
sets, and it primes the cache the apply page is about to ask for, which pays
part of the time back on the navigation that follows. Guessing at a more
specific landing page -- the employer's board under a Greenhouse path, a
Workday tenant's search page -- would be more faithful and would also be a
guess, so this does not.

Once per origin, not once per navigation. A run opens the job page, then the
apply page, then often the job page again, and warming an origin the profile has
already been on would be both slow and strange.

The dwell after landing is log-normal for the same reason the gap between
keystrokes in ``human_typing`` is: a person reads a page for a second or two and
occasionally much longer, and a constant delay is a signal of its own.
"""

from __future__ import annotations

import random
from collections.abc import Container
from urllib.parse import urlsplit

# Anything else -- ``file:``, ``about:blank``, a ``data:`` URL -- has no origin
# to warm and no server to form an impression.
_WEB_SCHEMES = frozenset({"http", "https"})

# The front door only has to be reached, not finished rendering, so it gets a
# fraction of the budget a page the worker is about to read would get.
WARM_UP_TIMEOUT_S = 6.0

# Log-normal seconds between landing and following the link inward. The median
# sits at e**MU, and the clamp keeps the tail from stalling a run on a page
# nothing is going to be read from.
DWELL_MU = 0.40
DWELL_SIGMA = 0.45
MIN_DWELL_S = 0.6
MAX_DWELL_S = 6.0


def origin_of(url: str) -> str | None:
    """The scheme and host a URL belongs to, or ``None`` if it belongs to none.

    This is the identity a site is warmed under, so the host is lowercased:
    hostnames are case insensitive, and treating ``Boards.greenhouse.io`` as a
    site the profile has never visited would warm it a second time.
    """
    try:
        parsed = urlsplit(url.strip())
        port = parsed.port
    except ValueError:
        return None

    host = parsed.hostname
    if parsed.scheme not in _WEB_SCHEMES or not host:
        return None
    return f"{parsed.scheme}://{host}:{port}" if port else f"{parsed.scheme}://{host}"


def warm_up_target(url: str, visited: Container[str]) -> str | None:
    """The page to land on before ``url``, or ``None`` to go straight there.

    Returns nothing for a URL with no origin, for an origin this run has already
    been on, and for a URL that is the front door already -- in each of those
    cases a warm-up would either be impossible or would be a second request for
    a page the browser is about to ask for anyway.
    """
    origin = origin_of(url)
    if origin is None or origin in visited:
        return None
    if not urlsplit(url.strip()).path.strip("/"):
        return None
    return f"{origin}/"


def dwell_seconds(rng: random.Random | None = None) -> float:
    """How long to stay on the front door before following the link inward."""
    generator = rng if rng is not None else random.Random()
    return min(MAX_DWELL_S, max(MIN_DWELL_S, generator.lognormvariate(DWELL_MU, DWELL_SIGMA)))
