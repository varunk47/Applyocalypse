from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from .adapter import BrowserBlocker, BrowserField, BrowserStepResult


@dataclass(frozen=True, slots=True)
class FrameRef:
    """Where a field lives when the portal serves its form from an iframe.

    Greenhouse embeds grnhse_iframe from job-boards.greenhouse.io onto an employer
    domain, so the form is a cross-origin document: injected JS cannot reach it by
    walking iframe.contentDocument, and a write aimed at the top document lands
    nowhere while still looking like it succeeded. The adapter has to address the
    frame directly, which means each field must remember where it came from.
    """

    url: str
    index: int


# Frames that never hold application questions. The CAPTCHA widgets matter most:
# they really do contain inputs, so scanning them would hand the model a challenge
# box to answer. The rest are analytics, chat and media frames that only add noise.
_NON_FORM_FRAME_URL_RE = re.compile(
    r"recaptcha|hcaptcha|turnstile|challenges\.cloudflare\.com|googletagmanager|"
    r"google-analytics|doubleclick|googlesyndication|facebook\.com/(?:tr|plugins)|"
    r"youtube\.com/embed|player\.vimeo\.com|hotjar|segment\.(?:io|com)|"
    r"intercom|drift\.com|zendesk|fullstory|mixpanel",
    re.IGNORECASE,
)


def frame_url_is_worth_scanning(url: str) -> bool:
    """Whether a subframe could plausibly hold part of the application form."""
    candidate = (url or "").strip()
    # about:blank and about:srcdoc frames are wrappers a portal fills in later;
    # there is nothing to read yet and no stable URL to address them by.
    if not candidate.startswith(("http://", "https://")):
        return False
    return _NON_FORM_FRAME_URL_RE.search(candidate) is None


@dataclass(frozen=True, slots=True)
class ControlCandidate:
    label: str
    tag_name: str
    href: str | None = None
    visible: bool = True


def normalize_control_label(value: str) -> str:
    return " ".join("".join(character.lower() if character.isalnum() else " " for character in value).split())


def is_final_submit_like(normalized_label: str) -> bool:
    forbidden = {"submit", "submit application", "send application", "finish", "complete application"}
    return (
        normalized_label in forbidden
        or normalized_label.startswith("submit ")
        or normalized_label.startswith("send ")
        or " submit application" in normalized_label
        or " send application" in normalized_label
        or " complete application" in normalized_label
        or " finish application" in normalized_label
    )


def choose_safe_click_target(labels: list[str], candidates: list[ControlCandidate]) -> BrowserStepResult:
    requested = [normalize_control_label(label) for label in labels if label.strip()]
    requested = [label for label in requested if label]
    if not requested:
        return BrowserStepResult(False, "no click labels configured", {"action": "click_by_text"})

    visible_candidates = [candidate for candidate in candidates if candidate.visible]
    matches: list[tuple[ControlCandidate, str]] = []
    for candidate in visible_candidates:
        normalized = normalize_control_label(candidate.label)
        if not normalized or is_final_submit_like(normalized):
            continue
        if any(normalized == label or normalized in label or label in normalized for label in requested):
            matches.append((candidate, normalized))

    if not matches:
        return BrowserStepResult(
            False,
            "no matching safe portal action was found",
            {"action": "click_by_text", "message": "no matching safe portal action was found", "candidate_count": len(visible_candidates)},
        )

    exact_matches = [(candidate, normalized) for candidate, normalized in matches if normalized in requested]
    preferred_matches = exact_matches if exact_matches else matches
    unique_targets = {
        f"{normalized}|{candidate.tag_name.lower()}|{candidate.href or ''}" for candidate, normalized in preferred_matches
    }
    if len(unique_targets) > 1:
        return BrowserStepResult(
            False,
            "multiple safe portal actions matched; manual review is required",
            {
                "action": "click_by_text",
                "message": "multiple safe portal actions matched; manual review is required",
                "ambiguity_code": "AMBIGUOUS_PORTAL_ACTION",
                "candidate_count": len(preferred_matches),
                "candidate_labels": [candidate.label[:160] for candidate, _ in preferred_matches if candidate.label.strip()][:8],
            },
        )

    target = preferred_matches[0][0]
    return BrowserStepResult(
        True,
        "safe portal action clicked",
        {
            "action": "click_by_text",
            "clicked_label": target.label[:160],
            "clicked_tag": target.tag_name.lower(),
            "href": target.href,
        },
    )


# --- Shared label resolution -------------------------------------------------
# The browser (injected JS below) and the offline replay of saved portal HTML
# (`html_replay.py`) MUST resolve labels identically, or the replay fixtures stop
# being evidence about what the browser actually sees. Both sides consume this
# one ordering; `tests/test_label_resolution.py` pins them to the same table.
LABEL_SOURCE_ORDER: tuple[str, ...] = (
    "label_for",
    "wrapping_label",
    "aria_labelledby",
    "aria_label",
    "legend",
    "title",
    "placeholder",
    "name_or_id",
)

# A field we could not label is surfaced under this label instead of being
# dropped, so the run pauses for a human rather than silently skipping a
# required question. The literal string is part of the runner's contract.
SYNTHETIC_LABEL = "Unlabeled field"

_MAX_LABEL_LENGTH = 240
_CAMEL_BOUNDARY = re.compile(r"([a-z0-9])([A-Z])")
_ACRONYM_BOUNDARY = re.compile(r"([A-Z]+)([A-Z][a-z])")
_NON_ALNUM = re.compile(r"[^A-Za-z0-9]+")


def humanize_identifier(raw: str) -> str:
    """Turn a machine name such as ``candidate.firstName`` into ``Candidate First Name``.

    Mirrored verbatim by ``humanizeIdentifier`` in :data:`LABEL_RESOLUTION_JS`.
    """
    source = str(raw or "")
    if not source:
        return ""
    spaced = _ACRONYM_BOUNDARY.sub(r"\1 \2", _CAMEL_BOUNDARY.sub(r"\1 \2", _NON_ALNUM.sub(" ", source)))
    tokens = [token for token in spaced.split() if token]
    return " ".join(token if token == token.upper() else token[0].upper() + token[1:] for token in tokens)


def resolve_field_label(sources: dict[str, Any] | None) -> tuple[str, str, bool]:
    """Resolve one field label from the ordered chain in :data:`LABEL_SOURCE_ORDER`.

    Returns ``(label, label_source, synthetic)``. ``synthetic`` is True only when
    every source was empty; the caller must surface the field for human review
    instead of dropping it.
    """
    for source in LABEL_SOURCE_ORDER:
        raw = (sources or {}).get(source)
        candidate = " ".join(str(raw).split()) if raw is not None else ""
        if not candidate:
            continue
        if source == "name_or_id":
            candidate = humanize_identifier(candidate)
            if not candidate:
                continue
        return candidate[:_MAX_LABEL_LENGTH], source, False
    return SYNTHETIC_LABEL, "synthetic", True


