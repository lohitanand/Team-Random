"""Decision layer entrypoint: classify -> confidence -> gate -> route -> priority -> playbook.

No LLM calls. A medium-confidence decision is handed to the (read-only) investigator, whose
enriched packet is re-scored by the same deterministic functions.
"""
from __future__ import annotations

from collections.abc import Callable

from backend.app.config import Settings, get_settings
from backend.app.decision.classify import classify
from backend.app.decision.confidence import confidence
from backend.app.decision.gating import gate
from backend.app.decision.playbook import Playbook, default_moment, get_playbook
from backend.app.decision.priority import impact, priority, trend_factor
from backend.app.decision.routing import route
from backend.app.schemas.alerts import Decision
from backend.app.schemas.evidence import AggregatePacket, Packet

Investigator = Callable[[Packet, Decision], Packet]


def _exposure(packet: Packet) -> tuple[float, int, float]:
    """(revenue_at_risk, customers_affected, trend_factor) for the priority formula."""
    if isinstance(packet, AggregatePacket):
        return packet.revenue_at_risk, packet.affected_sessions, trend_factor(packet.multiplier)
    ctx = packet.context
    if packet.session_kind == "post_purchase":
        revenue = float(ctx.get("order_value") or 0.0)
    else:
        revenue = 0.0 if ctx.get("converted") else packet.cart_value
    return revenue, 1, trend_factor(packet.aggregate_context.get("multiplier"))


def decide_once(packet: Packet, settings: Settings | None = None, playbook: Playbook | None = None,
                moment: str | None = None) -> Decision:
    s = settings or get_settings()
    book = playbook or get_playbook()
    cls = classify(packet, s)
    breakdown = confidence(packet, cls.primary, s)
    revenue, customers, trend = _exposure(packet)
    score = impact(revenue, customers, trend)
    g = gate(breakdown.score, s)
    return Decision(
        packet_id=packet.packet_id, packet_type=packet.packet_type, friction_type=cls.primary,
        secondary_friction=cls.secondary, classification_source=cls.source, confidence=breakdown.score,
        breakdown=breakdown, gate=g, owner_team=route(cls.primary), priority=priority(score, s),
        impact=score, revenue_at_risk=round(revenue, 2), customers_affected=customers, trend_factor=trend,
        customer_action=book.customer_action(cls.primary, packet, moment or default_moment(packet)),
        team_action=book.team_action(cls.primary, packet), needs_review=g == "medium",
    )


def decide(packet: Packet, investigator: Investigator | None = None, settings: Settings | None = None,
           moment: str | None = None) -> tuple[Decision, Packet]:
    decision = decide_once(packet, settings, moment=moment)
    if decision.gate == "medium" and investigator is not None:
        enriched = investigator(packet, decision)
        decision = decide_once(enriched, settings, moment=moment)
        decision.investigated = True
        packet = enriched
    return decision, packet
