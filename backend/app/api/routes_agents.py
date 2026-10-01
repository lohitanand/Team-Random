"""Agents: investigation (re-scored deterministically), CS reply drafts (human approval), analyst Q&A."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.app.actions.alerts import key_evidence
from backend.app.agents.analyst import ask
from backend.app.agents.cs_copilot import draft_reply, gather
from backend.app.api.deps import get_state
from backend.app.api.insights import clear_cache
from backend.app.api.routes_alerts import load_packet
from backend.app.audit.log import audit
from backend.app.db.models import AlertRow, CsDraftRow, PacketRow
from backend.app.db.session import get_db
from backend.app.decision.engine import decide_once

router = APIRouter(prefix="/agents", tags=["agents"])


def _tool_logger(db: Session, entity: str, agent: str):
    def log(name: str, args: dict[str, Any], result: dict[str, Any]) -> None:
        audit(db, "agent_tool_call", "agent", entity, {"agent": agent, "tool": name, "args": args,
                                                       "result_keys": sorted(result)[:12]}, actor=agent)
    return log


@router.post("/investigate/{packet_id}")
def investigate(packet_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    row = db.get(PacketRow, packet_id)
    if row is None:
        raise HTTPException(404, "packet not found")
    packet, before = load_packet(row)
    agent = get_state().investigator(on_tool_call=_tool_logger(db, packet_id, "investigator"))
    enriched = agent(packet, before)
    after = decide_once(enriched)
    after.investigated = True
    row.payload, row.decision = enriched.model_dump(mode="json"), after.model_dump(mode="json")
    row.gate, row.confidence = after.gate, after.confidence
    alert = db.query(AlertRow).filter(AlertRow.packet_id == packet_id).first()
    if alert is not None and alert.status in ("open", "needs_review"):
        alert.confidence, alert.gate = after.confidence, after.gate
        alert.status = "open" if after.gate == "high" else "needs_review" if after.gate == "medium" else alert.status
        alert.key_evidence = key_evidence(after, enriched)
    audit(db, "investigation", "packet", packet_id, {"before": before.confidence, "after": after.confidence,
                                                     "findings": len(enriched.investigation_findings)})
    db.commit()
    clear_cache()
    return {"packet_id": packet_id, "before": {"confidence": before.confidence, "gate": before.gate},
            "after": {"confidence": after.confidence, "gate": after.gate, "breakdown": after.breakdown.model_dump()},
            "findings": [f.model_dump() for f in enriched.investigation_findings]}


@router.post("/cs-draft/{alert_id}")
def cs_draft(alert_id: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    alert = db.get(AlertRow, alert_id)
    if alert is None:
        raise HTTPException(404, "alert not found")
    session_id = alert.session_id or ((alert.key_evidence or {}).get("sample_sessions") or [None])[0]
    if not session_id:
        raise HTTPException(409, "no customer session linked to this alert")
    state = get_state()
    ctx = gather(state.tools, session_id)
    action_id = (alert.customer_action or {}).get("id")
    reply, source, failures = draft_reply(ctx, alert.friction_type, action_id)
    draft = CsDraftRow(alert_id=alert_id, session_id=session_id, draft=reply, source=source, context=ctx,
                       status="pending_approval")
    db.add(draft)
    db.flush()
    audit(db, "cs_draft", "alert", str(alert_id), {"draft_id": draft.id, "source": source,
                                                   "guardrail_failures": failures}, actor="cs_copilot")
    db.commit()
    return {"id": draft.id, "draft": reply, "source": source, "status": draft.status, "context": ctx,
            "guardrail_failures": failures}


class ApproveRequest(BaseModel):
    actor: str = Field(default="cs_agent", max_length=80)
    edited_text: str | None = Field(default=None, max_length=700)


@router.post("/cs-draft/{draft_id}/approve")
def approve_draft(draft_id: int, req: ApproveRequest, db: Session = Depends(get_db)) -> dict[str, Any]:
    draft = db.get(CsDraftRow, draft_id)
    if draft is None:
        raise HTTPException(404, "draft not found")
    if req.edited_text:
        draft.draft = req.edited_text
    draft.status, draft.approved_by = "approved_sent", req.actor
    audit(db, "cs_draft_approved", "alert", str(draft.alert_id), {"draft_id": draft_id, "simulated_send": True},
          actor=req.actor)
    db.commit()
    return {"id": draft.id, "status": draft.status, "draft": draft.draft}


class AskRequest(BaseModel):
    question: str = Field(min_length=3, max_length=500)


@router.post("/ask")
def analyst(req: AskRequest, db: Session = Depends(get_db)) -> dict[str, Any]:
    result = ask(req.question, get_state().tools, on_tool_call=_tool_logger(db, "analyst", "analyst"))
    db.commit()
    return result