# The JavaScript twin of the three definitions above. Kept as a standalone chunk
# of `const` declarations so it can be spliced into any injected script.
LABEL_RESOLUTION_JS = r"""
const LABEL_SOURCE_ORDER = [
  'label_for', 'wrapping_label', 'aria_labelledby', 'aria_label',
  'legend', 'title', 'placeholder', 'name_or_id'
];
const SYNTHETIC_LABEL = 'Unlabeled field';
const collapseLabelWhitespace = (value) => String(value == null ? '' : value).replace(/\s+/g, ' ').trim();
const humanizeIdentifier = (raw) => {
  const source = String(raw == null ? '' : raw);
  if (!source) return '';
  return source
    .replace(/[^A-Za-z0-9]+/g, ' ')
    .replace(/([a-z0-9])([A-Z])/g, '$1 $2')
    .replace(/([A-Z]+)([A-Z][a-z])/g, '$1 $2')
    .split(/\s+/)
    .filter(Boolean)
    .map((token) => (token === token.toUpperCase() ? token : token.charAt(0).toUpperCase() + token.slice(1)))
    .join(' ');
};
const resolveLabelFromSources = (sources) => {
  for (const source of LABEL_SOURCE_ORDER) {
    let candidate = collapseLabelWhitespace(sources ? sources[source] : '');
    if (!candidate) continue;
    if (source === 'name_or_id') candidate = humanizeIdentifier(candidate);
    if (!candidate) continue;
    return { label: candidate.slice(0, 240), label_source: source, label_synthetic: false };
  }
  return { label: SYNTHETIC_LABEL, label_source: 'synthetic', label_synthetic: true };
};
const labelSourcesFor = (element) => {
  const readText = (node) => (node ? (node.innerText || node.textContent || '') : '');
  const elementId = element.getAttribute('id');
  const explicit = elementId ? document.querySelector(`label[for="${CSS.escape(elementId)}"]`) : null;
  const wrapping = element.closest ? element.closest('label') : null;
  const fieldset = element.closest ? element.closest('fieldset') : null;
  const legend = fieldset && fieldset.querySelector ? fieldset.querySelector('legend') : null;
  return {
    label_for: readText(explicit),
    wrapping_label: readText(wrapping),
    aria_labelledby: String(element.getAttribute('aria-labelledby') || '')
      .split(/\s+/)
      .filter(Boolean)
      .map((reference) => collapseLabelWhitespace(readText(document.getElementById(reference))))
      .filter(Boolean)
      .join(' '),
    aria_label: element.getAttribute('aria-label') || '',
    legend: readText(legend),
    title: element.getAttribute('title') || '',
    placeholder: element.getAttribute('placeholder') || '',
    name_or_id: element.getAttribute('name') || elementId || ''
  };
};
"""


# Field types whose value cannot simply be typed. These must go through the injected
# write script, which knows how to choose an option and check the choice actually took.
# ARIA pickers are here for a sharp reason: an <input role="combobox"> accepts a plain
# fill() and reads the typed text straight back, so a naive write would report a
# success the portal never saw (audit finding F9).
SCRIPTED_WRITE_FIELD_TYPES: frozenset[str] = frozenset(
    {"select", "checkbox", "radio", "aria_combobox", "aria_listbox", "aria_radiogroup"}
)


_FIELD_DISCOVERY_BODY_JS = r"""
  const fields = [];
  const candidates = Array.from(document.querySelectorAll('input, textarea, select'));
  const attrValue = (value) => JSON.stringify(String(value));
  const fieldType = (element) => {
    const tagName = element.tagName.toLowerCase();
    return tagName === 'input' ? (element.getAttribute('type') || 'text').toLowerCase() : tagName;
  };
  const optionsFor = (element) => {
    if (element.tagName.toLowerCase() !== 'select') return [];
    return Array.from(element.options || []).map((option) => ({
      value: option.getAttribute('value') || option.value || '',
      label: (option.textContent || '').trim(),
      selected: option.selected === true,
      disabled: option.disabled === true
    }));
  };
  const selectorFor = (element, type) => {
    const id = element.getAttribute('id');
    if (id) return `#${CSS.escape(id)}`;
    const name = element.getAttribute('name');
    if (!name) return null;
    const tag = element.tagName.toLowerCase();
    if ((type === 'radio' || type === 'checkbox') && element.getAttribute('value')) {
      return `${tag}[name=${attrValue(name)}][value=${attrValue(element.getAttribute('value'))}]`;
    }
    return `${tag}[name=${attrValue(name)}]`;
  };
  // Workday, Ashby and most React portals render every picker as a div or input
  // carrying role=combobox|listbox|radiogroup and never emit a <select>, so the
  // native sweep above is blind to them. A question we cannot see is worse than one
  // we cannot fill: the run would reach the submit gate believing a required field
  // was answered (audit finding F9).
  const ariaWidgetRoleFor = (element) => {
    const role = (element.getAttribute('role') || '').toLowerCase();
    if (role === 'combobox' || role === 'listbox' || role === 'radiogroup') return role;
    // Workday wires its pickers to a popup listbox instead of declaring a role.
    if (element.hasAttribute('aria-haspopup') && element.hasAttribute('data-automation-id')) return 'combobox';
    return null;
  };
  const ariaOptionsFor = (element, role) => {
    const containers = [];
    const owned = ((element.getAttribute('aria-controls') || '') + ' ' + (element.getAttribute('aria-owns') || '')).trim();
    for (const ownedId of owned.split(/\s+/).filter(Boolean)) {
      const container = document.getElementById(ownedId);
      if (container) containers.push(container);
    }
    // A listbox or radiogroup owns its options directly; a closed combobox owns none
    // until it is opened, which is exactly the case we must hand to a human.
    containers.push(element);
    const optionSelector = role === 'radiogroup' ? '[role="radio"]' : '[role="option"]';
    const seen = new Set();
    const options = [];
    for (const container of containers) {
      for (const option of Array.from(container.querySelectorAll(optionSelector))) {
        if (seen.has(option)) continue;
        seen.add(option);
        options.push({
          value: option.getAttribute('data-value') || option.getAttribute('value') || '',
          label: (option.textContent || '').trim(),
          selected: option.getAttribute('aria-selected') === 'true' || option.getAttribute('aria-checked') === 'true',
          disabled: option.getAttribute('aria-disabled') === 'true'
        });
      }
    }
    return options;
  };
  const ariaSelectorFor = (element) => {
    const id = element.getAttribute('id');
    if (id) return `#${CSS.escape(id)}`;
    const automationId = element.getAttribute('data-automation-id');
    if (automationId) return `[data-automation-id=${attrValue(automationId)}]`;
    const name = element.getAttribute('name');
    if (!name) return null;
    return `${element.tagName.toLowerCase()}[name=${attrValue(name)}]`;
  };
  for (const element of candidates) {
    const type = fieldType(element);
    if (['hidden', 'submit', 'button', 'image', 'reset', 'search'].includes(type)) continue;
    // Skip non-interactable controls: the display:none g-recaptcha-response textarea,
    // collapsed/conditional fields, and any bot-challenge field the user cannot fill.
    const rect = element.getBoundingClientRect();
    const style = window.getComputedStyle(element);
    if ((rect.width === 0 && rect.height === 0) || style.display === 'none' || style.visibility === 'hidden') continue;
    const nameId = ((element.getAttribute('name') || '') + ' ' + (element.getAttribute('id') || '')).toLowerCase();
    if (/recaptcha|captcha|turnstile/.test(nameId)) continue;
    // An <input role="combobox"> is a picker wearing an input's clothes: typing into
    // it leaves the widget's real state untouched while element.value reads back the
    // text we just wrote, so the generic text path would report a false success. Let
    // the ARIA sweep below claim it instead (audit finding F9).
    if (ariaWidgetRoleFor(element)) continue;
    // A field we cannot label is NEVER dropped: it is surfaced with a synthetic
    // label and a flag so the run can pause for a human (audit finding F6).
    const resolved = resolveLabelFromSources(labelSourcesFor(element));
    const id = element.getAttribute('id');
    const name = element.getAttribute('name');
    const selector = selectorFor(element, type);
    fields.push({
      label: resolved.label,
      label_source: resolved.label_source,
      label_synthetic: resolved.label_synthetic,
      field_type: type,
      selector,
      required: element.required === true || element.getAttribute('aria-required') === 'true',
      metadata: {
        tag_name: element.tagName.toLowerCase(),
        accept: element.getAttribute('accept'),
        autocomplete: element.getAttribute('autocomplete'),
        id,
        name,
        placeholder: element.getAttribute('placeholder'),
        file_count: type === 'file' && element.files ? element.files.length : null,
        value: ['checkbox', 'radio'].includes(type) ? element.getAttribute('value') : null,
        checked: ['checkbox', 'radio'].includes(type) ? element.checked === true : null,
        options: optionsFor(element)
      }
    });
  }
  const ariaCandidates = Array.from(document.querySelectorAll(
    '[role="combobox"], [role="listbox"], [role="radiogroup"], [aria-haspopup][data-automation-id]'
  ));
  for (const element of ariaCandidates) {
    const role = ariaWidgetRoleFor(element);
    if (!role) continue;
    const rect = element.getBoundingClientRect();
    const style = window.getComputedStyle(element);
    if ((rect.width === 0 && rect.height === 0) || style.display === 'none' || style.visibility === 'hidden') continue;
    const nameId = ((element.getAttribute('name') || '') + ' ' + (element.getAttribute('id') || '')).toLowerCase();
    if (/recaptcha|captcha|turnstile/.test(nameId)) continue;
    const resolved = resolveLabelFromSources(labelSourcesFor(element));
    const options = ariaOptionsFor(element, role);
    fields.push({
      label: resolved.label,
      label_source: resolved.label_source,
      label_synthetic: resolved.label_synthetic,
      field_type: `aria_${role}`,
      selector: ariaSelectorFor(element),
      required: element.getAttribute('aria-required') === 'true' || element.hasAttribute('required'),
      metadata: {
        tag_name: element.tagName.toLowerCase(),
        aria_role: role,
        aria_expanded: element.getAttribute('aria-expanded'),
        automation_id: element.getAttribute('data-automation-id'),
        id: element.getAttribute('id'),
        name: element.getAttribute('name'),
        placeholder: element.getAttribute('placeholder'),
        // A combobox that was never opened owns no options yet. Recording that
        // honestly is what lets the write path pause instead of guessing.
        options_rendered: options.length > 0,
        options: options
      }
    });
  }
  return JSON.stringify(fields);
"""


