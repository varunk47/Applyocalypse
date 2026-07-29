"""Portal reachability probe.

This module measures exactly one thing: whether a configured live application
URL answers an HTTP GET and maps to a portal adapter plan that still carries a
FINAL_SUBMIT review gate.

It never opens the application form, never fills a field, and never reads a
value back, so it cannot show that a portal is *fillable*. That is a separate
property, tracked on the adapter plan as ``fill_capability_status`` and only
ever carried through here verbatim: a 200 OK can never upgrade a portal's fill
capability, and no status produced by this module means "certified".

The module path is kept for ``scripts/certification/live-portal-certification.mjs``;
everything it reports is named for reachability.
"""
from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from pathlib import Path
from urllib.error import URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from .portal_adapters import (
    ATS_ADAPTER_PLANS,
    FILL_CAPABILITY_UNPROVEN,
    portal_adapter_plan_for_workflow,
)
from .portal_registry import PORTALS, detect_portal
from .portal_workflows import workflow_for_url

TARGET_PORTAL_IDS: tuple[str, ...] = tuple(portal.portal_id for portal in PORTALS)

# Outcomes of the probe. None of them is a certification, and none of them says
# anything about whether the portal's form can be filled.
REACHABILITY_REACHABLE = "REACHABLE"
REACHABILITY_UNREACHABLE = "UNREACHABLE"
REACHABILITY_BLOCKED = "BLOCKED"
REACHABILITY_MISCONFIGURED = "MISCONFIGURED"

REACHABILITY_STATUSES: frozenset[str] = frozenset(
    {
        REACHABILITY_REACHABLE,
        REACHABILITY_UNREACHABLE,
        REACHABILITY_BLOCKED,
        REACHABILITY_MISCONFIGURED,
    }
)

REPORT_TYPE = "PORTAL_REACHABILITY_PROBE"

TRUTHFULNESS_POLICY = (
    "REACHABLE means only that the configured URL answered an HTTP GET and that the URL maps to a "
    "gated adapter plan. It is not evidence that any field was filled, that a form was completed, "
    "or that an application was submitted. Fill capability is reported separately per portal and is "
    "never raised by this probe."
)

_ALLOWED_URL_SCHEMES = frozenset({"http", "https"})


@dataclass(frozen=True, slots=True)
class ReachabilityTarget:
    portal_id: str
    url: str | None
    requires_credentials: bool = False
    notes: str = ""


@dataclass(frozen=True, slots=True)
class ReachabilityResult:
    portal_id: str
    status: str
    checks: tuple[str, ...]
    blockers: tuple[str, ...]
    fill_capability: str
    fill_capability_blockers: tuple[str, ...] = ()
    url: str | None = None
    http_status: int | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "portal_id": self.portal_id,
            "reachability_status": self.status,
            "checks": list(self.checks),
            "blockers": list(self.blockers),
            "fill_capability": self.fill_capability,
            "fill_capability_blockers": list(self.fill_capability_blockers),
            "url": self.url,
            "http_status": self.http_status,
        }


def fill_capability_for_portal(portal_id: str) -> tuple[str, tuple[str, ...]]:
    """Declared fill capability for a portal, independent of any network probe."""
    plan = ATS_ADAPTER_PLANS.get(portal_id)
    if plan is None:
        return (FILL_CAPABILITY_UNPROVEN, ("REQUIRES_PORTAL_SPECIFIC_ADAPTER", "REQUIRES_LIVE_JOB_FIXTURES"))
    return (plan.fill_capability_status, plan.fill_capability_blockers)


def default_targets() -> tuple[ReachabilityTarget, ...]:
    return tuple(ReachabilityTarget(portal_id=portal_id, url=None) for portal_id in TARGET_PORTAL_IDS)


def load_targets(path: Path | None) -> tuple[ReachabilityTarget, ...]:
    if path is None:
        return default_targets()
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError("Reachability target file must contain a JSON array")
    targets: list[ReachabilityTarget] = []
    for item in raw:
        if not isinstance(item, dict):
            raise ValueError("Each reachability target must be a JSON object")
        portal_id = str(item.get("portal_id") or "").strip()
        if portal_id not in TARGET_PORTAL_IDS:
            raise ValueError(f"Unsupported portal_id in reachability target file: {portal_id}")
        url = item.get("url")
        targets.append(
            ReachabilityTarget(
                portal_id=portal_id,
                url=str(url).strip() if isinstance(url, str) and url.strip() else None,
                requires_credentials=bool(item.get("requires_credentials", False)),
                notes=str(item.get("notes") or ""),
            )
        )
    return tuple(targets)


def _fetch_status(url: str, timeout_seconds: float) -> int:
    request = Request(
        url,
        headers={
            "User-Agent": "ApplyocalypseReachabilityProbe/0.1 (+local-desktop-readiness-check)",
            "Accept": "text/html,application/xhtml+xml",
        },
        method="GET",
    )
    with urlopen(request, timeout=timeout_seconds) as response:  # nosec B310: scheme-checked, operator-triggered URL.
        return int(getattr(response, "status", 0) or response.getcode())


