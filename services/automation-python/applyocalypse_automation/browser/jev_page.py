"""The page as Jev sees it: numbered interactive elements, with personal data removed.

The element walk follows jev-browser's page script (MIT, Ying-Kai Liao): every
visible interactive element, through open shadow roots, numbered in DOM order
and tagged with `data-applyo-jev` so an action can find it again.

Jev only picks what to click and classifies the page; the answer engine fills
fields. So no field value ever leaves the machine: a field is sent as filled or
empty, and the user's own details are cut out of the visible page text.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

JEV_INDEX_ATTRIBUTE = "data-applyo-jev"
PAGE_TEXT_LIMIT = 2500
REDACTED = "[redacted]"
MIN_PERSONAL_VALUE_LENGTH = 3

# Runs in each frame with the first free index; returns that frame's elements.
ENUMERATE_ELEMENTS_JS = r"""
(start) => {
  const ATTR = "data-applyo-jev";
  const SEL = [
    "a[href]", "button", "input:not([type=hidden])", "select", "textarea", "summary",
    "[role=button]", "[role=link]", "[role=menuitem]", "[role=tab]", "[role=checkbox]",
    "[role=radio]", "[role=switch]", "[role=option]", "[role=combobox]", "[role=textbox]",
    "[contenteditable=''], [contenteditable=true]", "[onclick]", "[tabindex]:not([tabindex='-1'])",
  ].join(",");
  const clean = (s, n = 80) => String(s || "").replace(/\s+/g, " ").trim().slice(0, n);
  const out = [];
  let i = start;
  const walk = (root) => {
    for (const el of root.querySelectorAll("*")) {
      if (el.shadowRoot) walk(el.shadowRoot);
      if (el.hasAttribute(ATTR)) el.removeAttribute(ATTR);
      if (!el.matches(SEL) || el.closest("[aria-hidden=true], [inert]")) continue;
      const style = getComputedStyle(el);
      const rect = el.getBoundingClientRect();
      const type = (el.getAttribute("type") || "text").toLowerCase();
      const isFile = el.tagName === "INPUT" && type === "file";
      const visible = rect.width >= 1 && rect.height >= 1 && style.visibility !== "hidden"
        && style.display !== "none";
      if (!visible && !isFile) continue;
      const role = el.getAttribute("role");
      const tagName = el.tagName.toLowerCase();
      const tag = tagName === "input" ? `input:${type}`
        : role && !["a", "button", "select", "textarea"].includes(tagName) ? `${tagName}[${role}]` : tagName;
      const field = ["input", "select", "textarea"].includes(tagName)
        || ["textbox", "combobox", "checkbox", "radio", "switch"].includes(role || "") || el.isContentEditable;
      const labelled = (el.getAttribute("aria-labelledby") || "").split(/\s+/)
        .map((id) => id && el.ownerDocument.getElementById(id)).filter(Boolean)
        .map((n) => n.innerText).join(" ");
      const label = clean(labelled || [...(el.labels || [])].map((l) => l.innerText).join(" ")
        || el.getAttribute("aria-label"));
      const choice = type === "checkbox" || type === "radio" || ["checkbox", "radio", "switch"].includes(role || "");
      const filled = choice
        ? Boolean(el.checked || el.getAttribute("aria-checked") === "true")
        : Boolean(tagName === "select" ? el.selectedIndex > 0 : (el.value ?? el.innerText ?? "").trim());
      let href = "";
      if (tagName === "a" && el.href && !el.href.startsWith("javascript:")) {
        try { const u = new URL(el.href); href = clean(u.origin === location.origin ? u.pathname : u.origin + u.pathname); }
        catch (e) { href = ""; }
      }
      el.setAttribute(ATTR, String(i));
      out.push({
        i: i++, tag, field,
        label,
        text: field && !["submit", "button", "reset"].includes(type) ? "" : clean(el.innerText || el.value || el.title),
        placeholder: clean(el.getAttribute("placeholder"), 60),
        filled: field ? filled : null,
        required: Boolean(el.required || el.getAttribute("aria-required") === "true"),
        disabled: Boolean(el.disabled || el.getAttribute("aria-disabled") === "true"),
        expanded: el.hasAttribute("aria-expanded") ? el.getAttribute("aria-expanded") === "true" : null,
        options: tagName === "select" ? [...el.options].slice(0, 25).map((o) => clean(o.text, 30)) : [],
        href,
        hidden: !visible,
      });
    }
  };
  walk(document);
  const dialogs = [...document.querySelectorAll("dialog[open], [role=dialog], [role=alertdialog], [aria-modal=true]")]
    .filter((d) => d.getBoundingClientRect().height > 0).map((d) => clean(d.innerText, 400));
  return { url: location.href, title: document.title, text: clean(document.body?.innerText, 2500),
           dialogs, elements: out, next: i };
}
"""


@dataclass(frozen=True, slots=True)
class JevElement:
    index: int
    tag: str
    is_field: bool
    label: str
    text: str
    placeholder: str
    filled: bool | None
    required: bool
    disabled: bool
    expanded: bool | None
    options: tuple[str, ...]
    href: str
    hidden: bool
    frame_url: str = ""

    @property
    def name(self) -> str:
        return self.label or self.text or self.placeholder or self.href or self.tag

    @property
    def is_password(self) -> bool:
        return self.tag == "input:password"


@dataclass(frozen=True, slots=True)
class JevPage:
    url: str
    title: str
    text: str
    dialogs: tuple[str, ...]
    elements: tuple[JevElement, ...]

    def element(self, index: int) -> JevElement | None:
        return next((element for element in self.elements if element.index == index), None)

    def fingerprint(self) -> str:
        """Stable identity of what the page shows, for spotting a loop that makes no progress."""
        return json.dumps(
            [self.url, self.text, [(e.index, e.name, e.filled) for e in self.elements]],
            ensure_ascii=False,
        )


def page_from_frames(frames: list[tuple[str, dict[str, Any]]]) -> JevPage:
    """Combine per-frame enumeration results; the first entry is the main frame."""
    main_url, main = frames[0]
    elements: list[JevElement] = []
    for frame_url, raw in frames:
        frame_label = "" if frame_url == main_url else frame_url
        for item in raw.get("elements") or []:
            elements.append(_element(item, frame_label))
    return JevPage(
        url=str(main.get("url") or main_url),
        title=str(main.get("title") or ""),
        text=str(main.get("text") or "")[:PAGE_TEXT_LIMIT],
        dialogs=tuple(str(d) for d in main.get("dialogs") or []),
        elements=tuple(elements),
    )


def _element(item: dict[str, Any], frame_url: str) -> JevElement:
    filled = item.get("filled")
    expanded = item.get("expanded")
    return JevElement(
        index=int(item["i"]),
        tag=str(item.get("tag") or ""),
        is_field=bool(item.get("field")),
        label=str(item.get("label") or ""),
        text=str(item.get("text") or ""),
        placeholder=str(item.get("placeholder") or ""),
        filled=None if filled is None else bool(filled),
        required=bool(item.get("required")),
        disabled=bool(item.get("disabled")),
        expanded=None if expanded is None else bool(expanded),
        options=tuple(str(o) for o in item.get("options") or []),
        href=str(item.get("href") or ""),
        hidden=bool(item.get("hidden")),
        frame_url=frame_url,
    )


def redact_text(text: str, personal_values: list[str]) -> str:
    """Cut the user's own details (name, email, phone, address...) out of page text."""
    values = sorted(
        {v.strip() for v in personal_values if len(v.strip()) >= MIN_PERSONAL_VALUE_LENGTH},
        key=len,
        reverse=True,
    )
    for value in values:
        text = re.sub(re.escape(value), REDACTED, text, flags=re.IGNORECASE)
    return text


