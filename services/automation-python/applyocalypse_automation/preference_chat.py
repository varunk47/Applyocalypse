"""Turns a chat message into preferences the user can save.

The model reads the message when one is configured; otherwise, or when the
model's answer is unusable, plain phrasings are read by rules. Nothing here
saves anything: the app shows each proposal and the user picks what to keep.

Proposal shapes (the renderer saves them through the matching contract):
  {"type": "answer_rule", "question", "answer", "conditions": {location?, company?, portal?}}
  {"type": "job_filter", "kind", "value"}
  {"type": "address", "label", "addressLine1", "addressLine2", "city", "state", "postalCode", "country"}
"""

from __future__ import annotations

import json
import os
import re
from typing import Any

from .llm.litellm_client import LiteLlmClient

FILTER_KINDS: tuple[str, ...] = ("skip_company", "skip_keyword", "min_salary", "work_arrangement", "place")
ARRANGEMENTS: tuple[str, ...] = ("remote", "hybrid", "onsite")
CONDITION_KEYS: tuple[str, ...] = ("location", "company", "portal")
ADDRESS_KEYS: tuple[str, ...] = ("label", "addressLine1", "addressLine2", "city", "state", "postalCode", "country")

NO_MODEL_HINT = (
    "Add a model key in Settings and I can read anything you write. Until then I understand phrasings like "
    '"skip jobs at Initech", "skip anything mentioning clearance", "minimum salary 120k", "remote or hybrid only", '
    '"only jobs in Denver", "I also live at 1 Beacon St, Boston, MA 02108" and '
    '"when they ask about notice period, say 2 weeks".'
)

SYSTEM_PROMPT = f"""You help a job seeker record preferences that an application assistant applies later.
Read the user's message and propose preferences to save. Reply with JSON only:
{{"reply": "<one or two short sentences>", "proposals": [<proposal>, ...]}}

A proposal is one of:
- {{"type": "answer_rule", "question": "<words the form question uses>", "answer": "<what to answer>",
   "conditions": {{"location"?: "<place>", "company"?: "<company>", "portal"?: "<portal>"}}}}
  for a standing answer to an application question, optionally only for some jobs.
- {{"type": "job_filter", "kind": one of {list(FILTER_KINDS)}, "value": "<value>"}}
  skip_company: a company never to apply to. skip_keyword: a word that rules a job out.
  min_salary: the lowest acceptable salary as digits only. work_arrangement: one of {list(ARRANGEMENTS)},
  one proposal per allowed arrangement. place: a city, state or country onsite jobs must be in.
- {{"type": "address", "label": "<Home, Parents...>", "addressLine1", "addressLine2", "city", "state",
   "postalCode", "country"}} for another place the user lives or can work from. city is required.

Only propose what the user actually said. Never invent answers to demographic, disability, veteran,
criminal history or legal questions. If nothing in the message is a preference, return no proposals
and say so in reply. Never use em dashes."""


def _clean(value: object, limit: int = 200) -> str:
    text = value.strip() if isinstance(value, str) else ""
    return re.sub(r"\s*—\s*", ", ", text)[:limit]


def normalize_proposal(raw: object) -> dict[str, Any] | None:
    """A proposal the app can save, or None when the shape or values are unusable."""
    if not isinstance(raw, dict):
        return None
    kind = raw.get("type")
    if kind == "answer_rule":
        question, answer = _clean(raw.get("question"), 500), _clean(raw.get("answer"), 2000)
        if not question or not answer:
            return None
        given = raw.get("conditions") if isinstance(raw.get("conditions"), dict) else {}
        conditions = {key: _clean(given.get(key)) for key in CONDITION_KEYS if _clean(given.get(key))}
        return {"type": "answer_rule", "question": question, "answer": answer, "conditions": conditions}
    if kind == "job_filter":
        filter_kind, value = raw.get("kind"), _clean(raw.get("value"))
        if filter_kind not in FILTER_KINDS or not value:
            return None
        if filter_kind == "min_salary":
            value = _salary_digits(value) or ""
        elif filter_kind == "work_arrangement":
            value = value.lower().replace("-", "").replace(" ", "")
            value = value if value in ARRANGEMENTS else ""
        return {"type": "job_filter", "kind": filter_kind, "value": value} if value else None
    if kind == "address":
        address = {key: _clean(raw.get(key)) for key in ADDRESS_KEYS}
        return {"type": "address", **address} if address["city"] else None
    return None


