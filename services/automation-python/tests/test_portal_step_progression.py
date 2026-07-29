"""A progression click only counts when the portal actually moved on.

Portals answer an invalid step by re-rendering the same page with error copy.
Reading that as progress made the worker march through phantom steps and then
demand a submit button that only ever existed on the last page.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from applyocalypse_automation.browser.portal_adapters import final_submit_labels_for_workflow
from applyocalypse_automation.browser.portal_workflows import workflow_for_url
from applyocalypse_automation.runner import (
    PortalPageFingerprint,
    attempt_safe_step_progression,
    final_submit_labels_for,
    new_visible_lines,
    portal_page_changed,
    wait_for_portal_page_change,
)


def fingerprint(
    *,
    url: str = "https://boards.test/apply",
    title: str = "Apply",
    text: str = "Given name\nFamily name",
    selectors: tuple[str, ...] = ("#given-name", "#family-name"),
) -> PortalPageFingerprint:
    return PortalPageFingerprint(
        url=url,
        title=title,
        text=text,
        text_digest=" ".join(text.split()),
        selectors=frozenset(selectors),
    )


PAGE = fingerprint()


@pytest.mark.parametrize(
    ("before", "after", "changed", "case"),
    [
        (PAGE, PAGE, False, "identical page is not progress"),
        (PAGE, fingerprint(url="https://boards.test/apply/2"), True, "new url"),
        (PAGE, fingerprint(title="Experience"), True, "new title"),
        (PAGE, fingerprint(selectors=("#company", "#role")), True, "new fields"),
        # Same fields, new error copy: the portal rejected the step in place.
        (PAGE, fingerprint(text="Given name\nFamily name\nEnter a family name"), False, "validation copy only"),
        (None, PAGE, True, "unreadable before means cannot tell"),
        (PAGE, None, True, "unreadable after means cannot tell"),
        (
            fingerprint(text="Review", selectors=()),
            fingerprint(text="Confirmation", selectors=()),
            True,
            "text decides when there are no fields",
        ),
        (
            fingerprint(text="Review", selectors=()),
            fingerprint(text="Review", selectors=()),
            False,
            "identical text with no fields is not progress",
        ),
    ],
)
def test_page_change_is_judged_on_stable_signals(
    before: PortalPageFingerprint | None,
    after: PortalPageFingerprint | None,
    changed: bool,
    case: str,
) -> None:
    assert portal_page_changed(before, after) is changed, case


def test_new_visible_lines_surfaces_only_the_fresh_validation_copy() -> None:
    before = fingerprint(text="Given name\nFamily name")
    after = fingerprint(text="Given name\nFamily name\nEnter a family name\nEnter a phone number")

    assert new_visible_lines(before, after) == ["Enter a family name", "Enter a phone number"]


def test_new_visible_lines_is_bounded() -> None:
    before = fingerprint(text="Header")
    after = fingerprint(text="Header\n" + "\n".join(f"error {index}" for index in range(40)))

    lines = new_visible_lines(before, after)
    assert len(lines) == 8
    assert all(len(line) <= 200 for line in lines)


class StubAdapter:
    """Serves a scripted sequence of pages, one per read."""

    def __init__(self, pages: list[dict[str, object]], *, click_ok: bool = True) -> None:
        self._pages = pages
        self._reads = 0
        self._click_ok = click_ok
        self.clicked_labels: list[str] = []

    def _page(self) -> dict[str, object]:
        page = self._pages[min(self._reads, len(self._pages) - 1)]
        self._reads += 1
        return page

    async def extract_visible_text(self):
        page = self._page()
        return type(
            "Result",
            (),
            {"ok": True, "payload": {"text": page["text"], "url": page["url"], "title": page["title"]}},
        )()

    async def detect_fields(self):
        page = self._pages[min(max(self._reads - 1, 0), len(self._pages) - 1)]
        return [
            type("Field", (), {"selector": selector, "field_id": selector})()
            for selector in page["selectors"]
        ]

    async def click_by_text(self, labels):
        self.clicked_labels = list(labels)
        return type(
            "Result",
            (),
            {"ok": self._click_ok, "message": "", "payload": {"action": "click_by_text", "clicked_label": "Next"}},
        )()

    async def detect_blockers(self):
        return []


def page(url: str, title: str, text: str, selectors: tuple[str, ...]) -> dict[str, object]:
    return {"url": url, "title": title, "text": text, "selectors": selectors}


WORKFLOW = workflow_for_url("https://boards.greenhouse.io/example/jobs/1")


def run_progression(adapter: StubAdapter, tmp_path, *, timeout_s: float = 0.0) -> str:
    return asyncio.run(
        attempt_safe_step_progression(
            adapter=adapter,
            work_dir=tmp_path,
            run_id="run-progress",
            workflow=WORKFLOW,
            context="test",
            step_index=1,
            page_change_timeout_s=timeout_s,
        )
    )


def test_a_page_that_re_renders_with_errors_reports_blocked(tmp_path, capsys) -> None:
    same_page = page("https://boards.test/apply", "Apply", "Given name\nFamily name", ("#given-name", "#family-name"))
    rejected = page(
        "https://boards.test/apply",
        "Apply",
        "Given name\nFamily name\nEnter a family name",
        ("#given-name", "#family-name"),
    )
    adapter = StubAdapter([same_page] + [rejected] * 60)

    result = run_progression(adapter, tmp_path)

    events = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    blocked = [event for event in events if event["machine_state"].get("reason") == "PORTAL_STEP_DID_NOT_ADVANCE"]
    assert result == "blocked"
    assert len(blocked) == 1
    assert blocked[0]["event_type"] == "PAUSED"
    assert blocked[0]["ui_state"]["requires_user_review"] is True
    assert "Enter a family name" in blocked[0]["payload"]["validation_messages"]


def test_a_real_next_step_reports_advanced(tmp_path, capsys) -> None:
    first = page("https://boards.test/apply", "Apply", "Given name", ("#given-name",))
    second = page("https://boards.test/apply/2", "Experience", "Company", ("#company",))
    adapter = StubAdapter([first, second])

    result = run_progression(adapter, tmp_path)

    events = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert result == "advanced"
    assert not [event for event in events if event["machine_state"].get("reason") == "PORTAL_STEP_DID_NOT_ADVANCE"]


def test_change_wait_returns_as_soon_as_the_page_moves(tmp_path) -> None:
    stale = page("https://boards.test/apply", "Apply", "Given name", ("#given-name",))
    fresh = page("https://boards.test/apply/2", "Experience", "Company", ("#company",))
    adapter = StubAdapter([stale, stale, fresh])
    before = PortalPageFingerprint(
        url=stale["url"],
        title=stale["title"],
        text=str(stale["text"]),
        text_digest=str(stale["text"]),
        selectors=frozenset(stale["selectors"]),
    )

    after = asyncio.run(
        wait_for_portal_page_change(adapter, before, timeout_s=5.0, poll_interval_s=0.0, sleep=asyncio.sleep)
    )

    assert after is not None
    assert after.url == "https://boards.test/apply/2"


def test_final_submit_labels_lead_with_the_portals_own_wording() -> None:
    registered = list(final_submit_labels_for_workflow(WORKFLOW))
    labels = final_submit_labels_for(WORKFLOW)

    # The portal's own wording comes first so an exact-match click can reach a
    # button the generic list never names, and the fallbacks follow undiluted.
    assert labels[: len(registered)] == registered
    assert "Submit application" in labels
    assert len(labels) == len(set(labels))


def test_final_submit_labels_fall_back_to_the_generic_list_without_a_workflow() -> None:
    assert final_submit_labels_for(None) == [
        "Submit",
        "Submit application",
        "Send application",
        "Finish application",
        "Complete application",
    ]