DOM_FIELD_DISCOVERY_SCRIPT = "\n".join(["(() => {", LABEL_RESOLUTION_JS, _FIELD_DISCOVERY_BODY_JS, "})()"])


DOM_BLOCKER_DISCOVERY_SCRIPT = r"""
(() => {
  const text = (document.body && document.body.innerText ? document.body.innerText : '').toLowerCase();
  const html = document.documentElement ? document.documentElement.innerHTML.toLowerCase() : '';
  const blockers = [];
  const isChallengeVisible = (element) => {
    if (!element) { return false; }
    const rect = element.getBoundingClientRect();
    if (rect.width < 40 || rect.height < 40) { return false; }
    const style = window.getComputedStyle(element);
    return style.visibility !== 'hidden' && style.display !== 'none' && Number(style.opacity || '1') > 0.1;
  };
  // Only a VISIBLE, interactive challenge is a real blocker. An invisible reCAPTCHA v3
  // badge/script is embedded on most modern application forms, requires no interaction,
  // and must never pause the run. Matching raw page text/HTML (the old behaviour) flagged
  // every such form as a CAPTCHA and hung the run in an endless pause/resume loop.
  const recaptchaChallenge = Array.from(
    document.querySelectorAll('iframe[src*="recaptcha/api2/anchor" i], iframe[src*="recaptcha/api2/bframe" i], div.g-recaptcha')
  ).some((element) => {
    if (element.closest && element.closest('.grecaptcha-badge')) { return false; }
    const src = (element.getAttribute('src') || '').toLowerCase();
    if (src.indexOf('size=invisible') !== -1) { return false; }
    if ((element.getAttribute('data-size') || '').toLowerCase() === 'invisible') { return false; }
    return isChallengeVisible(element);
  });
  const hcaptchaChallenge = Array.from(
    document.querySelectorAll('iframe[src*="hcaptcha.com" i], div.h-captcha')
  ).some(isChallengeVisible);
  const turnstileChallenge = Array.from(
    document.querySelectorAll('iframe[src*="challenges.cloudflare.com" i], div.cf-turnstile')
  ).some(isChallengeVisible);
  const datadomeChallenge = Array.from(
    document.querySelectorAll('iframe[src*="captcha-delivery.com" i]')
  ).some(isChallengeVisible);
  const docTitle = (document.title || '').toLowerCase();
  const cloudflareInterstitial =
    Boolean(document.querySelector('#challenge-running, #cf-challenge-running, #challenge-stage, #challenge-form'))
    || docTitle === 'just a moment...'
    || (docTitle.indexOf('attention required') !== -1 && html.includes('cloudflare'));
  let captchaVendor = null;
  if (recaptchaChallenge) { captchaVendor = 'recaptcha'; }
  else if (hcaptchaChallenge) { captchaVendor = 'hcaptcha'; }
  else if (turnstileChallenge || cloudflareInterstitial) { captchaVendor = 'cloudflare'; }
  else if (datadomeChallenge) { captchaVendor = 'datadome'; }
  if (captchaVendor) {
    blockers.push({ blocker_type: 'CAPTCHA', message: 'Interactive CAPTCHA or bot challenge detected', confidence: 0.95, metadata: { vendor: captchaVendor } });
  }
  if (text.includes('multi-factor') || text.includes('multifactor') || text.includes('authenticator app') || text.includes('mfa')) {
    blockers.push({ blocker_type: 'MFA', message: 'Multi-factor authentication detected', confidence: 0.82 });
  }
  if (text.includes('one-time code') || text.includes('one time code') || text.includes('verification code') || text.includes('otp')) {
    blockers.push({ blocker_type: 'OTP', message: 'One-time passcode challenge detected', confidence: 0.8 });
  }
  const passwordInputs = Array.from(document.querySelectorAll('input[type="password"]'))
    .filter((element) => {
      const rect = element.getBoundingClientRect();
      const style = window.getComputedStyle(element);
      return rect.width > 0 && rect.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
    });
  const loginTextDetected =
    text.includes('sign in')
    || text.includes('log in')
    || text.includes('login')
    || text.includes('create an account')
    || text.includes('sign into your account');
  if (passwordInputs.length > 0 || (loginTextDetected && text.includes('password'))) {
    blockers.push({
      blocker_type: 'LOGIN',
      message: 'Login or account creation page detected',
      confidence: passwordInputs.length > 0 ? 0.9 : 0.74,
      metadata: { password_input_count: passwordInputs.length }
    });
  }
  const formLabelText = Array.from(document.querySelectorAll('label, legend, [aria-label]'))
    .map((element) => element.innerText || element.textContent || element.getAttribute('aria-label') || '')
    .join('\n')
    .toLowerCase();
  const sensitiveQuestionPatterns = [
    { key: 'work_authorization', phrases: ['legally authorized', 'work authorization', 'authorized to work'] },
    { key: 'sponsorship', phrases: ['require sponsorship', 'need sponsorship', 'visa sponsorship', 'sponsor now or in the future'] },
    { key: 'security_clearance', phrases: ['security clearance', 'active clearance', 'clearance level'] },
    { key: 'compensation', phrases: ['salary expectation', 'desired salary', 'desired compensation', 'compensation expectation'] },
    { key: 'relocation', phrases: ['willing to relocate', 'relocation assistance', 'relocate for this role'] },
    { key: 'eeo', phrases: ['voluntary self-identification', 'veteran status', 'disability status', 'race/ethnicity', 'gender identity'] }
  ];
  const matchedSensitiveQuestions = sensitiveQuestionPatterns
    .filter((pattern) => pattern.phrases.some((phrase) => formLabelText.includes(phrase)))
    .map((pattern) => pattern.key);
  if (matchedSensitiveQuestions.length > 0) {
    blockers.push({
      blocker_type: 'AMBIGUOUS_QUESTION',
      message: 'Sensitive or ambiguous application question detected',
      confidence: 0.86,
      metadata: { matched_patterns: matchedSensitiveQuestions.slice(0, 8) }
    });
  }
  return JSON.stringify(blockers);
})()
"""


