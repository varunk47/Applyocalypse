from __future__ import annotations

from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Any

from .adapter import BrowserBlocker, BrowserField
from .field_detection import ControlCandidate, choose_safe_click_target, fields_from_dom_snapshot
from .portal_state import PortalPageState, classify_portal_page_state
from .portal_workflows import PortalWorkflow, workflow_for_url


@dataclass(frozen=True, slots=True)
class PortalReplayAnalysis:
    url: str
    workflow: PortalWorkflow
    page_state: PortalPageState
    fields: tuple[BrowserField, ...]
    controls: tuple[ControlCandidate, ...]
    blockers: tuple[BrowserBlocker, ...]


class _PortalHtmlParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title_parts: list[str] = []
        self.text_parts: list[str] = []
        self.raw_fields: list[dict[str, Any]] = []
        self.controls: list[ControlCandidate] = []
        self._label_stack: list[dict[str, Any]] = []
        self._control_stack: list[dict[str, Any]] = []
        self._title_depth = 0
        self._label_by_for: dict[str, str] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_map = {key.lower(): value for key, value in attrs}
        tag_name = tag.lower()
        if tag_name == "title":
            self._title_depth += 1
        if tag_name == "label":
            self._label_stack.append({"for": attrs_map.get("for"), "text": []})
        if tag_name in {"button", "a"} or attrs_map.get("role") == "button":
            self._control_stack.append(
                {
                    "tag_name": tag_name,
                    "href": attrs_map.get("href"),
                    "text": [attrs_map.get("aria-label") or attrs_map.get("title") or ""],
                }
            )
        if tag_name == "input" and (attrs_map.get("type") or "text").lower() in {"button", "submit"}:
            self.controls.append(
                ControlCandidate(
                    label=(attrs_map.get("value") or attrs_map.get("aria-label") or "").strip(),
                    tag_name="input",
                    href=None,
                    visible=not self._is_hidden(attrs_map),
                )
            )
        if tag_name in {"input", "textarea", "select"}:
            field_type = (attrs_map.get("type") or "text").lower() if tag_name == "input" else tag_name
            if field_type in {"hidden", "submit", "button", "image", "reset"}:
                return
            self.raw_fields.append(
                {
                    "label": attrs_map.get("aria-label") or attrs_map.get("placeholder") or attrs_map.get("name") or attrs_map.get("id") or "",
                    "field_type": field_type,
                    "selector": self._selector_for(tag_name, attrs_map, field_type),
                    "required": "required" in attrs_map or attrs_map.get("aria-required") == "true",
                    "metadata": {
                        "tag_name": tag_name,
                        "accept": attrs_map.get("accept"),
                        "autocomplete": attrs_map.get("autocomplete"),
                        "id": attrs_map.get("id"),
                        "name": attrs_map.get("name"),
                        "placeholder": attrs_map.get("placeholder"),
                        "file_count": None,
                        "value": attrs_map.get("value") if field_type in {"checkbox", "radio"} else None,
                        "checked": "checked" in attrs_map if field_type in {"checkbox", "radio"} else None,
                        "options": [],
                    },
                }
            )

    def handle_data(self, data: str) -> None:
        if not data.strip():
            return
        if self._title_depth > 0:
            self.title_parts.append(data.strip())
        self.text_parts.append(data.strip())
        if self._label_stack:
            self._label_stack[-1]["text"].append(data.strip())
        if self._control_stack:
            self._control_stack[-1]["text"].append(data.strip())

    def handle_endtag(self, tag: str) -> None:
        tag_name = tag.lower()
        if tag_name == "title" and self._title_depth > 0:
            self._title_depth -= 1
        if tag_name == "label" and self._label_stack:
            label = self._label_stack.pop()
            target_id = label.get("for")
            text = " ".join(label["text"]).strip()
            if target_id and text:
                self._label_by_for[str(target_id)] = text
        if tag_name in {"button", "a"} and self._control_stack:
            control = self._control_stack.pop()
            text = " ".join(part for part in control["text"] if part).strip()
            if text:
                self.controls.append(
                    ControlCandidate(
                        label=text,
                        tag_name=str(control["tag_name"]),
                        href=str(control["href"]) if control.get("href") else None,
                    )
                )

    def finalize_fields(self) -> list[dict[str, Any]]:
        finalized: list[dict[str, Any]] = []
        for raw_field in self.raw_fields:
            metadata = raw_field.get("metadata") if isinstance(raw_field.get("metadata"), dict) else {}
            field_id = metadata.get("id")
            label = self._label_by_for.get(str(field_id), "") if field_id else ""
            finalized.append({**raw_field, "label": label or str(raw_field.get("label") or "Unlabeled field")})
        return finalized

    @staticmethod
    def _selector_for(tag_name: str, attrs_map: dict[str, str | None], field_type: str) -> str | None:
        element_id = attrs_map.get("id")
        if element_id:
            return f"#{element_id}"
        name = attrs_map.get("name")
        if not name:
            return None
        value = attrs_map.get("value")
        if field_type in {"radio", "checkbox"} and value:
            return f'{tag_name}[name="{name}"][value="{value}"]'
        return f'{tag_name}[name="{name}"]'

    @staticmethod
    def _is_hidden(attrs_map: dict[str, str | None]) -> bool:
        style = (attrs_map.get("style") or "").lower()
        return "display:none" in style.replace(" ", "") or "visibility:hidden" in style.replace(" ", "")


