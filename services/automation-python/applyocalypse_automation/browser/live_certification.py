from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen

from .portal_adapters import portal_adapter_plan_for_workflow
from .portal_registry import PORTALS, detect_portal
from .portal_workflows import workflow_for_url

TARGET_PORTAL_IDS = tuple(portal.portal_id for portal in PORTALS)


@dataclass(frozen=True, slots=True)
class CertificationTarget:
    portal_id: str
    url: str | None
    requires_credentials: bool = False
    notes: str = ""


@dataclass(frozen=True, slots=True)
class CertificationResult:
    portal_id: str
    status: str
    checks: tuple[str, ...]
    blockers: tuple[str, ...]
    url: str | None = None
    http_status: int | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "portal_id": self.portal_id,
            "status": self.status,
            "checks": list(self.checks),
            "blockers": list(self.blockers),
            "url": self.url,
            "http_status": self.http_status,
        }


def default_targets() -> tuple[CertificationTarget, ...]:
    return tuple(CertificationTarget(portal_id=portal_id, url=None) for portal_id in TARGET_PORTAL_IDS)


def load_targets(path: Path | None) -> tuple[CertificationTarget, ...]:
    if path is None:
        return default_targets()
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError("Live certification target file must be a JSON array")
    targets: list[CertificationTarget] = []
    for item in raw:
        if not isinstance(item, dict):
            raise ValueError("Each live certification target must be a JSON object")
        portal_id = str(item.get("portal_id") or "").strip()
        if portal_id not in TARGET_PORTAL_IDS:
            raise ValueError(f"Unsupported portal_id in live certification target: {portal_id}")
        url = item.get("url")
        targets.append(
            CertificationTarget(
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
            "User-Agent": "ApplyocalypseLiveCertification/0.1 (+local-desktop-readiness-check)",
            "Accept": "text/html,application/xhtml+xml",
        },
        method="GET",
    )
    with urlopen(request, timeout=timeout_seconds) as response:  # nosec B310: explicit operator-triggered certification URL.
        return int(getattr(response, "status", 0) or response.getcode())


def certify_target(
    target: CertificationTarget,
    *,
    live_enabled: bool,
    network_enabled: bool,
    timeout_seconds: float = 8.0,
) -> CertificationResult:
    checks: list[str] = []
    blockers: list[str] = []

    if not target.url:
        return CertificationResult(
            portal_id=target.portal_id,
            status="BLOCKED",
            checks=tuple(checks),
            blockers=("missing_live_application_url",),
            url=None,
        )

    detected = detect_portal(target.url)
    if detected is None or detected.portal_id != target.portal_id:
        return CertificationResult(
            portal_id=target.portal_id,
            status="FAIL",
            checks=tuple(checks),
            blockers=(f"url_does_not_match_portal:{target.url}",),
            url=target.url,
        )
    checks.append("portal_detected")

    workflow = workflow_for_url(target.url)
    plan = portal_adapter_plan_for_workflow(workflow)
    if not plan.steps:
        return CertificationResult(
            portal_id=target.portal_id,
            status="FAIL",
            checks=tuple(checks),
            blockers=("missing_portal_adapter_plan",),
            url=target.url,
        )
    checks.append("adapter_plan_loaded")
    checks.append("final_submit_gate_present" if "FINAL_SUBMIT" in plan.required_review_gates else "final_submit_gate_missing")

    if "FINAL_SUBMIT" not in plan.required_review_gates:
        return CertificationResult(
            portal_id=target.portal_id,
            status="FAIL",
            checks=tuple(checks),
            blockers=("final_submit_gate_missing",),
            url=target.url,
        )

    if target.requires_credentials:
        blockers.append("requires_portal_account_or_test_identity")
    if not live_enabled:
        blockers.append("set_APPLYO_LIVE_CERTIFICATION_1_to_run_live_checks")
    if not network_enabled:
        blockers.append("network_probe_disabled")

    if blockers:
        return CertificationResult(
            portal_id=target.portal_id,
            status="BLOCKED",
            checks=tuple(checks),
            blockers=tuple(blockers),
            url=target.url,
        )

    try:
        http_status = _fetch_status(target.url, timeout_seconds)
    except (OSError, URLError, TimeoutError) as exc:
        return CertificationResult(
            portal_id=target.portal_id,
            status="FAIL",
            checks=tuple(checks),
            blockers=(f"network_probe_failed:{type(exc).__name__}",),
            url=target.url,
        )

    checks.append("network_probe_completed")
    status = "PASS" if 200 <= http_status < 400 else "FAIL"
    return CertificationResult(
        portal_id=target.portal_id,
        status=status,
        checks=tuple(checks),
        blockers=() if status == "PASS" else (f"unexpected_http_status:{http_status}",),
        url=target.url,
        http_status=http_status,
    )


def certify_targets(
    targets: tuple[CertificationTarget, ...],
    *,
    live_enabled: bool,
    network_enabled: bool,
) -> tuple[CertificationResult, ...]:
    seen = {target.portal_id for target in targets}
    results = [
        certify_target(target, live_enabled=live_enabled, network_enabled=network_enabled)
        for target in targets
    ]
    for portal_id in TARGET_PORTAL_IDS:
        if portal_id not in seen:
            results.append(
                CertificationResult(
                    portal_id=portal_id,
                    status="BLOCKED",
                    checks=(),
                    blockers=("portal_missing_from_target_file",),
                )
            )
    return tuple(results)


def report_payload(results: tuple[CertificationResult, ...]) -> dict[str, object]:
    totals = {
        "pass": sum(1 for result in results if result.status == "PASS"),
        "blocked": sum(1 for result in results if result.status == "BLOCKED"),
        "fail": sum(1 for result in results if result.status == "FAIL"),
    }
    return {
        "report_type": "LIVE_PORTAL_CERTIFICATION",
        "truthfulness_policy": "PASS only means the configured live URL was reachable and mapped to a gated adapter plan. It is not proof of successful submission.",
        "totals": totals,
        "results": [result.to_dict() for result in sorted(results, key=lambda item: item.portal_id)],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run Applyocalypse live portal certification readiness checks.")
    parser.add_argument("--targets", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--network", action="store_true", help="Perform a read-only network probe for each configured live URL.")
    args = parser.parse_args(argv)

    live_enabled = os.environ.get("APPLYO_LIVE_CERTIFICATION") == "1"
    results = certify_targets(load_targets(args.targets), live_enabled=live_enabled, network_enabled=bool(args.network))
    payload = report_payload(results)
    rendered = json.dumps(payload, indent=2, sort_keys=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    else:
        print(rendered)
    return 1 if any(result.status == "FAIL" for result in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
