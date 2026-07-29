from __future__ import annotations

import pytest

from applyocalypse_automation.otp.verification_link import (
    MAX_CANDIDATE_LINKS,
    extract_verification_links,
    redact_link,
    select_trusted_verification_link,
)


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        (
            "Click https://wd5.myworkday.com/verify?token=abc123 to confirm your email.",
            ("https://wd5.myworkday.com/verify?token=abc123",),
        ),
        (
            '<a href="https://my.greenhouse.io/confirm/xyz">Verify email</a>',
            ("https://my.greenhouse.io/confirm/xyz",),
        ),
        # An href carrying an escaped ampersand must survive as a usable URL.
        (
            '<a href="https://jobs.lever.co/verify?id=7&amp;sig=deadbeef">Confirm</a>',
            ("https://jobs.lever.co/verify?id=7&sig=deadbeef",),
        ),
        # Trailing sentence punctuation is not part of the link.
        (
            "Confirm at https://boards.ashbyhq.com/verify/abc.",
            ("https://boards.ashbyhq.com/verify/abc",),
        ),
        (
            "Wrapped in parens (https://boards.ashbyhq.com/verify/abc) here.",
            ("https://boards.ashbyhq.com/verify/abc",),
        ),
        # The same link in the plaintext part and the HTML part is one link.
        (
            'https://wd5.myworkday.com/v?t=1\n<a href="https://wd5.myworkday.com/v?t=1">click</a>',
            ("https://wd5.myworkday.com/v?t=1",),
        ),
        # Order is preserved so the caller can prefer the first plausible link.
        (
            "https://one.example.com/a and https://two.example.com/b",
            ("https://one.example.com/a", "https://two.example.com/b"),
        ),
        # http is refused outright: a magic link in cleartext is a leaked credential.
        ("Visit http://wd5.myworkday.com/verify?token=abc", ()),
        ("No links in this message at all.", ()),
        ("", ()),
    ],
)
def test_extract_verification_links(body: str, expected: tuple[str, ...]) -> None:
    assert extract_verification_links(body) == expected


def test_extract_verification_links_caps_candidates() -> None:
    body = " ".join(f"https://host{index}.example.com/verify" for index in range(MAX_CANDIDATE_LINKS + 25))

    assert len(extract_verification_links(body)) == MAX_CANDIDATE_LINKS


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        # The query string is where the token lives, so it never survives redaction.
        ("https://wd5.myworkday.com/verify?token=abc123def456", "https://wd5.myworkday.com/verify"),
        ("https://wd5.myworkday.com/verify#token=abc123def456", "https://wd5.myworkday.com/verify"),
        # A token can also ride in the path, so long segments are elided.
        (
            "https://my.greenhouse.io/confirm/eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9",
            "https://my.greenhouse.io/confirm/[...]",
        ),
        ("https://wd5.myworkday.com", "https://wd5.myworkday.com"),
        ("https://wd5.myworkday.com/", "https://wd5.myworkday.com"),
        ("not a url", "[unparseable link]"),
    ],
)
def test_redact_link(url: str, expected: str) -> None:
    assert redact_link(url) == expected


@pytest.mark.parametrize(
    ("url", "secret"),
    [
        ("https://wd5.myworkday.com/verify?token=abc123def456", "abc123def456"),
        ("https://wd5.myworkday.com/verify#code=zzz999888777", "zzz999888777"),
        ("https://my.greenhouse.io/confirm/eyJhbGciOiJIUzI1NiJ9", "eyJhbGciOiJIUzI1NiJ9"),
    ],
)
def test_redact_link_never_leaks_the_token(url: str, secret: str) -> None:
    """The redacted form is the only form allowed into an event, so it must not carry the token."""
    assert secret not in redact_link(url)


@pytest.mark.parametrize(
    ("links", "portal_url", "expected"),
    [
        # Same portal, same registrable domain.
        (
            ("https://boards.ashbyhq.com/verify/abc",),
            "https://jobs.ashbyhq.com/acme/apply",
            "https://boards.ashbyhq.com/verify/abc",
        ),
        # The Workday case: verification mail links to myworkday.com while the
        # application lives on myworkdayjobs.com.
        (
            ("https://wd5.myworkday.com/verify?token=abc",),
            "https://acme.wd5.myworkdayjobs.com/en-US/careers/job/123",
            "https://wd5.myworkday.com/verify?token=abc",
        ),
        # An unrelated host is refused even when it looks like a verification link.
        (("https://verify-workday.attacker.example/verify?token=abc",), "https://acme.wd5.myworkdayjobs.com/apply", None),
        # A lookalike suffix must not pass: attacker owns notmyworkday.com.
        (("https://wd5.notmyworkday.com/verify",), "https://acme.wd5.myworkdayjobs.com/apply", None),
        # Another portal's domain is still the wrong portal for this run.
        (("https://jobs.lever.co/verify/abc",), "https://boards.greenhouse.io/acme/jobs/1", None),
        # The first trusted link wins; untrusted candidates ahead of it are skipped.
        (
            ("https://tracker.attacker.example/click", "https://jobs.lever.co/verify/abc"),
            "https://jobs.lever.co/acme/apply",
            "https://jobs.lever.co/verify/abc",
        ),
        # An unrecognised page trusts nothing: there is no origin to compare against.
        (("https://jobs.lever.co/verify/abc",), "https://careers.unknown-startup.example/apply", None),
        ((), "https://jobs.lever.co/acme/apply", None),
        (("https://jobs.lever.co/verify/abc",), "", None),
    ],
)
def test_select_trusted_verification_link(links: tuple[str, ...], portal_url: str, expected: str | None) -> None:
    assert select_trusted_verification_link(links, portal_url) == expected
