"""Alerts: list, detail (evidence, findings, workflow history, audit trail), workflow actions, AI draft."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.app.actions.alerts import alert_dict
from backend.app.actions.workflows import WorkflowError, execute
from backend.app.api.insights import clear_cache
from backend.app.audit.log import audit, trail
from backend.app.db.models import AlertRow, CsDraftRow, PacketRow, RecoveryRow, WorkflowRow
from backend.app.db.session import get_db
from backend.app.decision.routing import TEAM_VIEWS
from backend.app.llm.explain import explain
from backend.app.schemas.alerts import Decision, WorkflowRequest
from backend.app.schemas.evidence import AggregatePacket, SessionPacket

router = APIRouter(tags=["alerts"])


def load_packet(row: PacketRow) -> tuple[SessionPacket | AggregatePacket, Decision]:
    model = AggregatePacket if row.packet_type == "aggregate" else SessionPacket
    return model.model_validate(row.payload), Decision.model_validate(row.decision)


@router.get("/alerts")
def list_alerts(team: str | None = None, status: str | None = None, gate: str | None = None,
                friction: str | None = None, alert_type: str | None = None, source: str | None = None,
                limit: int = 50, offset: int = 0, db: Session = Depends(get_db)) -> dict[str, Any]:
    q = db.query(AlertRow)
    if team:
        q = q.filter(AlertRow.owner_team.in_(TEAM_VIEWS.get(team, [team])))
    if status:
        q = q.filter(AlertRow.status.in_(status.split(",")))
    if gate:
        q = q.filter(AlertRow.gate == gate)
    if friction:
        q = q.filter(AlertRow.friction_type == friction)
    if alert_type:
        q = q.filter(AlertRow.alert_type == alert_type)
    if source:
        q = q.filter(AlertRow.source == source)
    total = q.count()
    rows = (q.order_by(AlertRow.alert_type.asc(), AlertRow.impact.desc(), AlertRow.created_at.desc())
            .offset(offset).limit(min(limit, 200)).all())
    return {"total": total, "items": [{k: v for k, v in alert_dict(r).items() if k not in ("key_evidence",)}
                                      for r in rows]}


@router.get("/alerts/{alert_id}")
def get_alert(alert_id: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    alert = db.get(AlertRow, alert_id)
    if alert is None:
        raise HTTPException(404, "alert not found")
    workflows = db.query(WorkflowRow).filter(WorkflowRow.alert_id == alert_id).order_by(WorkflowRow.id).all()
    recoveries = db.query(RecoveryRow).filter(RecoveryRow.packet_id == alert.packet_id).all()
    drafts = db.query(CsDraftRow).filter(CsDraftRow.alert_id == alert_id).order_by(CsDraftRow.id.desc()).all()
    ids = [str(alert_id), alert.packet_id] + ([alert.session_id] if alert.session_id else [])
    return {
        **alert_dict(alert),
        "workflows": [{"id": w.id, "action": w.action, "actor": w.actor, "assignee": w.assignee, "note": w.note,
                       "result": w.result, "created_at": w.created_at} for w in workflows],
        "recoveries": [{"id": r.id, "session_id": r.session_id, "action_id": r.action_id, "moment": r.moment,
                        "channel": r.channel, "status": r.status, "message": r.message, "outcome": r.outcome,
                        "holdout": r.holdout} for r in recoveries],
        "cs_drafts": [{"id": d.id, "draft": d.draft, "source": d.source, "status": d.status,
                       "created_at": d.created_at} for d in drafts],
        "audit_trail": trail(db, ids),
    }


@router.post("/alerts/{alert_id}/actions")
def alert_action(alert_id: int, req: WorkflowRequest, db: Session = Depends(get_db)) -> dict[str, Any]:
    alert = db.get(AlertRow, alert_id)
    if alert is None:
        raise HTTPException(404, "alert not found")
    try:
        row = execute(db, alert, req)
    except WorkflowError as exc:
        raise HTTPException(409, str(exc)) from exc
    db.commit()
    clear_cache()
    return {"alert": alert_dict(alert), "execution": {"id": row.id, "action": row.action, "result": row.result}}


@router.post("/alerts/{alert_id}/explain")
def redraft_explanation(alert_id: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    """Ask the LLM to draft the explanation (guardrails + fallback). Works with LLM disabled too."""
    alert = db.get(AlertRow, alert_id)
    row = db.get(PacketRow, alert.packet_id) if alert else None
    if row is None:
        raise HTTPException(404, "alert not found")
    packet, decision = load_packet(row)
    explanation = explain(packet, decision)
    alert.explanation = explanation.model_dump()
    audit(db, "explanation_drafted", "alert", str(alert_id),
          {"source": explanation.source, "guardrail_failures": explanation.guardrail_failures})
    db.commit()
    return explanation.model_dump()