DOM_METADATA_CAPTURE_SCRIPT = r"""
(() => {
  const fields = JSON.parse((() => {
    const fields = [];
    const candidates = Array.from(document.querySelectorAll('input, textarea, select'));
    const fieldType = (element) => {
      const tagName = element.tagName.toLowerCase();
      return tagName === 'input' ? (element.getAttribute('type') || 'text').toLowerCase() : tagName;
    };
    const optionsFor = (element) => {
      if (element.tagName.toLowerCase() !== 'select') return [];
      return Array.from(element.options || []).map((option) => ({
        value: option.getAttribute('value') || option.value || '',
        label: (option.textContent || '').trim(),
        selected: option.selected === true,
        disabled: option.disabled === true
      }));
    };
    for (const element of candidates) {
      const type = fieldType(element);
      if (['hidden', 'submit', 'button', 'image', 'reset'].includes(type)) continue;
      fields.push({
        tag_name: element.tagName.toLowerCase(),
        type,
        name: element.getAttribute('name'),
        id: element.getAttribute('id'),
        autocomplete: element.getAttribute('autocomplete'),
        required: element.required === true || element.getAttribute('aria-required') === 'true',
        accept: element.getAttribute('accept'),
        file_count: type === 'file' && element.files ? element.files.length : null,
        value: ['checkbox', 'radio'].includes(type) ? element.getAttribute('value') : null,
        checked: ['checkbox', 'radio'].includes(type) ? element.checked === true : null,
        options: optionsFor(element)
      });
    }
    return JSON.stringify(fields);
  })());
  return JSON.stringify({
    url: location.href,
    title: document.title || '',
    field_count: fields.length,
    fields,
    forms: Array.from(document.forms).map((form, index) => ({
      index,
      id: form.getAttribute('id'),
      name: form.getAttribute('name'),
      action: form.getAttribute('action'),
      method: form.getAttribute('method')
    })),
    captured_at_epoch_ms: Date.now()
  });
})()
"""


DOM_VISIBLE_TEXT_SCRIPT = r"""
(() => {
  const title = document.title || '';
  const bodyText = document.body && document.body.innerText ? document.body.innerText : '';
  const normalized = bodyText
    .replace(/\r/g, '\n')
    .replace(/[ \t]+\n/g, '\n')
    .replace(/\n{3,}/g, '\n\n')
    .trim();
  return JSON.stringify({
    url: location.href,
    title,
    text: normalized.slice(0, 240000),
    text_length: normalized.length
  });
})()
"""


def fields_from_dom_snapshot(raw_fields: Any, *, frame: FrameRef | None = None) -> list[BrowserField]:
    if not isinstance(raw_fields, list):
        return []
    parsed: list[BrowserField] = []
    for index, raw in enumerate(raw_fields):
        if not isinstance(raw, dict):
            continue
        label = str(raw.get("label") or "").strip()
        label_source = str(raw.get("label_source") or "").strip()
        selector = raw.get("selector")
        field_type = str(raw.get("field_type") or "text").strip().lower()
        synthetic = bool(raw.get("label_synthetic")) or not label
        if synthetic:
            label = SYNTHETIC_LABEL
            label_source = "synthetic"
        confidence = 0.78 if selector else 0.45
        if synthetic:
            # Surfaced, never dropped, but never confident enough to answer
            # without a human reading the page first.
            confidence = round(confidence / 2, 2)
        raw_metadata = raw.get("metadata")
        metadata: dict[str, Any] = dict(raw_metadata) if isinstance(raw_metadata, dict) else {}
        if label_source:
            metadata["label_source"] = label_source
        if synthetic:
            metadata["label_synthetic"] = True
            metadata["requires_human_label_review"] = True
        field_id = f"field:{index}:{field_type}:{label[:40].lower()}"
        if frame is not None:
            metadata["frame_url"] = frame.url
            metadata["frame_index"] = frame.index
            # Discovery restarts its index at zero in every frame, so an unqualified
            # id would collide between the top document and the embedded form.
            field_id = f"frame:{frame.index}:{field_id}"
        parsed.append(
            BrowserField(
                field_id=field_id,
                label=label,
                field_type=field_type,
                selector=str(selector) if selector else None,
                required=bool(raw.get("required", False)),
                confidence=confidence,
                metadata=metadata,
            )
        )
    return parsed


