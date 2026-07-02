from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse

from .portal_registry import detect_portal
from .portal_workflows import PortalWorkflow

ATS_PORTAL_IDS = {"workday", "greenhouse", "lever", "ashby", "icims", "taleo", "governmentjobs", "usajobs", "ncs"}
APPLICATION_TERMS = (
    "application",
    "apply",
    "resume",
    "cover letter",
    "work authorization",
    "candidate",
    "submit your application",
)


@dataclass(frozen=True, slots=True)
class PortalPageState:
    original_url: str
    current_url: str | None
    original_portal_id: str
    current_portal_id: str | None
    host_changed: bool
    portal_changed: bool
    likely_application_surface: bool
    confidence: float
    requires_review: bool
    signals: tuple[str, ...]
    field_count: int | None

    def to_event_payload(self) -> dict[str, object]:
        return {
            "original_url": self.original_url,
            "current_url": self.current_url,
            "original_portal_id": self.original_portal_id,
            "current_portal_id": self.current_portal_id,
            "host_changed": self.host_changed,
            "portal_changed": self.portal_changed,
            "likely_application_surface": self.likely_application_surface,
            "confidence": self.confidence,
            "requires_review": self.requires_review,
            "signals": list(self.signals),
            "field_count": self.field_count,
        }


def _host(value: str | None) -> str | None:
    if not value:
        return None
    return urlparse(value).hostname


def classify_portal_page_state(
    *,
    workflow: PortalWorkflow,
    original_url: str,
    current_url: str | None,
    title: str | None,
    text: str | None,
    field_count: int | None = None,
) -> PortalPageState:
    current_portal = detect_portal(current_url or "") if current_url else None
    original_host = _host(original_url)
    current_host = _host(current_url)
    host_changed = bool(original_host and current_host and original_host.lower() != current_host.lower())
    current_portal_id = current_portal.portal_id if current_portal else None
    portal_changed = bool(current_portal_id and current_portal_id != workflow.portal_id)
    normalized_text = " ".join(f"{title or ''} {text or ''}".lower().split())[:12000]

    signals: list[str] = []
    if host_changed:
        signals.append("host_changed")
    if portal_changed:
        signals.append("portal_changed")
    if current_portal_id in ATS_PORTAL_IDS:
        signals.append("known_ats_surface")
    if field_count is not None and field_count >= 3:
        signals.append("multiple_fields_detected")
    matched_terms = [term for term in APPLICATION_TERMS if term in normalized_text]
    if matched_terms:
        signals.extend(f"term:{term}" for term in matched_terms[:4])

    likely_application_surface = (
        current_portal_id in ATS_PORTAL_IDS
        or (field_count is not None and field_count >= 3)
        or len(matched_terms) >= 2
        or "submit your application" in matched_terms
    )
    confidence = min(
        1.0,
        0.25
        + (0.25 if current_portal_id in ATS_PORTAL_IDS else 0)
        + (0.2 if host_changed or portal_changed else 0)
        + (0.2 if field_count is not None and field_count >= 3 else 0)
        + min(0.2, len(matched_terms) * 0.05),
    )
    requires_review = workflow.requires_external_redirect_watch and not host_changed and not likely_application_surface

    return PortalPageState(
        original_url=original_url,
        current_url=current_url,
        original_portal_id=workflow.portal_id,
        current_portal_id=current_portal_id,
        host_changed=host_changed,
        portal_changed=portal_changed,
        likely_application_surface=likely_application_surface,
        confidence=round(confidence, 3),
        requires_review=requires_review,
        signals=tuple(signals),
        field_count=field_count,
    )
