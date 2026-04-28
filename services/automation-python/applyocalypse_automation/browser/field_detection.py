from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any

from .adapter import BrowserBlocker, BrowserField, BrowserStepResult


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


DOM_FIELD_DISCOVERY_SCRIPT = r"""
(() => {
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
  const textForLabel = (element) => {
    const id = element.getAttribute('id');
    if (id) {
      const explicit = document.querySelector(`label[for="${CSS.escape(id)}"]`);
      if (explicit && explicit.innerText.trim()) return explicit.innerText.trim();
    }
    const parentLabel = element.closest('label');
    if (parentLabel && parentLabel.innerText.trim()) return parentLabel.innerText.trim();
    return element.getAttribute('aria-label')
      || element.getAttribute('name')
      || element.getAttribute('placeholder')
      || id
      || 'Unlabeled field';
  };
  for (const element of candidates) {
    const type = fieldType(element);
    if (['hidden', 'submit', 'button', 'image', 'reset'].includes(type)) continue;
    const label = textForLabel(element);
    const id = element.getAttribute('id');
    const name = element.getAttribute('name');
    const selector = selectorFor(element, type);
    fields.push({
      label,
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
  return JSON.stringify(fields);
})()
"""


DOM_BLOCKER_DISCOVERY_SCRIPT = r"""
(() => {
  const text = (document.body && document.body.innerText ? document.body.innerText : '').toLowerCase();
  const html = document.documentElement ? document.documentElement.innerHTML.toLowerCase() : '';
  const blockers = [];
  const hasCaptchaWidget = Boolean(
    document.querySelector('[class*="captcha" i], [id*="captcha" i], iframe[src*="recaptcha" i], iframe[src*="hcaptcha" i]')
  );
  if (hasCaptchaWidget || text.includes('captcha') || html.includes('recaptcha') || html.includes('hcaptcha')) {
    blockers.push({ blocker_type: 'CAPTCHA', message: 'CAPTCHA challenge detected', confidence: hasCaptchaWidget ? 0.92 : 0.72 });
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


def fields_from_dom_snapshot(raw_fields: Any) -> list[BrowserField]:
    if not isinstance(raw_fields, list):
        return []
    parsed: list[BrowserField] = []
    for index, raw in enumerate(raw_fields):
        if not isinstance(raw, dict):
            continue
        label = str(raw.get("label") or "").strip()
        selector = raw.get("selector")
        field_type = str(raw.get("field_type") or "text").strip().lower()
        if not label:
            label = "Unlabeled field"
        confidence = 0.78 if selector else 0.45
        parsed.append(
            BrowserField(
                field_id=f"field:{index}:{field_type}:{label[:40].lower()}",
                label=label,
                field_type=field_type,
                selector=str(selector) if selector else None,
                required=bool(raw.get("required", False)),
                confidence=confidence,
                metadata=raw.get("metadata") if isinstance(raw.get("metadata"), dict) else {},
            )
        )
    return parsed


def build_apply_field_value_script(selector: str, value: str) -> str:
    selector_json = json.dumps(selector)
    value_json = json.dumps(value)
    return f"""