_FIELD_WRITE_HELPERS_JS = r"""
  const normalize = (input) => String(input == null ? '' : input)
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, ' ')
    .trim();
  const digitsOf = (input) => String(input == null ? '' : input).replace(/[^0-9]/g, '');
  const parseBooleanIntent = (raw) => {
    const normalized = normalize(raw);
    if (['yes', 'true', 'checked', 'check', '1', 'on', 'agree', 'accepted', 'accept'].includes(normalized)) return true;
    if (['no', 'false', 'unchecked', 'uncheck', '0', 'off', 'decline', 'declined', 'reject'].includes(normalized)) {
      return false;
    }
    return null;
  };
  // React 16+ installs its OWN `value`/`checked` descriptor on the node, and that
  // setter refreshes React's cached copy of the value. A plain `node.value = x`
  // therefore leaves the tracker believing nothing changed, so React DISCARDS the
  // synthetic change event and the portal never sees the answer. Writing through
  // the *prototype* descriptor leaves React's cache stale, so the framework
  // observes a real change. Same mechanism in Vue and Angular. (Audit finding F5.)
  const prototypeSetterFor = (element, property) => {
    const tagName = element.tagName ? element.tagName.toLowerCase() : '';
    let ctor = window.HTMLInputElement;
    if (tagName === 'select') ctor = window.HTMLSelectElement;
    else if (tagName === 'textarea') ctor = window.HTMLTextAreaElement;
    let proto = ctor ? ctor.prototype : null;
    while (proto) {
      const descriptor = Object.getOwnPropertyDescriptor(proto, property);
      if (descriptor && typeof descriptor.set === 'function') return descriptor.set;
      proto = Object.getPrototypeOf(proto);
    }
    return null;
  };
  const setNativeValue = (element, property, next) => {
    const setter = prototypeSetterFor(element, property);
    if (setter) {
      setter.call(element, next);
      return true;
    }
    element[property] = next;
    return false;
  };
  const fireInputEvents = (element) => {
    element.dispatchEvent(new Event('input', { bubbles: true }));
    element.dispatchEvent(new Event('change', { bubbles: true }));
  };
  const focusSafely = (element) => { try { if (element.focus) element.focus(); } catch (error) { /* non-fatal */ } };
  const blurSafely = (element) => { try { if (element.blur) element.blur(); } catch (error) { /* non-fatal */ } };
  // How closely the value read back off the node matches what we asked for.
  const classifyMatch = (expected, actual) => {
    const expectedText = String(expected == null ? '' : expected);
    const actualText = String(actual == null ? '' : actual);
    if (expectedText === actualText) return 'exact';
    const expectedNormalized = normalize(expectedText);
    if (expectedNormalized && expectedNormalized === normalize(actualText)) return 'normalized';
    const expectedDigits = digitsOf(expectedText);
    if (expectedDigits && expectedDigits === digitsOf(actualText)) return 'reformatted';
    return 'mismatch';
  };
  // Every write is read back: a value that silently did not land reports ok:false.
  const verdict = (expected, actual, base) => {
    const expectedText = String(expected == null ? '' : expected);
    const actualText = String(actual == null ? '' : actual);
    const mode = classifyMatch(expectedText, actualText);
    const matched = mode !== 'mismatch';
    return Object.assign({
      ok: matched,
      verified: true,
      value_matched: matched,
      match_mode: mode,
      expected: expectedText,
      actual: actualText,
      expected_length: expectedText.length,
      actual_length: actualText.length,
      message: matched ? 'field value applied' : 'the field did not keep the value that was written'
    }, base);
  };
  const MATCH_TIERS = ['exact', 'prefix', 'token'];
  const tokensOf = (value) => normalize(value).split(' ').filter(Boolean);
  const isTokenPrefix = (haystack, needle) => {
    if (needle.length === 0 || needle.length > haystack.length) return false;
    return needle.every((token, index) => haystack[index] === token);
  };
  const hasTokenRun = (haystack, needle) => {
    if (needle.length === 0 || needle.length > haystack.length) return false;
    for (let start = 0; start + needle.length <= haystack.length; start += 1) {
      if (needle.every((token, index) => haystack[start + index] === token)) return true;
    }
    return false;
  };
  // There is deliberately NO raw character-substring tier: bidirectional substring
  // matching is precisely what made "India" select "Indiana". Every tier below is
  // token-bounded. (Audit finding F9 / fix-plan row 10.)
  const tierFor = (texts, target) => {
    const targetNormalized = normalize(target);
    if (!targetNormalized) return null;
    const targetTokens = tokensOf(target);
    let best = null;
    for (const text of texts) {
      const normalized = normalize(text);
      if (!normalized) continue;
      const tokens = tokensOf(text);
      let tier = null;
      if (normalized === targetNormalized) tier = 'exact';
      else if (isTokenPrefix(tokens, targetTokens) || isTokenPrefix(targetTokens, tokens)) tier = 'prefix';
      else if (hasTokenRun(tokens, targetTokens) || hasTokenRun(targetTokens, tokens)) tier = 'token';
      if (tier === null) continue;
      if (best === null || MATCH_TIERS.indexOf(tier) < MATCH_TIERS.indexOf(best)) best = tier;
    }
    return best;
  };
  // Ranked match that requires a UNIQUE winner at the best populated tier.
  // A tie or a miss never guesses: it reports the candidates and refuses.
  const rankCandidates = (entries, target) => {
    const scored = [];
    for (const entry of entries) {
      const tier = tierFor([entry.label, entry.value], target);
      if (tier !== null) scored.push({ entry, tier });
    }
    for (const tier of MATCH_TIERS) {
      const atTier = scored.filter((candidate) => candidate.tier === tier);
      if (atTier.length === 0) continue;
      return {
        status: atTier.length === 1 ? 'unique' : 'ambiguous',
        tier,
        winners: atTier.map((candidate) => candidate.entry)
      };
    }
    return { status: 'none', tier: null, winners: [] };
  };
  const refuseChoice = (action, type, ranked, target, currentText, optionCount) => {
    const targetText = String(target == null ? '' : target);
    const currentValue = String(currentText == null ? '' : currentText);
    const failure = {
      ok: false,
      action,
      field_type: type,
      verified: false,
      value_matched: false,
      match_mode: 'mismatch',
      expected: targetText,
      actual: currentValue,
      expected_length: targetText.length,
      actual_length: currentValue.length,
      option_count: optionCount,
      message: ranked.status === 'ambiguous'
        ? 'reviewed value matched more than one option; a human must choose'
        : 'reviewed value did not match any option'
    };
    if (ranked.status === 'ambiguous') {
      failure.ambiguity_code = 'AMBIGUOUS_SELECT_OPTION';
      failure.match_tier = ranked.tier;
      failure.candidate_labels = ranked.winners.map((entry) => String(entry.label).slice(0, 160)).slice(0, 8);
    }
    return failure;
  };
  const selectedOptionLabel = (element) => {
    const selected = Array.from(element.options || []).find((option) => option.selected === true);
    return selected ? String(selected.textContent || '').trim() : '';
  };
  const optionLabelFor = (element) => {
    const resolved = resolveLabelFromSources(labelSourcesFor(element));
    return resolved.label_synthetic ? '' : resolved.label;
  };
"""


