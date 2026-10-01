"""Sessions: at-risk list, session detail (journey, features, packet, explanation, action), recovery."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.app.actions.recovery import plan_recovery
from backend.app.api.deps import get_state
from backend.app.api.insights import clear_cache
from backend.app.api.routes_alerts import load_packet
from backend.app.api.util import plain
from backend.app.db.models import AlertRow, PacketRow, RecoveryRow
from backend.app.db.session import get_db
from backend.app.decision.playbook import default_moment
from backend.app.ingestion.features import FEATURE_COLUMNS
from backend.app.llm.fallbacks import fallback_explanation, fallback_message
from backend.app.schemas.events import PAGE_TO_STEP

router = APIRouter(tags=["sessions"])
KEY_FEATURES = [c for c in FEATURE_COLUMNS if not c.startswith(("dwell_z", "device_code", "source_code", "hour"))]


@router.get("/sessions")
def list_sessions(source: str | None = None, gate: str | None = None, limit: int = 50,
                  db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    q = db.query(PacketRow).filter(PacketRow.packet_type == "session", PacketRow.gate != "low")
    if source:
        q = q.filter(PacketRow.source == source)
    if gate:
        q = q.filter(PacketRow.gate == gate)
    rows = q.order_by(PacketRow.source.desc(), PacketRow.created_at.desc()).limit(min(limit, 200)).all()
    return [{"session_id": r.session_id, "source": r.source, "risk_score": r.risk_score,
             "friction_type": r.friction_type, "confidence": r.confidence, "gate": r.gate,
             "owner_team": (r.decision or {}).get("owner_team"), "priority": (r.decision or {}).get("priority"),
             "cart_value": (r.payload or {}).get("cart_value"), "device": (r.payload or {}).get("context", {}).get("device"),
             "step": (r.payload or {}).get("context", {}).get("exit_step"),
             "customer_action": ((r.decision or {}).get("customer_action") or {}).get("id"),
             "created_at": r.created_at} for r in rows]


def _journey(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{"ts": e["timestamp"], "event": e["event"], "page": e["page"], "step": PAGE_TO_STEP.get(e["page"]),
             "product_id": e.get("product_id"), "order_id": e.get("order_id"), "metadata": e.get("metadata") or {}}
            for e in sorted(events, key=lambda e: e["timestamp"])]


@router.get("/sessions/{session_id}")
def session_detail(session_id: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    state = get_state()
    store = state.store
    live = state.live.events_for(session_id) if "live" in state.__dict__ else []
    events = live or store.session_events(session_id)
    if not events:
        raise HTTPException(404, "session not found")
    row = db.query(PacketRow).filter(PacketRow.session_id == session_id).first()
    alert = db.query(AlertRow).filter(AlertRow.session_id == session_id).first()
    recoveries = db.query(RecoveryRow).filter(RecoveryRow.session_id == session_id).all()
    info: dict[str, Any] = {}
    features: dict[str, float] = {}
    truth = None
    if session_id in store.session_index.index:
        info = {k: v for k, v in store.session_index.loc[session_id].to_dict().items()}
        f = store.features[store.features["session_id"] == session_id]
        if len(f):
            features = {k: float(v) for k, v in f.iloc[0].items() if k in KEY_FEATURES and v}
        gt = store.ground_truth[store.ground_truth["session_id"] == session_id]
        truth = gt.iloc[0][["friction_types", "primary_variant", "incident_id"]].to_dict() if len(gt) else None
    elif live:
        features = {k: v for k, v in state.scorer.score_events(session_id, events)["features"].items()
                    if k in KEY_FEATURES and v}
    out: dict[str, Any] = {"session_id": session_id, "source": "live" if live else "batch", "info": plain(info),
                           "journey": plain(_journey(events)), "features": features,
                           "synthetic_ground_truth": plain(truth),
                           "packet": None, "decision": None, "explanation": None, "recommended": None,
                           "alert_id": alert.id if alert else None,
                           "recoveries": [{"id": r.id, "action_id": r.action_id, "moment": r.moment, "channel": r.channel,
                                           "status": r.status, "message": r.message, "outcome": r.outcome,
                                           "holdout": r.holdout, "created_at": r.created_at} for r in recoveries]}
    if row is not None:
        packet, decision = load_packet(row)
        out["packet"], out["decision"] = row.payload, row.decision
        out["explanation"] = alert.explanation if alert else fallback_explanation(packet, decision).model_dump()
        action = state_action = decision.customer_action
        if packet.packet_type == "session":
            from backend.app.decision.playbook import get_playbook

            state_action = get_playbook().customer_action(decision.friction_type, packet, default_moment(packet)) or action
        if state_action:
            product = store.product_by_id.get(packet.context.get("primary_product_id") or "", {})
            out["recommended"] = {"action": state_action.model_dump(),
                                  "message_preview": fallback_message(state_action, packet, product.get("subcategory")).text}
    return out


class RecoverRequest(BaseModel):
    moment: str | None = None


@router.post("/sessions/{session_id}/recover")
def recover(session_id: str, req: RecoverRequest | None = None, db: Session = Depends(get_db)) -> dict[str, Any]:
    row = db.query(PacketRow).filter(PacketRow.session_id == session_id).first()
    if row is None:
        raise HTTPException(404, "no evidence packet for this session (not at risk)")
    packet, decision = load_packet(row)
    if decision.gate == "low":
        raise HTTPException(409, "low confidence: log and monitor only, no recovery")
    moment = (req.moment if req and req.moment else None) or default_moment(packet)
    product = get_state().store.product_by_id.get(packet.context.get("primary_product_id") or "", {})
    rec = plan_recovery(db, decision, packet, moment, datetime.now(), product.get("subcategory"), simulate=False)
    if rec is None:
        raise HTTPException(409, f"no eligible playbook action for moment '{moment}'")
    db.commit()
    clear_cache()
    return {"id": rec.id, "action_id": rec.action_id, "moment": rec.moment, "channel": rec.channel,
            "status": rec.status, "message": rec.message, "message_source": rec.message_source,
            "holdout": rec.holdout}
