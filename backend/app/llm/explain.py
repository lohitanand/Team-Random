"""LLM-drafted explanation of an already-made decision, validated by guardrails, with fallback.

The LLM receives ONLY the evidence packet summary + the decided friction type + the decided actions.
"""
from __future__ import annotations

import json
from typing import Any

from backend.app.detection.rules import RULES_BY_NAME
from backend.app.llm.client import LLMClient, LLMError, load_prompt
from backend.app.llm.fallbacks import FRICTION_LABELS, fallback_explanation
from backend.app.llm.guardrails import validate
from backend.app.schemas.alerts import Decision
from backend.app.schemas.evidence import AggregatePacket, Packet
from backend.app.schemas.llm import Explanation, ExplanationOut


def _window(packet: AggregatePacket) -> str:
    return f"{packet.window_start:%d %b %H:%M} to {packet.window_end:%d %b %H:%M}"


def explanation_payload(packet: Packet, decision: Decision) -> dict[str, Any]:
    """The exact input the LLM sees (and that grounding is checked against)."""
    friction = decision.friction_type
    evidence: dict[str, Any] = {
        "rule_flags": packet.rule_flags,
        "rule_meanings": {f: RULES_BY_NAME[f].description for f in packet.rule_flags if f in RULES_BY_NAME},
        "top_signals": [s.model_dump() for s in packet.top_signals[:5]],
        "friction_probs": {friction: round(packet.friction_probs.get(friction, 0.0), 2)},
        "text_themes": packet.text_themes,
        "investigation_findings": [{"tool": f.tool, "summary": f.summary, "numbers": f.numbers}
                                   for f in packet.investigation_findings],
    }
    if isinstance(packet, AggregatePacket):
        evidence |= {"segment_type": packet.segment_type, "segment_value": packet.segment_value,
                     "metric": packet.metric, "window": _window(packet), "observed": packet.observed,
                     "baseline": packet.baseline, "multiplier": packet.multiplier, "z_score": packet.z_score,
                     "affected_sessions": packet.affected_sessions, "revenue_at_risk": packet.revenue_at_risk}
    else:
        ctx = packet.context
        evidence |= {"risk_score": round(packet.risk_score, 2), "cart_value": packet.cart_value,
                     "session_kind": packet.session_kind,
                     "context": {k: ctx.get(k) for k in ("device", "city_tier", "gateway", "payment_method",
                                                         "courier", "exit_step", "converted")},
                     "aggregate_context": {k: v for k, v in packet.aggregate_context.items()
                                           if k in ("segment_type", "segment", "metric", "multiplier",
                                                    "affected_sessions")}}
    return {
        "friction_type": decision.friction_type,
        "friction_label": FRICTION_LABELS[decision.friction_type],
        "confidence": decision.confidence,
        "priority": decision.priority,
        "owner_team": decision.owner_team,
        "team_action": {"id": decision.team_action.id, "description": decision.team_action.description},
        "customer_action": ({"id": decision.customer_action.id, "description": decision.customer_action.description}
                            if decision.customer_action else None),
        "evidence": evidence,
    }


def _allowed_terms(decision: Decision) -> list[str]:
    terms = list(decision.team_action.allows_terms)
    if decision.customer_action:
        terms += decision.customer_action.allows_terms
    return terms


def explain(packet: Packet, decision: Decision, client: LLMClient | None = None) -> Explanation:
    client = client or LLMClient()
    if not client.active:
        return fallback_explanation(packet, decision)
    payload = explanation_payload(packet, decision)
    try:
        raw = client.complete_json(load_prompt("explain"), json.dumps(payload, default=str))
    except LLMError as exc:
        return fallback_explanation(packet, decision, [f"llm_error: {str(exc)[:200]}"])

    action_ids = {decision.team_action.id} | ({decision.customer_action.id} if decision.customer_action else set())
    parsed, result = validate(raw, ExplanationOut, ["summary", "behavior_observed", "likely_business_cause"],
                              payload, decision.friction_type, action_ids, _allowed_terms(decision),
                              evidence_field="evidence_used")
    if parsed is None:
        return fallback_explanation(packet, decision, result.failures)
    return Explanation(**parsed.model_dump(), source="llm")
