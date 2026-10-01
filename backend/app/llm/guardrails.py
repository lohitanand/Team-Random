"""Guardrail validation for every LLM output (CLAUDE.md §7.7), in order:

1. Schema      - strict Pydantic parse of the JSON.
2. Grounding   - every number in the text appears in the payload the LLM was given;
                 every `evidence_used` key exists in that payload.
3. Consistency - the text does not name a different friction type or a different playbook action.
4. Policy      - no discount/refund/compensation/offer terms unless the decided action allows them;
                 no emails, phone numbers or customer/order/session IDs; no banned phrases.

Any failure -> the caller uses the deterministic fallback template.
"""
from __future__ import annotations

import json
import re
from collections.abc import Iterable
from typing import Any

from pydantic import BaseModel, ValidationError

from backend.app.decision.playbook import get_playbook
from backend.app.schemas.taxonomy import FRICTION_TYPES

NUMBER_RE = re.compile(r"(?<![A-Za-z_])\d[\d,]*(?:\.\d+)?%?")
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
PHONE_RE = re.compile(r"(?:\+91[\s-]?)?\b[6-9]\d{9}\b")
ID_RE = re.compile(r"\b(?:u_[0-9a-f]{6,}|s_\d{4,}(?:_\d+)?|o_\d{4,}|pay_\d{4,}|t_\d{4,}|c_\d{4,}|r_\d{4,})\b")
URL_RE = re.compile(r"https?://|www\.")

FRICTION_PHRASES: dict[str, list[str]] = {
    "unclear_product_info": ["unclear product info"],
    "delivery_uncertainty": ["delivery uncertainty"],
    "payment_failure": ["payment failure"],
    "poor_recommendations": ["poor recommendation"],
    "post_purchase_concern": ["post-purchase concern", "post purchase concern"],
    "price_shock": ["price shock", "hidden cost"],
    "coupon_failure": ["coupon failure"],
    "login_otp_issue": ["login/otp issue", "otp issue", "login issue"],
    "out_of_stock": ["out of stock", "out-of-stock"],
    "technical_glitch": ["technical glitch"],
}
OFFER_TERMS = ["discount", "% off", "cashback", "cash back", "voucher", "promo code", "coupon", "free gift",
               "gift card", "store credit", "compensation", "compensate", "refund", "reimburse", "waive",
               "free delivery", "free shipping", "reversed", "reversal"]
BANNED_PHRASES = ["guarantee", "promise", "100%", "lawsuit", "legal action", "your fault", "stupid", "idiot",
                  "damn", "shut up"]


class GuardrailResult(BaseModel):
    ok: bool
    failures: list[str]


# --- payload helpers ------------------------------------------------------------------

def _walk(value: Any, path: str = "") -> Iterable[tuple[str, Any]]:
    if isinstance(value, dict):
        for k, v in value.items():
            p = f"{path}.{k}" if path else str(k)
            yield p, v
            yield from _walk(v, p)
    elif isinstance(value, list):
        for v in value:
            yield from _walk(v, path)


def payload_numbers(payload: dict[str, Any]) -> list[float]:
    nums: list[float] = []
    for _, v in _walk(payload):
        if isinstance(v, bool):
            continue
        if isinstance(v, (int, float)):
            nums.append(float(v))
        elif isinstance(v, str):
            nums.extend(_parse(m) for m in NUMBER_RE.findall(v))
    return nums


def payload_keys(payload: dict[str, Any]) -> set[str]:
    keys: set[str] = set()
    for path, v in _walk(payload):
        keys.add(path)
        keys.add(path.rsplit(".", 1)[-1])
        if isinstance(v, str):
            keys.add(v)
    return keys


def _parse(token: str) -> float:
    return float(token.rstrip("%").replace(",", ""))


def _grounded(token: str, numbers: list[float]) -> bool:
    value = _parse(token)
    for n in numbers:
        if abs(value - n) <= 0.5 or (n and abs(value - n) / abs(n) <= 0.01):
            return True
        if token.endswith("%") or value > 1:  # 82% or "82 percent" of a 0.82 rate
            if abs(value / 100 - n) <= 0.005:
                return True
    return False


# --- checks ----------------------------------------------------------------------------

def parse_json(raw: str, schema: type[BaseModel]) -> tuple[BaseModel | None, list[str]]:
    try:
        data = json.loads(raw)
    except (TypeError, ValueError) as exc:
        return None, [f"schema: invalid JSON ({exc.__class__.__name__})"]
    try:
        return schema.model_validate(data), []
    except ValidationError as exc:
        return None, [f"schema: {err['loc']} {err['msg']}" for err in exc.errors()][:5]


def check_grounding(texts: list[str], payload: dict[str, Any], evidence_used: list[str] | None = None) -> list[str]:
    numbers = payload_numbers(payload)
    failures = [f"grounding: number '{tok}' is not in the evidence"
                for text in texts for tok in NUMBER_RE.findall(text) if not _grounded(tok, numbers)]
    if evidence_used is not None:
        keys = payload_keys(payload)
        failures += [f"grounding: evidence key '{k}' is not in the packet" for k in evidence_used if k not in keys]
    return failures


def check_consistency(texts: list[str], friction: str, action_ids: set[str], allowed_frictions: set[str]) -> list[str]:
    blob = " ".join(texts).lower()
    allowed_frictions = allowed_frictions | {friction}
    failures = []
    for other in FRICTION_TYPES:
        if other in allowed_frictions:
            continue
        if other in blob or any(phrase in blob for phrase in FRICTION_PHRASES[other]):
            failures.append(f"consistency: mentions a different friction type ({other})")
    for action_id in get_playbook().action_ids - action_ids:
        if action_id in blob:
            failures.append(f"consistency: mentions a different action ({action_id})")
    return failures


def check_policy(texts: list[str], allowed_terms: Iterable[str]) -> list[str]:
    blob = " ".join(texts)
    low = blob.lower()
    allowed = {t.lower() for t in allowed_terms}
    failures = [f"policy: offer/money term '{t}' is not allowed for this action"
                for t in OFFER_TERMS if t in low and not any(t in a or a in t for a in allowed)]
    failures += [f"policy: banned phrase '{p}'" for p in BANNED_PHRASES if p in low]
    if EMAIL_RE.search(blob):
        failures.append("policy: contains an email address")
    if PHONE_RE.search(blob):
        failures.append("policy: contains a phone number")
    if ID_RE.search(blob):
        failures.append("policy: contains a customer/session/order identifier")
    if URL_RE.search(low):
        failures.append("policy: contains a link")
    return failures


def validate(raw: str, schema: type[BaseModel], text_fields: list[str], payload: dict[str, Any], friction: str,
             action_ids: set[str], allowed_terms: Iterable[str], allowed_frictions: set[str] | None = None,
             evidence_field: str | None = None) -> tuple[BaseModel | None, GuardrailResult]:
    parsed, failures = parse_json(raw, schema)
    if parsed is None:
        return None, GuardrailResult(ok=False, failures=failures)
    texts = [getattr(parsed, f) for f in text_fields]
    evidence = getattr(parsed, evidence_field) if evidence_field else None
    failures = [
        *check_grounding(texts, payload, evidence),
        *check_consistency(texts, friction, action_ids, (allowed_frictions or set()) | {friction}),
        *check_policy(texts, allowed_terms),
    ]
    return (parsed if not failures else None), GuardrailResult(ok=not failures, failures=failures)
