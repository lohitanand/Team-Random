"""Dashboard read endpoints: overview, team insights, evaluation."""
from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.app.api.deps import get_state
from backend.app.api.insights import overview, team_insights
from backend.app.audit.outcomes import recovery_stats
from backend.app.config import REPORTS_DIR
from backend.app.db.models import AlertRow, AuditRow, RecoveryRow
from backend.app.db.session import get_db
from backend.app.decision.routing import TEAM_VIEWS

router = APIRouter(tags=["dashboard"])


@router.get("/overview")
def get_overview(db: Session = Depends(get_db)) -> dict[str, Any]:
    return overview(get_state().store, db)


@router.get("/teams/{team}/insights")
def get_team(team: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    if team not in TEAM_VIEWS:
        raise HTTPException(404, f"unknown team; use one of {sorted(TEAM_VIEWS)}")
    return team_insights(team, get_state().store, db)


@router.get("/eval")
def get_eval(db: Session = Depends(get_db)) -> dict[str, Any]:
    path = REPORTS_DIR / "eval.json"
    report = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    drafts = db.query(AuditRow.event_type, AuditRow.payload).filter(
        AuditRow.event_type.in_(["alert_created", "recovery_message_drafted", "explanation_drafted"])).all()
    llm_total = llm_passed = 0
    for _, payload in drafts:
        source = (payload or {}).get("explanation_source") or (payload or {}).get("source")
        failures = (payload or {}).get("guardrail_failures") or []
        if source == "llm" or failures:
            llm_total += 1
            llm_passed += source == "llm" and not failures
    alerts = db.query(AlertRow.gate, func.count()).group_by(AlertRow.gate).all()
    gates = {g: n for g, n in alerts}
    report["llm_outputs"] = {"drafted": llm_total, "passed_guardrails": llm_passed,
                             "pass_rate": round(llm_passed / llm_total, 4) if llm_total else None}
    report["alert_quality"] = {"alerts": sum(gates.values()), "by_gate": gates,
                               "high_confidence_share": round(gates.get("high", 0) / max(sum(gates.values()), 1), 4)}
    report["holdout"] = recovery_stats(db)
    report["recovery_rows"] = db.query(RecoveryRow).count()
    return report
