"""Audit log: every decision, alert, LLM draft, workflow step, recovery and agent tool call."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from backend.app.db.models import AuditRow


def audit(db: Session, event_type: str, entity_type: str, entity_id: str, payload: dict[str, Any] | None = None,
          actor: str = "system", ts: datetime | None = None) -> AuditRow:
    row = AuditRow(event_type=event_type, entity_type=entity_type, entity_id=str(entity_id), actor=actor,
                   payload=payload or {}, ts=ts or datetime.now())
    db.add(row)
    return row


def trail(db: Session, entity_ids: list[str], limit: int = 100) -> list[dict[str, Any]]:
    rows = (db.query(AuditRow).filter(AuditRow.entity_id.in_(entity_ids))
            .order_by(AuditRow.ts.desc(), AuditRow.id.desc()).limit(limit).all())
    return [{"id": r.id, "ts": r.ts.isoformat(), "event_type": r.event_type, "entity_type": r.entity_type,
             "entity_id": r.entity_id, "actor": r.actor, "payload": r.payload} for r in rows]
