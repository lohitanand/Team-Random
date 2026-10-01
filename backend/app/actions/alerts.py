"""Team alerts (CLAUDE.md §7.9). High gate -> open with workflow triggers; medium -> needs_review."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from backend.app.audit.log import audit
from backend.app.db.models import AlertRow
from backend.app.llm.fallbacks import AGGREGATE_METRIC_LABELS, FRICTION_LABELS
from backend.app.schemas.alerts import Decision
from backend.app.schemas.evidence import AggregatePacket, Packet
from backend.app.schemas.llm import Explanation


def alert_title(decision: Decision, packet: Packet) -> str:
    label = FRICTION_LABELS[decision.friction_type]
    if isinstance(packet, AggregatePacket):
        metric = AGGREGATE_METRIC_LABELS.get(packet.metric, packet.metric)
        return (f"{label}: {packet.segment_type.replace('_', ' ')} {packet.segment_value} - {metric} "
                f"{packet.observed:.0%} vs {packet.baseline:.0%} ({packet.multiplier}x)")
    ctx = packet.context
    where = ", ".join(str(x) for x in (ctx.get("device"), ctx.get("city")) if x)
    return f"{label} - session {packet.session_id}" + (f" ({where})" if where else "")


def key_evidence(decision: Decision, packet: Packet) -> dict[str, Any]:
    ev: dict[str, Any] = {
        "rule_flags": packet.rule_flags,
        "top_signals": [s.model_dump() for s in packet.top_signals],
        "friction_prob": packet.friction_probs.get(decision.friction_type),
        "text_themes": packet.text_themes,
        "aggregate_context": packet.aggregate_context,
        "confidence_breakdown": decision.breakdown.model_dump(),
        "classification_source": decision.classification_source,
        "secondary_friction": decision.secondary_friction,
        "investigation_findings": [f.model_dump() for f in packet.investigation_findings],
    }
    if isinstance(packet, AggregatePacket):
        ev |= {"segment_type": packet.segment_type, "segment_value": packet.segment_value, "metric": packet.metric,
               "observed": packet.observed, "baseline": packet.baseline, "multiplier": packet.multiplier,
               "z_score": packet.z_score, "window_start": packet.window_start.isoformat(),
               "window_end": packet.window_end.isoformat(), "sample_sessions": packet.session_ids[:20]}
    else:
        ev |= {"risk_score": packet.risk_score, "cart_value": packet.cart_value, "context": packet.context}
    return ev


def create_alert(db: Session, decision: Decision, packet: Packet, explanation: Explanation,
                 source: str = "batch", now: datetime | None = None) -> AlertRow | None:
    if decision.gate == "low":
        return None
    now = now or datetime.now()
    row = AlertRow(
        packet_id=packet.packet_id, alert_type=packet.packet_type, source=source,
        title=alert_title(decision, packet)[:300], friction_type=decision.friction_type,
        confidence=decision.confidence, gate=decision.gate, priority=decision.priority, impact=decision.impact,
        owner_team=decision.owner_team, status="open" if decision.gate == "high" else "needs_review",
        revenue_at_risk=decision.revenue_at_risk, affected_sessions=decision.customers_affected,
        session_id=getattr(packet, "session_id", None), explanation=explanation.model_dump(),
        key_evidence=key_evidence(decision, packet), team_action=decision.team_action.model_dump(),
        customer_action=decision.customer_action.model_dump() if decision.customer_action else None,
        created_at=now, updated_at=now,
    )
    db.add(row)
    db.flush()
    audit(db, "alert_created", "alert", str(row.id),
          {"packet_id": packet.packet_id, "gate": decision.gate, "priority": decision.priority,
           "explanation_source": explanation.source, "guardrail_failures": explanation.guardrail_failures}, ts=now)
    return row


def alert_dict(row: AlertRow) -> dict[str, Any]:
    return {c: getattr(row, c) for c in (
        "id", "packet_id", "alert_type", "source", "title", "friction_type", "confidence", "gate", "priority",
        "impact", "owner_team", "status", "revenue_at_risk", "affected_sessions", "session_id", "explanation",
        "key_evidence", "team_action", "customer_action", "assigned_to", "created_at", "updated_at")}
