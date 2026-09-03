from __future__ import annotations

import re
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Any

from .adapter import BrowserBlocker, BrowserField
from .field_detection import (
    CAPTCHA_CHALLENGE_PHRASES,
    CAPTCHA_INTERSTITIAL_PHRASES,
    ControlCandidate,
    choose_safe_click_target,
    fields_from_dom_snapshot,
    resolve_field_label,
)
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


# Both of these mirror the injected discovery script in field_detection. A control
# this twin reports and the browser does not is a phantom question: the offline
# fixture tests would assert an answer for something no user will ever be asked.
_NATIVE_FIELD_TAGS = frozenset({"input", "textarea", "select"})
_SKIPPED_INPUT_TYPES = frozenset({"hidden", "submit", "button", "image", "reset", "search"})
_CAPTCHA_NAME_RE = re.compile(r"recaptcha|captcha|turnstile")


# `html.parser` never emits an end tag for these, so they never open a frame.
_VOID_TAGS = frozenset(
    {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}
)


class _PortalHtmlParser(HTMLParser):
    """Offline twin of the injected DOM discovery script.

    The label chain here MUST match ``LABEL_RESOLUTION_JS`` in
    ``field_detection.py``; both call :func:`resolve_field_label` with the same
    source names, and ``tests/test_label_resolution.py`` pins them together.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title_parts: list[str] = []
        self.text_parts: list[str] = []
        self.raw_fields: list[dict[str, Any]] = []
        self.controls: list[ControlCandidate] = []
        self._frames: list[dict[str, Any]] = []
        self._control_stack: list[dict[str, Any]] = []
        self._title_depth = 0
        self._next_frame_uid = 0
        self._aria_stack: list[dict[str, Any]] = []
        self._aria_option_stack: list[dict[str, Any]] = []
        self._label_by_for: dict[str, str] = {}
        self._label_text_by_uid: dict[int, str] = {}
        self._legend_by_fieldset_uid: dict[int, str] = {}
        self._text_by_id: dict[str, str] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_map = {key.lower(): value for key, value in attrs}
        tag_name = tag.lower()
        if tag_name == "title":
            self._title_depth += 1
        if tag_name not in _VOID_TAGS:
            self._next_frame_uid += 1
            self._frames.append(
                {
                    "uid": self._next_frame_uid,
                    "tag": tag_name,
                    "id": attrs_map.get("id"),
                    "for": attrs_map.get("for"),
                    "editable": self._is_rich_text_host(attrs_map),
                    "text": [],
                }
            )
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
        widget_role = self._aria_widget_role(attrs_map)
        if widget_role is not None and not self._is_captcha_control(attrs_map):
            # Mirrors the ARIA sweep in ``field_detection.py``: a picker built from
            # divs owns no value the browser can set, and an <input role="combobox">
            # must NOT fall through to the plain-text path below or a write would
            # read its own text back as proof (audit finding F9). Nested options are
            # collected here; options a widget only references via aria-controls are
            # resolved live, where the popup container actually exists.
            self._aria_stack.append(
                {
                    "uid": None if tag_name in _VOID_TAGS else self._next_frame_uid,
                    "index": len(self.raw_fields),
                }
            )
            self.raw_fields.append(
                {
                    "_label_attrs": {
                        "aria_label": attrs_map.get("aria-label") or "",
                        "title": attrs_map.get("title") or "",
                        "placeholder": attrs_map.get("placeholder") or "",
                        "name_or_id": attrs_map.get("name") or attrs_map.get("id") or "",
                    },
                    "_aria_labelledby": attrs_map.get("aria-labelledby") or "",
                    "_label_frame_uid": self._enclosing_uid("label"),
                    "_fieldset_uid": self._enclosing_uid("fieldset"),
                    "field_type": f"aria_{widget_role}",
                    "selector": self._aria_selector_for(tag_name, attrs_map),
                    "required": attrs_map.get("aria-required") == "true" or "required" in attrs_map,
                    "metadata": {
                        "tag_name": tag_name,
                        "aria_role": widget_role,
                        "aria_expanded": attrs_map.get("aria-expanded"),
                        "automation_id": attrs_map.get("data-automation-id"),
                        "id": attrs_map.get("id"),
                        "name": attrs_map.get("name"),
                        "placeholder": attrs_map.get("placeholder"),
                        "options_rendered": False,
                        "options": [],
                    },
                }
            )
            return
        if self._aria_stack and (attrs_map.get("role") or "").lower() in {"option", "radio"}:
            self._aria_option_stack.append(
                {
                    "uid": None if tag_name in _VOID_TAGS else self._next_frame_uid,
                    "widget_index": self._aria_stack[-1]["index"],
                    "text": [attrs_map.get("aria-label") or ""],
                    "value": attrs_map.get("data-value") or attrs_map.get("value") or "",
                    "selected": attrs_map.get("aria-selected") == "true"
                    or attrs_map.get("aria-checked") == "true",
                    "disabled": attrs_map.get("aria-disabled") == "true",
                }
            )
            return
        if self._is_rich_text_host(attrs_map) and tag_name not in _NATIVE_FIELD_TAGS | _VOID_TAGS:
            # Mirrors the contenteditable sweep in ``field_detection.py``. Quill,
            # ProseMirror, TipTap and Lexical all render their editing surface as a
            # styled div, so the branch below cannot see one and a required long-form
            # question leaves a form that reads as having nothing missing.
            #
            # ``self._frames`` already holds this element, so the ancestors are
            # everything before it; skipping when one of them is editable is how
            # ``parentElement.closest()`` behaves in the real script. Where editable
            # regions genuinely nest, the outer one is the surface a person types into.
            if not any(bool(frame.get("editable")) for frame in self._frames[:-1]):
                self.raw_fields.append(
                    {
                        "_label_attrs": {
                            "aria_label": attrs_map.get("aria-label") or "",
                            "title": attrs_map.get("title") or "",
                            "placeholder": attrs_map.get("placeholder") or "",
                            "name_or_id": attrs_map.get("name") or attrs_map.get("id") or "",
                        },
                        "_aria_labelledby": attrs_map.get("aria-labelledby") or "",
                        "_label_frame_uid": self._enclosing_uid("label"),
                        "_fieldset_uid": self._enclosing_uid("fieldset"),
                        "field_type": "richtext",
                        "selector": self._rich_text_selector_for(tag_name, attrs_map),
                        "required": attrs_map.get("aria-required") == "true" or "required" in attrs_map,
                        "metadata": {
                            "tag_name": tag_name,
                            "id": attrs_map.get("id"),
                            "name": attrs_map.get("name"),
                            "aria_role": attrs_map.get("role"),
                            "current_length": 0,
                        },
                    }
                )
            return
        if tag_name in {"input", "textarea", "select"}:
            field_type = (attrs_map.get("type") or "text").lower() if tag_name == "input" else tag_name
            if field_type in _SKIPPED_INPUT_TYPES or self._is_captcha_control(attrs_map):
                return
            self.raw_fields.append(
                {
                    "_label_attrs": {
                        "aria_label": attrs_map.get("aria-label") or "",
                        "title": attrs_map.get("title") or "",
                        "placeholder": attrs_map.get("placeholder") or "",
                        "name_or_id": attrs_map.get("name") or attrs_map.get("id") or "",
                    },
                    "_aria_labelledby": attrs_map.get("aria-labelledby") or "",
                    "_label_frame_uid": self._enclosing_uid("label"),
                    "_fieldset_uid": self._enclosing_uid("fieldset"),
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

    @staticmethod
    def _aria_widget_role(attrs_map: dict[str, str | None]) -> str | None:
        role = (attrs_map.get("role") or "").lower()
        if role in {"combobox", "listbox", "radiogroup"}:
            return role
        # Workday wires its pickers to a popup listbox instead of declaring a role.
        if "aria-haspopup" in attrs_map and "data-automation-id" in attrs_map:
            return "combobox"
        return None

    @staticmethod
    def _aria_selector_for(tag_name: str, attrs_map: dict[str, str | None]) -> str | None:
        element_id = attrs_map.get("id")
        if element_id:
            return f"#{element_id}"
        automation_id = attrs_map.get("data-automation-id")
        if automation_id:
            return f'[data-automation-id="{automation_id}"]'
        name = attrs_map.get("name")
        if not name:
            return None
        return f'{tag_name}[name="{name}"]'

    @staticmethod
    def _is_rich_text_host(attrs_map: dict[str, str | None]) -> bool:
        if "contenteditable" not in attrs_map:
            return False
        return (attrs_map.get("contenteditable") or "").lower() in {"", "true", "plaintext-only"}

    @classmethod
    def _rich_text_selector_for(cls, tag_name: str, attrs_map: dict[str, str | None]) -> str | None:
        """A rich-text host is usually a bare styled div with no id and no name.

        ``aria-label`` is how these actually get named, so it is the fallback the
        real script reaches for. That script also requires the selector to match
        exactly one element; a streaming parser holds no document to ask, so the
        twin can only agree about markup where the question does not arise.
        """
        direct = cls._aria_selector_for(tag_name, attrs_map)
        if direct:
            return direct
        for attribute in ("aria-label", "data-testid", "aria-labelledby"):
            value = attrs_map.get(attribute)
            if value:
                return f'{tag_name}[{attribute}="{value}"]'
        return None

    def _enclosing_uid(self, tag_name: str) -> int | None:
        for frame in reversed(self._frames):
            if frame["tag"] == tag_name:
                return int(frame["uid"])
        return None

    def _record_frame(self, frame: dict[str, Any]) -> None:
        text = " ".join(str(part) for part in frame["text"]).strip()
        if not text:
            return
        uid = int(frame["uid"])
        frame_id = frame.get("id")
        if frame_id:
            self._text_by_id.setdefault(str(frame_id), text)
        if frame["tag"] == "label":
            self._label_text_by_uid.setdefault(uid, text)
            target_id = frame.get("for")
            if target_id:
                self._label_by_for.setdefault(str(target_id), text)
        elif frame["tag"] == "legend":
            fieldset_uid = self._enclosing_uid("fieldset")
            if fieldset_uid is not None:
                self._legend_by_fieldset_uid.setdefault(fieldset_uid, text)

    def _close_frame(self, tag_name: str) -> None:
        index = next(
            (position for position in range(len(self._frames) - 1, -1, -1) if self._frames[position]["tag"] == tag_name),
            None,
        )
        if index is None:
            return
        closed = self._frames[index:]
        self._frames = self._frames[:index]
        for frame in reversed(closed):
            self._record_frame(frame)

    def handle_data(self, data: str) -> None:
        if not data.strip():
            return
        if self._title_depth > 0:
            self.title_parts.append(data.strip())
        self.text_parts.append(data.strip())
        for frame in self._frames:
            frame["text"].append(data.strip())
        if self._control_stack:
            self._control_stack[-1]["text"].append(data.strip())
        if self._aria_option_stack:
            self._aria_option_stack[-1]["text"].append(data.strip())

    def handle_endtag(self, tag: str) -> None:
        tag_name = tag.lower()
        if tag_name == "title" and self._title_depth > 0:
            self._title_depth -= 1
        if tag_name not in _VOID_TAGS:
            self._close_frame(tag_name)
        # Close ARIA widgets and their options off the frame lifecycle rather than by
        # tag name, so a plain <div> wrapper inside a listbox cannot end the widget.
        live_uids = {int(frame["uid"]) for frame in self._frames}
        while self._aria_option_stack and self._aria_option_stack[-1]["uid"] not in live_uids:
            option = self._aria_option_stack.pop()
            metadata = self.raw_fields[int(option["widget_index"])]["metadata"]
            metadata["options"].append(
                {
                    "value": option["value"],
                    "label": " ".join(part for part in option["text"] if part).strip(),
                    "selected": option["selected"],
                    "disabled": option["disabled"],
                }
            )
            metadata["options_rendered"] = True
        while self._aria_stack and self._aria_stack[-1]["uid"] not in live_uids:
            self._aria_stack.pop()
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
        # Close anything the document left open so trailing text still counts.
        for frame in reversed(self._frames):
            self._record_frame(frame)
        self._frames = []
        finalized: list[dict[str, Any]] = []
        for raw_field in self.raw_fields:
            metadata = raw_field.get("metadata") if isinstance(raw_field.get("metadata"), dict) else {}
            field_id = metadata.get("id")
            attrs = raw_field.get("_label_attrs") or {}
            label_frame_uid = raw_field.get("_label_frame_uid")
            fieldset_uid = raw_field.get("_fieldset_uid")
            references = str(raw_field.get("_aria_labelledby") or "").split()
            sources = {
                "label_for": self._label_by_for.get(str(field_id), "") if field_id else "",
                "wrapping_label": self._label_text_by_uid.get(label_frame_uid, "") if label_frame_uid else "",
                "aria_labelledby": " ".join(
                    text for text in (self._text_by_id.get(reference, "") for reference in references) if text
                ),
                "aria_label": attrs.get("aria_label", ""),
                "legend": self._legend_by_fieldset_uid.get(fieldset_uid, "") if fieldset_uid else "",
                "title": attrs.get("title", ""),
                "placeholder": attrs.get("placeholder", ""),
                "name_or_id": attrs.get("name_or_id", ""),
            }
            label, label_source, synthetic = resolve_field_label(sources)
            public = {key: value for key, value in raw_field.items() if not key.startswith("_")}
            finalized.append(
                {**public, "label": label, "label_source": label_source, "label_synthetic": synthetic}
            )
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
    def _is_captcha_control(attrs_map: dict[str, str | None]) -> bool:
        """A challenge is never an application question, however it is labelled."""
        name_id = f"{attrs_map.get('name') or ''} {attrs_map.get('id') or ''}".lower()
        return _CAPTCHA_NAME_RE.search(name_id) is not None

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
    captcha_challenge_phrases = CAPTCHA_CHALLENGE_PHRASES + CAPTCHA_INTERSTITIAL_PHRASES
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