_FIELD_WRITE_BODY_JS = r"""
  const element = document.querySelector(selector);
  if (!element) {
    return JSON.stringify({
      ok: false, action: 'query', verified: false, value_matched: false, message: 'field not found'
    });
  }
  const tag = element.tagName.toLowerCase();
  const type = tag === 'input' ? (element.getAttribute('type') || 'text').toLowerCase() : tag;
  const normalizedReviewedValue = normalize(reviewedValue);
  if (!normalizedReviewedValue) {
    return JSON.stringify({
      ok: false, action: 'apply', field_type: type, verified: false, value_matched: false,
      message: 'reviewed value is empty'
    });
  }

  if (tag === 'select') {
    const allOptions = Array.from(element.options || []);
    const entries = allOptions
      .filter((option) => option.disabled !== true)
      .map((option) => ({
        option,
        label: String(option.textContent || '').trim(),
        value: option.getAttribute('value') || option.value || ''
      }));
    const ranked = rankCandidates(entries, reviewedValue);
    if (ranked.status !== 'unique') {
      return JSON.stringify(
        refuseChoice('select_option', type, ranked, reviewedValue, selectedOptionLabel(element), entries.length)
      );
    }
    const winner = ranked.winners[0];
    focusSafely(element);
    for (const option of allOptions) option.selected = option === winner.option;
    setNativeValue(element, 'value', winner.value);
    fireInputEvents(element);
    blurSafely(element);
    return JSON.stringify(verdict(winner.label, selectedOptionLabel(element), {
      action: 'select_option',
      field_type: type,
      match_tier: ranked.tier,
      option_count: entries.length,
      selected_label: winner.label,
      selected_value_length: String(winner.value || '').length
    }));
  }

  if (type === 'checkbox') {
    const desired = parseBooleanIntent(reviewedValue);
    if (desired === null) {
      return JSON.stringify({
        ok: false, action: 'set_checkbox', field_type: type, verified: false, value_matched: false,
        message: 'checkbox answer must be reviewed as yes or no'
      });
    }
    focusSafely(element);
    setNativeValue(element, 'checked', desired);
    fireInputEvents(element);
    blurSafely(element);
    return JSON.stringify(verdict(String(desired), String(element.checked === true), {
      action: 'set_checkbox',
      field_type: type,
      checked: element.checked === true
    }));
  }

  if (type === 'radio') {
    const root = element.form || document;
    const groupName = element.getAttribute('name');
    const group = groupName
      ? Array.from(root.querySelectorAll(`input[type="radio"][name="${CSS.escape(groupName)}"]`))
      : [element];
    const entries = group
      .filter((candidate) => candidate.disabled !== true)
      .map((candidate) => ({
        option: candidate,
        label: optionLabelFor(candidate),
        value: candidate.getAttribute('value') || ''
      }));
    const ranked = rankCandidates(entries, reviewedValue);
    if (ranked.status !== 'unique') {
      return JSON.stringify(refuseChoice('set_radio', type, ranked, reviewedValue, '', entries.length));
    }
    const winner = ranked.winners[0];
    focusSafely(winner.option);
    setNativeValue(winner.option, 'checked', true);
    fireInputEvents(winner.option);
    blurSafely(winner.option);
    return JSON.stringify(verdict('true', String(winner.option.checked === true), {
      action: 'set_radio',
      field_type: type,
      match_tier: ranked.tier,
      option_count: entries.length,
      checked: winner.option.checked === true,
      selected_label: winner.label,
      selected_value_length: String(winner.value || '').length
    }));
  }

  // ARIA widget pickers (audit finding F9). The browser owns no value for these, so
  // falling through to element.value would write text the form never sees and then
  // read that same text back as proof it worked.
  const widgetRole = (() => {
    const role = (element.getAttribute('role') || '').toLowerCase();
    if (role === 'combobox' || role === 'listbox' || role === 'radiogroup') return role;
    if (element.hasAttribute('aria-haspopup') && element.hasAttribute('data-automation-id')) return 'combobox';
    return null;
  })();
  if (widgetRole) {
    const containers = [];
    const owned = ((element.getAttribute('aria-controls') || '') + ' ' + (element.getAttribute('aria-owns') || '')).trim();
    for (const ownedId of owned.split(/\s+/).filter(Boolean)) {
      const container = document.getElementById(ownedId);
      if (container) containers.push(container);
    }
    containers.push(element);
    const optionSelector = widgetRole === 'radiogroup' ? '[role="radio"]' : '[role="option"]';
    const seen = new Set();
    const entries = [];
    for (const container of containers) {
      for (const candidate of Array.from(container.querySelectorAll(optionSelector))) {
        if (seen.has(candidate) || candidate.getAttribute('aria-disabled') === 'true') continue;
        seen.add(candidate);
        entries.push({
          option: candidate,
          label: String(candidate.textContent || '').trim(),
          value: candidate.getAttribute('data-value') || candidate.getAttribute('value') || ''
        });
      }
    }
    if (!entries.length) {
      // A closed combobox renders its list only after a real user gesture. We do not
      // fake one and we do not guess: the run pauses and a human opens it.
      return JSON.stringify({
        ok: false, action: 'aria_select_option', field_type: 'aria_' + widgetRole,
        verified: false, value_matched: false, requires_human: true,
        message: widgetRole + ' exposes no options until it is opened'
      });
    }
    const ranked = rankCandidates(entries, reviewedValue);
    if (ranked.status !== 'unique') {
      return JSON.stringify(
        refuseChoice('aria_select_option', 'aria_' + widgetRole, ranked, reviewedValue, '', entries.length)
      );
    }
    const winner = ranked.winners[0];
    winner.option.click();
    const chosen = winner.option.getAttribute('aria-selected') === 'true'
      || winner.option.getAttribute('aria-checked') === 'true';
    return JSON.stringify(verdict(winner.label, chosen ? winner.label : '', {
      action: 'aria_select_option',
      field_type: 'aria_' + widgetRole,
      match_tier: ranked.tier,
      option_count: entries.length,
      selected_label: winner.label
    }));
  }

  if ('value' in element) {
    focusSafely(element);
    setNativeValue(element, 'value', reviewedValue);
    fireInputEvents(element);
    blurSafely(element);
    return JSON.stringify(verdict(reviewedValue, element.value, { action: 'set_value', field_type: type }));
  }
  return JSON.stringify({
    ok: false, action: 'apply', field_type: type, verified: false, value_matched: false,
    message: 'field type is not supported'
  });
"""


# Named in the injected source so a captured script says which one it is, both in
# a debug log and to anything that has to tell a write apart from a read-back.
WRITE_SCRIPT_MARKER = "applyo:write-field-value"
VERIFY_SCRIPT_MARKER = "applyo:verify-field-value"


def build_apply_field_value_script(selector: str, value: str) -> str:
    """Build the injected script that writes one reviewed answer and verifies it.

    The script returns a JSON string. Consumers (``runner.py`` via
    :func:`parse_apply_field_result`) can rely on this envelope:

    ==========================  ====================================================
    key                         meaning
    ==========================  ====================================================
    ``ok``                      bool. True only when the value was written AND read
                                back successfully. A write that silently did not
                                take is ``False``.
    ``action``                  ``query`` | ``apply`` | ``set_value`` |
                                ``select_option`` | ``set_checkbox`` | ``set_radio``
    ``field_type``              resolved input type (absent for ``query``)
    ``verified``                bool. True when a read-back actually happened. False
                                means we never got as far as writing (field missing,
                                empty answer, refused option match).
    ``value_matched``           bool. Read-back agreed with the intended value.
    ``match_mode``              ``exact`` | ``normalized`` | ``reformatted`` |
                                ``mismatch``. ``reformatted`` means the page
                                rewrote the value but kept the same digits (phone
                                numbers, dates) and is treated as success.
    ``expected`` / ``actual``   strings, present whenever a comparison was made.
                                REDACTED by :func:`parse_apply_field_result` for
                                secret-bearing fields.
    ``expected_length`` /       int lengths of the above.
    ``actual_length``
    ``match_tier``              ``exact`` | ``prefix`` | ``token`` for select/radio.
    ``option_count``            number of enabled options considered.
    ``selected_label``          label of the option that was chosen.
    ``selected_value_length``   length of the chosen option's value.
    ``checked``                 bool for checkbox/radio.
    ``candidate_labels``        present only on an ambiguous option match: the
                                competing labels (<= 8, truncated).
    ``ambiguity_code``          ``AMBIGUOUS_SELECT_OPTION`` when two or more options
                                tied. The script refuses to guess; a human decides.
    ``message``                 human-readable outcome.
    ==========================  ====================================================
    """
    selector_json = json.dumps(selector)
    value_json = json.dumps(value)
    return "\n".join(
        [
            "(() => {",
            f"  // {WRITE_SCRIPT_MARKER}",
            f"  const selector = {selector_json};",
            f"  const reviewedValue = {value_json};",
            LABEL_RESOLUTION_JS,
            _FIELD_WRITE_HELPERS_JS,
            _FIELD_WRITE_BODY_JS,
            "})()",
        ]
    )