def analyze_portal_html_fixture(url: str, html: str) -> PortalReplayAnalysis:
    parser = _PortalHtmlParser()
    parser.feed(html)
    fields = tuple(fields_from_dom_snapshot(parser.finalize_fields()))
    workflow = workflow_for_url(url)
    title = " ".join(parser.title_parts).strip()
    text = "\n".join(parser.text_parts)
    page_state = classify_portal_page_state(
        workflow=workflow,
        original_url=url,
        current_url=url,
        title=title,
        text=text,
        field_count=len(fields),
    )
    return PortalReplayAnalysis(
        url=url,
        workflow=workflow,
        page_state=page_state,
        fields=fields,
        controls=tuple(parser.controls),
        blockers=tuple(_blockers_from_replay_text(text, fields)),
    )


def choose_entry_action_for_fixture(analysis: PortalReplayAnalysis):
    return choose_safe_click_target(list(analysis.workflow.entry_action_labels), list(analysis.controls))


def _blockers_from_replay_text(text: str, fields: tuple[BrowserField, ...]) -> list[BrowserBlocker]:
    normalized = " ".join(text.lower().split())
    blockers: list[BrowserBlocker] = []
    # Only an ACTIVE challenge blocks the run. A passive "protected by reCAPTCHA"
    # notice (present on most application forms) must not pause automation — this
    # mirrors the visibility-gated detection in DOM_BLOCKER_DISCOVERY_SCRIPT.
    captcha_challenge_phrases = (
        "i'm not a robot",
        "i am not a robot",
        "verify you are human",
        "verify you're human",
        "are you human",
        "select all images",
        "select each image",
        "complete the captcha",
        "solve the captcha",
        "checking your browser before",
        "just a moment",
        "press and hold",
    )
    if any(phrase in normalized for phrase in captcha_challenge_phrases):
        blockers.append(BrowserBlocker("CAPTCHA", "Interactive CAPTCHA or bot challenge detected", 0.9))
    if "multi-factor" in normalized or "multifactor" in normalized or "authenticator app" in normalized or " mfa " in f" {normalized} ":
        blockers.append(BrowserBlocker("MFA", "Multi-factor authentication detected", 0.82))
    if "one-time code" in normalized or "one time code" in normalized or "verification code" in normalized or " otp " in f" {normalized} ":
        blockers.append(BrowserBlocker("OTP", "One-time passcode challenge detected", 0.8))
    password_fields = [field for field in fields if field.field_type == "password"]
    if password_fields or (("sign in" in normalized or "log in" in normalized or "login" in normalized) and "password" in normalized):
        blockers.append(BrowserBlocker("LOGIN", "Login or account creation page detected", 0.9 if password_fields else 0.74))
    sensitive_patterns = {
        "work_authorization": ("legally authorized", "work authorization", "authorized to work"),
        "sponsorship": ("require sponsorship", "need sponsorship", "visa sponsorship", "sponsor now or in the future"),
        "security_clearance": ("security clearance", "active clearance", "clearance level"),
        "compensation": ("salary expectation", "desired salary", "desired compensation", "compensation expectation"),
        "relocation": ("willing to relocate", "relocation assistance", "relocate for this role"),
        "eeo": ("voluntary self-identification", "veteran status", "disability status", "race/ethnicity", "gender identity"),
    }
    matched_sensitive = [key for key, phrases in sensitive_patterns.items() if any(phrase in normalized for phrase in phrases)]
    if matched_sensitive:
        blockers.append(
            BrowserBlocker(
                "AMBIGUOUS_QUESTION",
                "Sensitive or ambiguous application question detected",
                0.86,
                {"matched_patterns": matched_sensitive[:8]},
            )
        )
    return blockers