def _salary_digits(text: str) -> str | None:
    match = re.search(r"\$?\s*(\d[\d,.]*)\s*(k)?\b", text, re.IGNORECASE)
    if not match:
        return None
    digits = re.sub(r"[,.]", "", match.group(1))
    if not digits.isdigit():
        return None
    value = int(digits) * (1000 if match.group(2) and int(digits) < 1000 else 1)
    return str(value) if 1000 <= value <= 5_000_000 else None


# ── Rules for when no model is available ──────────────────────────────────────

_COMPANY = re.compile(
    r"\b(?:skip|avoid|exclude|never apply to|don'?t apply to|do not apply to)\s+"
    r"(?:any\s+)?(?:jobs?|roles?|positions?|anything)?\s*(?:at|from|with)\s+(?P<name>[^.;!?]+)",
    re.IGNORECASE,
)
_COMPANY_BARE = re.compile(r"\b(?:never apply to|don'?t apply to|do not apply to)\s+(?P<name>[^.;!?]+)", re.IGNORECASE)
_KEYWORD = re.compile(
    r"\b(?:skip|avoid|exclude)\s+(?:any\s+)?(?:jobs?|roles?|positions?|anything)\s+"
    r"(?:that\s+)?(?:mention(?:s|ing)?|with|requiring|that require|about|containing)\s+(?P<word>[^.;!?]+)",
    re.IGNORECASE,
)
_SALARY = re.compile(
    r"\b(?:minimum|min\.?|at least|no less than|not less than|floor of)\b[^.;!?\d$]{0,25}(?P<amount>\$?\s*\d[\d,.]*\s*k?)",
    re.IGNORECASE,
)
_ARRANGEMENT_WORD = re.compile(r"\b(remote|hybrid|on[- ]?site|in[- ]office)\b", re.IGNORECASE)
_ARRANGEMENT_INTENT = re.compile(r"\b(only|just|want|prefer)\b", re.IGNORECASE)
_PLACE = re.compile(
    r"\bonly\s+(?:want\s+)?(?:jobs?|roles?|positions?|work)?\s*(?:in|near|around)\s+(?P<place>[^.;!?]+)",
    re.IGNORECASE,
)
_ADDRESS = re.compile(
    r"(?P<line1>\d+[\w .'-]*?\b(?:st|street|ave|avenue|rd|road|blvd|boulevard|dr|drive|ln|lane|way|ct|court|pl|place|pkwy|parkway)\b\.?)"
    r"(?:,?\s*(?P<line2>(?:apt|apartment|suite|ste|unit|#)\s*[\w-]+))?"
    r",\s*(?P<city>[A-Za-z .'-]+?),\s*(?P<state>[A-Z]{2})\b(?:\s+(?P<zip>\d{5}(?:-\d{4})?))?",
    re.IGNORECASE,
)
_ADDRESS_LABEL = re.compile(r"\b(?:my\s+)?(?P<label>home|parents'?|family|work|office|second|other)\b", re.IGNORECASE)
_ANSWER = re.compile(
    r"\b(?:when|if|whenever)\s+(?:they|a form|the form|an application|it|a portal)?\s*asks?\s+"
    r"(?:me\s+)?(?:about|for|whether|if)?\s*(?P<question>.+?),?\s+"
    r"(?:say|answer|put|use|tell them|write|choose|pick)\s+(?P<answer>[^.;!?]+)",
    re.IGNORECASE,
)
_AT_COMPANY = re.compile(r"\s+(?:for|at)\s+(?P<company>[A-Z][\w&.-]*(?:\s+[A-Z][\w&.-]*)*)\s*(?:jobs?|roles?)?$")


def _names(text: str) -> list[str]:
    """ "Initech, Globex and Hooli" becomes three names."""
    parts = re.split(r",\s*|\s+(?:and|or)\s+", text.strip())
    return [part.strip(" \"'") for part in parts if part.strip(" \"'")]


def _clauses(message: str) -> list[str]:
    return [clause.strip() for clause in re.split(r"(?<=[.;!?])\s+|\n+", message) if clause.strip()]