_FIELD_VERIFY_BODY_JS = r"""
  const element = document.querySelector(selector);
  if (!element) {
    return JSON.stringify({
      ok: false, action: 'verify', verified: false, value_matched: false, message: 'field not found'
    });
  }
  const tag = element.tagName.toLowerCase();
  const type = tag === 'input' ? (element.getAttribute('type') || 'text').toLowerCase() : tag;
  if (!('value' in element)) {
    return JSON.stringify({
      ok: false, action: 'verify', field_type: type, verified: false, value_matched: false,
      message: 'field value cannot be read back'
    });
  }
  const actual = String(element.value == null ? '' : element.value);
  const base = verdict(reviewedValue, actual, { action: 'verify', field_type: type });
  if (!base.value_matched && actual) {
    // An autocomplete that turns "New York" into "New York, NY, United States"
    // has accepted the answer, not lost it. Rewriting the field to the shorter
    // form would undo the portal's own selection, so this counts as landed.
    if (isTokenPrefix(tokensOf(actual), tokensOf(reviewedValue))) {
      return JSON.stringify(Object.assign({}, base, {
        ok: true,
        value_matched: true,
        match_mode: 'expanded',
        message: 'the page expanded the typed value into its own form'
      }));
    }
  }
  return JSON.stringify(base);
"""


def build_verify_field_value_script(selector: str, value: str) -> str:
    """Build a script that reads a field back without writing to it.

    Typing is the right way to fill a text field: it fires the key events that
    autocomplete widgets listen for, which a native value assignment never does.
    But typing gives no evidence the value survived, and a React-controlled input
    routinely discards it. This reads the field back and reports the same verdict
    envelope as :func:`build_apply_field_value_script`, with one extra
    ``match_mode`` of ``expanded`` for a page that canonicalised what was typed.
    """
    selector_json = json.dumps(selector)
    value_json = json.dumps(value)
    return "\n".join(
        [
            "(() => {",
            f"  // {VERIFY_SCRIPT_MARKER}",
            f"  const selector = {selector_json};",
            f"  const reviewedValue = {value_json};",
            LABEL_RESOLUTION_JS,
            _FIELD_WRITE_HELPERS_JS,
            _FIELD_VERIFY_BODY_JS,
            "})()",
        ]
    )


def build_click_by_text_script(labels: list[str]) -> str:
    labels_json = json.dumps([label for label in labels if label.strip()])
    return f"""
(() => {{
  const labels = {labels_json};
  const normalize = (input) => String(input ?? '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, ' ')
    .trim();
  const requested = labels.map(normalize).filter(Boolean);
  if (requested.length === 0) {{
    return JSON.stringify({{ ok: false, action: 'click_by_text', message: 'no click labels configured' }});
  }}
  const forbidden = new Set(['submit', 'submit application', 'send application', 'finish', 'complete application']);
  const isFinalSubmitLike = (normalized) =>
    forbidden.has(normalized)
    || normalized.startsWith('submit ')
    || normalized.startsWith('send ')
    || normalized.includes(' submit application')
    || normalized.includes(' send application')
    || normalized.includes(' complete application')
    || normalized.includes(' finish application');
  const candidates = Array.from(document.querySelectorAll('button, a, input[type="button"], input[type="submit"], [role="button"]'));
  const isVisible = (element) => {{
    const rect = element.getBoundingClientRect();
    const style = window.getComputedStyle(element);
    return rect.width > 0 && rect.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
  }};
  const labelFor = (element) => {{
    if (element instanceof HTMLInputElement) return element.value || element.getAttribute('aria-label') || '';
    return element.innerText || element.textContent || element.getAttribute('aria-label') || '';
  }};
  const currentOrigin = location.origin;
  const isExternalLink = (element) =>
    element instanceof HTMLAnchorElement && element.href && !element.href.startsWith(currentOrigin) && !element.href.startsWith('#') && !element.href.startsWith('javascript');
  const matches = candidates
    .filter(isVisible)
    .filter((element) => !isExternalLink(element))
    .map((element) => ({{ element, label: labelFor(element).trim(), normalized: normalize(labelFor(element)) }}))
    .filter((entry) => entry.normalized && !isFinalSubmitLike(entry.normalized))
    .filter((entry) => requested.some((label) => entry.normalized === label || entry.normalized.includes(label)));
  if (matches.length === 0) {{
    return JSON.stringify({{
      ok: false,
      action: 'click_by_text',
      message: 'no matching safe portal action was found',
      candidate_count: candidates.length
    }});
  }}
  const exactMatches = matches.filter((entry) => requested.includes(entry.normalized));
  const preferredMatches = exactMatches.length > 0 ? exactMatches : matches;
  const uniqueTargets = new Set(preferredMatches.map((entry) => `${{entry.normalized}}|${{entry.element.tagName.toLowerCase()}}|${{entry.element instanceof HTMLAnchorElement ? entry.element.href : ''}}`));
  if (uniqueTargets.size > 1) {{
    return JSON.stringify({{
      ok: false,
      action: 'click_by_text',
      message: 'multiple safe portal actions matched; manual review is required',
      ambiguity_code: 'AMBIGUOUS_PORTAL_ACTION',
      candidate_count: preferredMatches.length,
      candidate_labels: preferredMatches.map((entry) => entry.label.slice(0, 160)).slice(0, 8)
    }});
  }}
  const exact = preferredMatches[0];
  exact.element.click();
  return JSON.stringify({{
    ok: true,
    action: 'click_by_text',
    clicked_label: exact.label.slice(0, 160),
    clicked_tag: exact.element.tagName.toLowerCase(),
    href: exact.element instanceof HTMLAnchorElement ? exact.element.href : null
  }});
}})()
"""


