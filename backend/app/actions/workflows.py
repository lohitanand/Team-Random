"""Workflow triggers on alerts (approve / assign / create_ticket / dismiss / resolve).

Executing a trigger only SIMULATES it: it writes an execution record; nothing external is called.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from backend.app.audit.log import audit
from backend.app.audit.outcomes import simulate_outcome
from backend.app.db.models import AlertRow, RecoveryRow, WorkflowRow
from backend.app.schemas.alerts import WorkflowRequest

OPEN_STATES = {"open", "needs_review", "approved", "assigned"}
TRANSITIONS: dict[str, tuple[set[str], str | None]] = {
    "approve": ({"open", "needs_review", "assigned"}, "approved"),
    "assign": ({"open", "needs_review", "approved"}, "assigned"),
    "create_ticket": (OPEN_STATES, None),
    "dismiss": (OPEN_STATES, "dismissed"),
    "resolve": ({"approved", "assigned"}, "resolved"),
}


class WorkflowError(ValueError):
    pass


def execute(db: Session, alert: AlertRow, req: WorkflowRequest) -> WorkflowRow:
    allowed, target = TRANSITIONS[req.action]
    if alert.status not in allowed:
        raise WorkflowError(f"cannot {req.action} an alert that is {alert.status}")
    now = datetime.now()
    result: dict = {"simulated": True, "from_status": alert.status}
    if req.action == "assign":
        alert.assigned_to = req.assignee or f"{alert.owner_team}_queue"
        result["assignee"] = alert.assigned_to
    if req.action == "create_ticket":
        n = db.query(WorkflowRow).filter(WorkflowRow.action == "create_ticket").count() + 1
        result["ticket_ref"] = f"TKT-{alert.id:05d}-{n:03d}"
    if req.action == "approve":
        pending = db.query(RecoveryRow).filter(RecoveryRow.packet_id == alert.packet_id,
                                               RecoveryRow.status == "pending_approval").all()
        for r in pending:
            r.status, r.approved_by = "approved", req.actor
            r.outcome = "recovered" if simulate_outcome(r.session_id, r.friction_type, True) else "not_recovered"
            audit(db, "recovery_approved", "recovery", str(r.id), {"action_id": r.action_id}, actor=req.actor)
        result["recoveries_approved"] = len(pending)
    if target:
        alert.status = target
    alert.updated_at = now
    result["to_status"] = alert.status
    row = WorkflowRow(alert_id=alert.id, action=req.action, actor=req.actor, assignee=req.assignee,
                      note=req.note, result=result, created_at=now)
    db.add(row)
    audit(db, f"workflow_{req.action}", "alert", str(alert.id), result | {"note": req.note}, actor=req.actor)
    return row