(() => {{
  const selector = {selector_json};
  const reviewedValue = {value_json};
  const normalize = (input) => String(input ?? '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, ' ')
    .trim();
  const dispatchChange = (element) => {{
    element.dispatchEvent(new Event('input', {{ bubbles: true }}));
    element.dispatchEvent(new Event('change', {{ bubbles: true }}));
  }};
  const labelFor = (element) => {{
    const id = element.getAttribute('id');
    if (id) {{
      const explicit = document.querySelector(`label[for="${{CSS.escape(id)}}"]`);
      if (explicit && explicit.innerText.trim()) return explicit.innerText.trim();
    }}
    const parentLabel = element.closest('label');
    if (parentLabel && parentLabel.innerText.trim()) return parentLabel.innerText.trim();
    return element.getAttribute('aria-label')
      || element.getAttribute('name')
      || element.getAttribute('value')
      || '';
  }};
  const parseBooleanIntent = (raw) => {{
    const normalized = normalize(raw);
    if (['yes', 'true', 'checked', 'check', '1', 'on', 'agree', 'accepted', 'accept'].includes(normalized)) return true;
    if (['no', 'false', 'unchecked', 'uncheck', '0', 'off', 'decline', 'declined', 'reject'].includes(normalized)) return false;
    return null;
  }};
  const element = document.querySelector(selector);
  if (!element) {{
    return JSON.stringify({{ ok: false, action: 'query', message: 'field not found' }});
  }}
  const tag = element.tagName.toLowerCase();
  const type = tag === 'input' ? (element.getAttribute('type') || 'text').toLowerCase() : tag;
  const normalizedReviewedValue = normalize(reviewedValue);
  if (!normalizedReviewedValue) {{
    return JSON.stringify({{ ok: false, action: 'apply', field_type: type, message: 'reviewed value is empty' }});
  }}

  if (tag === 'select') {{
    const options = Array.from(element.options || []).filter((option) => option.disabled !== true);
    const optionData = options.map((option) => ({{
      option,
      label: (option.textContent || '').trim(),
      value: option.getAttribute('value') || option.value || ''
    }}));
    const exact = optionData.find((entry) =>
      normalize(entry.label) === normalizedReviewedValue || normalize(entry.value) === normalizedReviewedValue
    );
    const partial = exact || optionData.find((entry) => {{
      const label = normalize(entry.label);
      const value = normalize(entry.value);
      return (label && (label.includes(normalizedReviewedValue) || normalizedReviewedValue.includes(label)))
        || (value && (value.includes(normalizedReviewedValue) || normalizedReviewedValue.includes(value)));
    }});
    if (!partial) {{
      return JSON.stringify({{
        ok: false,
        action: 'select_option',
        field_type: type,
        option_count: options.length,
        message: 'reviewed value did not match any select option'
      }});
    }}
    element.value = partial.option.value;
    dispatchChange(element);
    return JSON.stringify({{
      ok: true,
      action: 'select_option',
      field_type: type,
      selected_label: partial.label,
      selected_value_length: String(partial.option.value || '').length
    }});
  }}

  if (type === 'checkbox') {{
    const desired = parseBooleanIntent(reviewedValue);
    if (desired === null) {{
      return JSON.stringify({{
        ok: false,
        action: 'set_checkbox',
        field_type: type,
        message: 'checkbox answer must be reviewed as yes or no'
      }});
    }}
    element.checked = desired;
    dispatchChange(element);
    return JSON.stringify({{ ok: true, action: 'set_checkbox', field_type: type, checked: desired }});
  }}

  if (type === 'radio') {{
    const root = element.form || document;
    const name = element.getAttribute('name');
    const candidates = name
      ? Array.from(root.querySelectorAll(`input[type="radio"][name="${{CSS.escape(name)}}"]`))
      : [element];
    const match = candidates.find((candidate) => {{
      const value = normalize(candidate.getAttribute('value') || '');
      const label = normalize(labelFor(candidate));
      return value === normalizedReviewedValue
        || label === normalizedReviewedValue
        || (label && (label.includes(normalizedReviewedValue) || normalizedReviewedValue.includes(label)));
    }});
    if (!match) {{
      return JSON.stringify({{
        ok: false,
        action: 'set_radio',
        field_type: type,
        option_count: candidates.length,
        message: 'reviewed value did not match any radio option'
      }});
    }}
    match.checked = true;
    dispatchChange(match);
    return JSON.stringify({{
      ok: true,
      action: 'set_radio',
      field_type: type,
      selected_label: labelFor(match),
      selected_value_length: String(match.getAttribute('value') || '').length
    }});
  }}

  if ('value' in element) {{
    element.value = reviewedValue;
    dispatchChange(element);
    return JSON.stringify({{ ok: true, action: 'set_value', field_type: type }});
  }}
  return JSON.stringify({{ ok: false, action: 'apply', field_type: type, message: 'field type is not supported' }});
}})()
"""


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
  const matches = candidates
    .filter(isVisible)
    .map((element) => ({{ element, label: labelFor(element).trim(), normalized: normalize(labelFor(element)) }}))
    .filter((entry) => entry.normalized && !isFinalSubmitLike(entry.normalized))
    .filter((entry) => requested.some((label) => entry.normalized === label || entry.normalized.includes(label) || label.includes(entry.normalized)));
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
    for key in ("field_type", "checked", "option_count", "selected_value_length"):
        if key in payload:
            safe_payload[key] = payload[key]
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
