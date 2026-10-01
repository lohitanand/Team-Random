"""Deterministic fallback explanations and messages, filled only from evidence packet fields.

Used when LLM_ENABLED=false, on any LLM error/timeout, and whenever a guardrail fails.
"""
from __future__ import annotations

from typing import Any

from backend.app.decision.playbook import get_playbook
from backend.app.detection.rules import RULES_BY_NAME
from backend.app.schemas.alerts import Decision, PlaybookAction
from backend.app.schemas.evidence import AggregatePacket, Packet
from backend.app.schemas.llm import CustomerMessage, Explanation

FRICTION_LABELS: dict[str, str] = {
    "unclear_product_info": "Unclear product information",
    "delivery_uncertainty": "Delivery uncertainty",
    "payment_failure": "Payment failures",
    "poor_recommendations": "Poor recommendations",
    "post_purchase_concern": "Post-purchase concerns",
    "price_shock": "Hidden costs / price shock",
    "coupon_failure": "Coupon failure",
    "login_otp_issue": "Forced login / OTP issues",
    "out_of_stock": "Out of stock / size unavailable",
    "technical_glitch": "Technical glitches",
}

LIKELY_CAUSES: dict[str, str] = {
    "unclear_product_info": "Product page is missing information customers need to decide (size chart, specs or attributes).",
    "delivery_uncertainty": "Delivery date or fee was unclear or too long for the customer's location.",
    "payment_failure": "Payment method or gateway instability, not price.",
    "poor_recommendations": "Search and recommendation slots are not surfacing relevant, in-stock items.",
    "post_purchase_concern": "Order status is not communicated well enough after purchase (delays, refunds or quality).",
    "price_shock": "Extra charges appear late in checkout, so the final total surprises the customer.",
    "coupon_failure": "Coupon rules or error messages do not match what customers expect.",
    "login_otp_issue": "Forced login and OTP delivery block customers from completing checkout.",
    "out_of_stock": "The wanted item or size is unavailable and alternatives are not compelling.",
    "technical_glitch": "A page or app error is blocking the customer from continuing.",
}

AGGREGATE_METRIC_LABELS = {
    "payment_session_failure_rate": "payment failure rate",
    "long_eta_share": "share of long delivery estimates",
    "delayed_order_share": "share of delayed orders",
    "size_chart_no_add_rate": "rate of size-chart views without add to cart",
    "negative_feedback_rate": "negative feedback rate",
    "error_session_rate": "error rate",
}


def _behaviour(packet: Packet) -> tuple[str, list[str]]:
    used: list[str] = []
    parts = [RULES_BY_NAME[f].description for f in packet.rule_flags if f in RULES_BY_NAME][:3]
    if parts:
        used.append("rule_flags")
    if isinstance(packet, AggregatePacket):
        label = AGGREGATE_METRIC_LABELS.get(packet.metric, packet.metric)
        parts.insert(0, f"{packet.segment_type} {packet.segment_value}: {label} at {packet.observed:.0%} "
                        f"vs {packet.baseline:.0%} baseline ({packet.multiplier}x) across "
                        f"{packet.affected_sessions} sessions")
        used += ["segment_value", "observed", "baseline", "multiplier", "affected_sessions"]
    elif not parts and packet.top_signals:
        parts.append("strongest signals: " + ", ".join(s.feature.replace("_", " ") for s in packet.top_signals[:3]))
        used.append("top_signals")
    if packet.text_themes:
        parts.append("customer feedback themes: " + ", ".join(t.replace("_", " ") for t in packet.text_themes[:3]))
        used.append("text_themes")
    return "; ".join(parts) or "detector signals", used


def fallback_explanation(packet: Packet, decision: Decision, failures: list[str] | None = None) -> Explanation:
    label = FRICTION_LABELS[decision.friction_type]
    behaviour, used = _behaviour(packet)
    cause = LIKELY_CAUSES[decision.friction_type]
    ctx = packet.aggregate_context if not isinstance(packet, AggregatePacket) else {}
    if ctx.get("segment_type"):
        cause += f" Linked anomaly: {ctx['segment_type']} {ctx['segment']} at {ctx['multiplier']}x baseline."
        used.append("aggregate_context")
    summary = f"{label} (confidence {decision.confidence:.2f}) routed to {decision.owner_team.replace('_', ' ')}."
    return Explanation(summary=summary, behavior_observed=behaviour[0].upper() + behaviour[1:] + ".",
                       likely_business_cause=cause, evidence_used=list(dict.fromkeys(used or ["friction_probs"])),
                       source="fallback", guardrail_failures=failures or [])


def message_slots(packet: Packet, product_name: str | None = None) -> dict[str, Any]:
    ctx = getattr(packet, "context", {}) or {}
    return {"product": product_name or "item", "method": ctx.get("payment_method") or "this method",
            "action": ""}


def fallback_message(action: PlaybookAction, packet: Packet, product_name: str | None = None,
                     failures: list[str] | None = None) -> CustomerMessage:
    template = get_playbook().template(action.template_id)
    slots = message_slots(packet, product_name) | {"action": action.description}
    return CustomerMessage(text=template.format(**slots)[:300], template_id=action.template_id, source="fallback",
                           guardrail_failures=failures or [])
