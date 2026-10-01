"""Customer recovery (CLAUDE.md §7.9): moment + channel from the playbook, 10% holdout, consent,
frequency cap (max N messages per user per 24h). auto_allowed actions run only at high confidence;
everything else goes to customer service for approval."""
from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from backend.app.audit.holdout import has_consent, in_holdout
from backend.app.audit.log import audit
from backend.app.audit.outcomes import simulate_outcome
from backend.app.config import Settings, get_settings
from backend.app.db.models import RecoveryRow
from backend.app.decision.playbook import get_playbook
from backend.app.llm.client import LLMClient
from backend.app.llm.messages import draft_message
from backend.app.schemas.alerts import Decision
from backend.app.schemas.evidence import SessionPacket

ACTIVE = ("sent", "approved", "pending_approval")


def recent_messages(db: Session, user_id: str, now: datetime) -> int:
    return db.query(RecoveryRow).filter(RecoveryRow.user_id == user_id, RecoveryRow.status.in_(ACTIVE),
                                        RecoveryRow.created_at >= now - timedelta(hours=24),
                                        RecoveryRow.created_at <= now).count()


def eligible(packet: SessionPacket, decision: Decision) -> bool:
    if decision.gate == "low":
        return False
    return packet.session_kind == "post_purchase" or not packet.context.get("converted")


def plan_recovery(db: Session, decision: Decision, packet: SessionPacket, moment: str, now: datetime,
                  product_name: str | None = None, client: LLMClient | None = None, simulate: bool = True,
                  sent_in_24h: int | None = None, settings: Settings | None = None) -> RecoveryRow | None:
    s = settings or get_settings()
    if not eligible(packet, decision):
        return None
    action = get_playbook().customer_action(decision.friction_type, packet, moment)
    if action is None:
        return None
    value = float(packet.context.get("order_value") or packet.cart_value or 0.0)
    row = RecoveryRow(session_id=packet.session_id, user_id=packet.user_id, packet_id=packet.packet_id,
                      friction_type=decision.friction_type, action_id=action.id, moment=moment,
                      channel=action.channel, auto=False, holdout=False, value=value, created_at=now)
    if in_holdout(packet.session_id, s.holdout_share):
        row.status, row.holdout = "holdout", True
    elif not has_consent(packet.user_id):
        row.status = "suppressed_consent"
    elif (sent_in_24h if sent_in_24h is not None else recent_messages(db, packet.user_id, now)) \
            >= s.recovery_max_messages_per_user_24h:
        row.status = "suppressed_cap"
    else:
        auto = decision.gate == "high" and action.auto_allowed
        row.status, row.auto = ("sent" if auto else "pending_approval"), auto
        msg = draft_message(action, packet, decision.friction_type, product_name, client)
        row.message, row.message_source = msg.text, msg.source
        audit(db, "recovery_message_drafted", "session", packet.session_id,
              {"action_id": action.id, "source": msg.source, "guardrail_failures": msg.guardrail_failures}, ts=now)
    if simulate and row.status in ("sent", "holdout"):
        row.outcome = "recovered" if simulate_outcome(packet.session_id, decision.friction_type,
                                                      treated=row.status == "sent") else "not_recovered"
    db.add(row)
    audit(db, "recovery_planned", "session", packet.session_id,
          {"action_id": action.id, "status": row.status, "moment": moment, "channel": action.channel,
           "holdout": row.holdout}, ts=now)
    return row