def _rule_proposals(clause: str) -> list[dict[str, Any]]:
    answer = _ANSWER.search(clause)
    if answer:
        text = answer.group("answer").strip()
        conditions: dict[str, str] = {}
        at_company = _AT_COMPANY.search(text)
        if at_company:
            conditions["company"] = at_company.group("company")
            text = text[: at_company.start()].strip()
        return [{"type": "answer_rule", "question": answer.group("question"), "answer": text.strip(" \"'"),
                 "conditions": conditions}]

    address = _ADDRESS.search(clause)
    if address:
        label = _ADDRESS_LABEL.search(clause[: address.start()])
        return [{
            "type": "address",
            "label": label.group("label").capitalize() if label else "",
            "addressLine1": address.group("line1"),
            "addressLine2": address.group("line2") or "",
            "city": address.group("city"),
            "state": address.group("state").upper(),
            "postalCode": address.group("zip") or "",
            "country": "",
        }]

    keyword = _KEYWORD.search(clause)
    if keyword:
        return [{"type": "job_filter", "kind": "skip_keyword", "value": word} for word in _names(keyword.group("word"))]

    company = _COMPANY.search(clause) or _COMPANY_BARE.search(clause)
    if company:
        return [{"type": "job_filter", "kind": "skip_company", "value": name} for name in _names(company.group("name"))]

    proposals: list[dict[str, Any]] = []
    salary = _SALARY.search(clause)
    if salary and re.search(r"\b(salary|pay|compensation|base|comp)\b", clause, re.IGNORECASE):
        proposals.append({"type": "job_filter", "kind": "min_salary", "value": salary.group("amount")})

    place = _PLACE.search(clause)
    if place:
        proposals.extend({"type": "job_filter", "kind": "place", "value": name} for name in _names(place.group("place")))

    if _ARRANGEMENT_INTENT.search(clause):
        words = {w.lower().replace("-", "").replace(" ", "") for w in _ARRANGEMENT_WORD.findall(clause)}
        words = {"onsite" if w == "inoffice" else w for w in words}
        proposals.extend(
            {"type": "job_filter", "kind": "work_arrangement", "value": a} for a in ARRANGEMENTS if a in words
        )
    return proposals


def rule_proposals(message: str) -> list[dict[str, Any]]:
    found = [normalize_proposal(raw) for clause in _clauses(message) for raw in _rule_proposals(clause)]
    return _dedupe([proposal for proposal in found if proposal])


def _dedupe(proposals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    unique = []
    for proposal in proposals:
        key = json.dumps(proposal, sort_keys=True).lower()
        if key not in seen:
            seen.add(key)
            unique.append(proposal)
    return unique


def _rule_reply(proposals: list[dict[str, Any]], had_model: bool) -> str:
    if proposals:
        noun = "preference" if len(proposals) == 1 else "preferences"
        return f"Here {'is' if len(proposals) == 1 else 'are'} {len(proposals)} {noun} to save. Keep the ones you want."
    if had_model:
        return "I could not find a preference in that. Tell me what to skip, what to answer, or where you can work."
    return "I could not read that as a preference yet. " + NO_MODEL_HINT


async def chat_preferences(
    message: str,
    known: dict[str, Any] | None = None,
    client: LiteLlmClient | None = None,
) -> dict[str, Any]:
    """{"reply", "proposals", "source"}; source says whether the model or the rules answered."""
    model = os.getenv("LITELLM_MODEL_FAST") or os.getenv("LITELLM_MODEL")
    llm = client or (LiteLlmClient(model=model) if model else None)
    if llm is not None:
        try:
            data = await llm.complete_json(
                system=SYSTEM_PROMPT,
                user=json.dumps({"already_saved": known or {}, "message": message}),
                schema_name="preference_chat",
            )
            if isinstance(data, str):
                data = json.loads(data)
            raw = data.get("proposals") if isinstance(data, dict) else None
            if isinstance(raw, list):
                proposals = _dedupe([p for p in (normalize_proposal(item) for item in raw) if p])
                reply = _clean(data.get("reply"), 600) or _rule_reply(proposals, had_model=True)
                return {"reply": reply, "proposals": proposals, "source": "model"}
        except Exception:  # noqa: BLE001 - any model failure falls back to the rules below
            pass
    proposals = rule_proposals(message)
    return {"reply": _rule_reply(proposals, had_model=llm is not None), "proposals": proposals, "source": "rules"}