def jev_state(page: JevPage, personal_values: list[str]) -> str:
    """The state string sent to Jev. Fields carry filled/empty only, never a value."""
    lines = [
        f"url: {_strip_query(page.url)}",
        f"title: {redact_text(page.title, personal_values)}",
    ]
    if page.dialogs:
        lines.append("dialogs: " + " || ".join(redact_text(d, personal_values) for d in page.dialogs))
    lines.append(f"visible text: {redact_text(page.text, personal_values)}")
    lines.append(f"elements ({len(page.elements)}):")
    lines.extend(_element_line(element, personal_values) for element in page.elements)
    return "\n".join(lines)


def _element_line(element: JevElement, personal_values: list[str]) -> str:
    parts = [f"[{element.index}] {element.tag}"]
    for key, value in (("label", element.label), ("text", element.text), ("placeholder", element.placeholder)):
        if value:
            parts.append(f'{key}="{redact_text(value, personal_values)}"')
    if element.is_field and element.filled is not None:
        parts.append("filled" if element.filled else "empty")
    if element.options:
        shown = ", ".join(element.options[:8]) + (", ..." if len(element.options) > 8 else "")
        parts.append(f"options=[{shown}]")
    for flag in ("required", "disabled", "hidden"):
        if getattr(element, flag):
            parts.append(flag)
    if element.expanded is not None:
        parts.append(f"expanded={str(element.expanded).lower()}")
    if element.href:
        parts.append(f"href={element.href}")
    if element.frame_url:
        parts.append(f"frame={_strip_query(element.frame_url)}")
    return " ".join(parts)


def _strip_query(url: str) -> str:
    """Query strings can carry emails or tokens; Jev only needs the path."""
    return url.split("?", 1)[0].split("#", 1)[0]