def build_final_submit_script(labels: list[str]) -> str:
    labels_json = json.dumps([label for label in labels if label.strip()])
    return f"""
(() => {{
  const labels = {labels_json};
  const normalize = (input) => String(input ?? '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, ' ')
    .trim();
  const requested = new Set(labels.map(normalize).filter(Boolean));
  if (requested.size === 0) {{
    return JSON.stringify({{ ok: false, action: 'final_submit', message: 'no final submit labels configured' }});
  }}
  const candidates = Array.from(document.querySelectorAll('button, input[type="submit"], [role="button"]'));
  const isVisible = (element) => {{
    const rect = element.getBoundingClientRect();
    const style = window.getComputedStyle(element);
    return rect.width > 0 && rect.height > 0 && style.visibility !== 'hidden' && style.display !== 'none';
  }};
  const labelFor = (element) => {{
    if (element instanceof HTMLInputElement) return element.value || element.getAttribute('aria-label') || '';
    return element.innerText || element.textContent || element.getAttribute('aria-label') || element.getAttribute('title') || '';
  }};
  const matches = candidates
    .filter(isVisible)
    .map((element) => ({{ element, label: labelFor(element).trim(), normalized: normalize(labelFor(element)) }}))
    .filter((entry) => requested.has(entry.normalized));
  if (matches.length === 0) {{
    return JSON.stringify({{
      ok: false,
      action: 'final_submit',
      message: 'no exact final submit control was found',
      candidate_count: candidates.length
    }});
  }}
  const target = matches[0];
  target.element.click();
  return JSON.stringify({{
    ok: true,
    action: 'final_submit',
    clicked_label: target.label.slice(0, 160),
    clicked_tag: target.element.tagName.toLowerCase()
  }});
}})()
"""


# Multi-word phrases that are unambiguous wherever they appear.
_SECRET_PHRASE_HINTS: tuple[str, ...] = (
    "password",
    "passcode",
    "one-time",
    "one time",
    "onetime",
    "social security",
    "api key",
)

# Single words that only count on a token boundary, so "encode"/"tokenize" and
# similar innocent substrings do not trip the redaction.
_SECRET_WORD_PATTERN = re.compile(
    r"\b(code|codes|otp|pin|ssn|secret|secrets|token|tokens|credential|credentials)\b"
)


def _is_secret_field(field: BrowserField) -> bool:
    """True when read-back values for this field must never be reported verbatim.

    Deliberately over-inclusive: ``runner.py`` spreads this payload straight into
    emitted events (including the OTP failure event), and CLAUDE.md forbids ever
    logging a plaintext key, password, or OTP code. Losing ``expected``/``actual``
    on a "Postal code" field costs a little debuggability; leaking a one-time code
    breaks a safety invariant.
    """
    if field.field_type == "password":
        return True
    metadata = field.metadata if isinstance(field.metadata, dict) else {}
    # Machine names carry no separators ("otpValue"), so humanize them first or
    # the word-boundary patterns below would never fire on them.
    identifiers = (metadata.get("name"), metadata.get("id"), metadata.get("autocomplete"))
    haystack = " ".join(
        [str(field.label or "")] + [humanize_identifier(str(value)) for value in identifiers if value]
    ).lower()
    if any(hint in haystack for hint in _SECRET_PHRASE_HINTS):
        return True
    return _SECRET_WORD_PATTERN.search(haystack) is not None


def parse_apply_field_result(raw_result: Any, field: BrowserField) -> BrowserStepResult:
    if isinstance(raw_result, str):
        try:
            payload = json.loads(raw_result)
        except json.JSONDecodeError:
            payload = {"ok": False, "message": "browser returned an invalid field application result"}
    else:
        payload = raw_result if isinstance(raw_result, dict) else {"ok": False, "message": "browser returned an invalid field application result"}

    action = str(payload.get("action") or "apply")
    safe_payload: dict[str, Any] = {"field_id": field.field_id, "action": action}
    for key in (
        "field_type",
        "checked",
        "option_count",
        "selected_value_length",
        "verified",
        "value_matched",
        "match_mode",
        "match_tier",
    ):
        if key in payload:
            safe_payload[key] = payload[key]
    # The runner spreads this payload into emitted events, so the verification
    # values must never carry a password or a one-time code (CLAUDE.md #3).
    verification_keys = ("expected", "actual", "expected_length", "actual_length")
    if _is_secret_field(field):
        if any(key in payload for key in verification_keys):
            safe_payload["values_redacted"] = True
    else:
        for key in ("expected", "actual"):
            if key in payload:
                safe_payload[key] = str(payload[key])[:240]
        for key in ("expected_length", "actual_length"):
            if key in payload:
                safe_payload[key] = payload[key]
    ambiguity_code = payload.get("ambiguity_code")
    if isinstance(ambiguity_code, str) and ambiguity_code.strip():
        safe_payload["ambiguity_code"] = ambiguity_code.strip()[:80]
    candidate_labels = payload.get("candidate_labels")
    if isinstance(candidate_labels, list):
        safe_payload["candidate_labels"] = [
            str(label).strip()[:160] for label in candidate_labels if str(label).strip()
        ][:8]
    selected_label = payload.get("selected_label")
    if isinstance(selected_label, str) and selected_label.strip():
        safe_payload["selected_label"] = selected_label.strip()[:160]
    message = str(payload.get("message") or ("field value applied" if payload.get("ok") else "field value could not be applied"))
    if not payload.get("ok"):
        safe_payload["message"] = message
    return BrowserStepResult(bool(payload.get("ok")), message, safe_payload)


def parse_click_by_text_result(raw_result: Any) -> BrowserStepResult:
    if isinstance(raw_result, str):
        try:
            payload = json.loads(raw_result)
        except json.JSONDecodeError:
            payload = {"ok": False, "message": "browser returned an invalid click result"}
    else:
        payload = raw_result if isinstance(raw_result, dict) else {"ok": False, "message": "browser returned an invalid click result"}

    safe_payload: dict[str, Any] = {"action": "click_by_text"}
    for key in ("clicked_label", "clicked_tag", "href", "candidate_count", "ambiguity_code"):
        value = payload.get(key)
        if isinstance(value, str):
            safe_payload[key] = value[:240]
        elif isinstance(value, int):
            safe_payload[key] = value
        elif value is None and key == "href":
            safe_payload[key] = None
    candidate_labels = payload.get("candidate_labels")
    if isinstance(candidate_labels, list):
        safe_payload["candidate_labels"] = [str(label)[:160] for label in candidate_labels if str(label).strip()][:8]
    message = str(payload.get("message") or ("safe portal action clicked" if payload.get("ok") else "safe portal action could not be clicked"))
    if not payload.get("ok"):
        safe_payload["message"] = message
    return BrowserStepResult(bool(payload.get("ok")), message, safe_payload)


def parse_final_submit_result(raw_result: Any) -> BrowserStepResult:
    result = parse_click_by_text_result(raw_result)
    return BrowserStepResult(
        result.ok,
        "final submit clicked" if result.ok else result.message,
        {**result.payload, "action": "final_submit"},
    )


def blockers_from_dom_snapshot(raw_blockers: Any) -> list[BrowserBlocker]:
    if not isinstance(raw_blockers, list):
        return []
    parsed: list[BrowserBlocker] = []
    for raw in raw_blockers:
        if not isinstance(raw, dict):
            continue
        blocker_type = str(raw.get("blocker_type") or "").strip().upper()
        if blocker_type not in {"CAPTCHA", "MFA", "OTP", "LOGIN", "AMBIGUOUS_QUESTION"}:
            continue
        parsed.append(
            BrowserBlocker(
                blocker_type=blocker_type,
                message=str(raw.get("message") or f"{blocker_type} challenge detected"),
                confidence=float(raw.get("confidence") or 0.5),
                metadata=raw.get("metadata") if isinstance(raw.get("metadata"), dict) else {},
            )
        )
    return parsed