def probe_target_reachability(
    target: ReachabilityTarget,
    *,
    live_enabled: bool,
    network_enabled: bool,
    timeout_seconds: float = 8.0,
) -> ReachabilityResult:
    """Probe one target. The returned fill capability is read from the adapter
    plan and is never derived from the HTTP response."""
    checks: list[str] = []
    blockers: list[str] = []
    capability, capability_blockers = fill_capability_for_portal(target.portal_id)

    def result(status: str, *, extra_blockers: tuple[str, ...] = (), http_status: int | None = None) -> ReachabilityResult:
        return ReachabilityResult(
            portal_id=target.portal_id,
            status=status,
            checks=tuple(checks),
            blockers=tuple(blockers) + extra_blockers,
            fill_capability=capability,
            fill_capability_blockers=capability_blockers,
            url=target.url,
            http_status=http_status,
        )

    if not target.url:
        return result(REACHABILITY_BLOCKED, extra_blockers=("missing_live_application_url",))

    if urlparse(target.url).scheme.lower() not in _ALLOWED_URL_SCHEMES:
        return result(REACHABILITY_MISCONFIGURED, extra_blockers=("unsupported_url_scheme",))

    detected = detect_portal(target.url)
    if detected is None or detected.portal_id != target.portal_id:
        return result(REACHABILITY_MISCONFIGURED, extra_blockers=(f"url_does_not_match_portal:{target.url}",))
    checks.append("portal_detected")

    plan = portal_adapter_plan_for_workflow(workflow_for_url(target.url))
    if not plan.steps:
        return result(REACHABILITY_MISCONFIGURED, extra_blockers=("missing_portal_adapter_plan",))
    checks.append("adapter_plan_loaded")

    if "FINAL_SUBMIT" not in plan.required_review_gates:
        checks.append("final_submit_gate_missing")
        return result(REACHABILITY_MISCONFIGURED, extra_blockers=("final_submit_gate_missing",))
    checks.append("final_submit_gate_present")

    if target.requires_credentials:
        blockers.append("requires_portal_account_or_test_identity")
    if not live_enabled:
        blockers.append("set_APPLYO_LIVE_CERTIFICATION_1_to_run_live_checks")
    if not network_enabled:
        blockers.append("network_probe_disabled")

    if blockers:
        return result(REACHABILITY_BLOCKED)

    try:
        http_status = _fetch_status(target.url, timeout_seconds)
    except (OSError, URLError, TimeoutError) as exc:
        return result(REACHABILITY_UNREACHABLE, extra_blockers=(f"network_probe_failed:{type(exc).__name__}",))

    checks.append("network_probe_completed")
    if 200 <= http_status < 400:
        # Deliberately not an upgrade: the page answered, nothing was filled.
        return result(REACHABILITY_REACHABLE, http_status=http_status)
    return result(
        REACHABILITY_UNREACHABLE,
        extra_blockers=(f"unexpected_http_status:{http_status}",),
        http_status=http_status,
    )


def probe_targets(
    targets: tuple[ReachabilityTarget, ...],
    *,
    live_enabled: bool,
    network_enabled: bool,
    timeout_seconds: float = 8.0,
) -> tuple[ReachabilityResult, ...]:
    by_portal = {target.portal_id: target for target in targets}
    results: list[ReachabilityResult] = []
    for portal_id in TARGET_PORTAL_IDS:
        target = by_portal.get(portal_id)
        if target is None:
            capability, capability_blockers = fill_capability_for_portal(portal_id)
            results.append(
                ReachabilityResult(
                    portal_id=portal_id,
                    status=REACHABILITY_BLOCKED,
                    checks=(),
                    blockers=("portal_missing_from_target_file",),
                    fill_capability=capability,
                    fill_capability_blockers=capability_blockers,
                )
            )
            continue
        results.append(
            probe_target_reachability(
                target,
                live_enabled=live_enabled,
                network_enabled=network_enabled,
                timeout_seconds=timeout_seconds,
            )
        )
    return tuple(results)


def report_payload(results: tuple[ReachabilityResult, ...]) -> dict[str, object]:
    totals = {
        "reachable": sum(1 for result in results if result.status == REACHABILITY_REACHABLE),
        "blocked": sum(1 for result in results if result.status == REACHABILITY_BLOCKED),
        "unreachable": sum(1 for result in results if result.status == REACHABILITY_UNREACHABLE),
        "misconfigured": sum(1 for result in results if result.status == REACHABILITY_MISCONFIGURED),
    }
    fill_capability_totals: dict[str, int] = {}
    for result in results:
        fill_capability_totals[result.fill_capability] = fill_capability_totals.get(result.fill_capability, 0) + 1
    return {
        "report_type": REPORT_TYPE,
        "truthfulness_policy": TRUTHFULNESS_POLICY,
        "totals": totals,
        "fill_capability_totals": fill_capability_totals,
        "results": [result.to_dict() for result in sorted(results, key=lambda item: item.portal_id)],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Probe Applyocalypse portal application URLs for reachability.")
    parser.add_argument("--targets", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--network", action="store_true", help="Perform a read-only network probe of each configured URL.")
    args = parser.parse_args(argv)

    live_enabled = os.environ.get("APPLYO_LIVE_CERTIFICATION") == "1"
    results = probe_targets(load_targets(args.targets), live_enabled=live_enabled, network_enabled=bool(args.network))
    payload = report_payload(results)
    rendered = json.dumps(payload, indent=2, sort_keys=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    else:
        print(rendered)
    failed = (REACHABILITY_UNREACHABLE, REACHABILITY_MISCONFIGURED)
    return 1 if any(result.status in failed for result in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
