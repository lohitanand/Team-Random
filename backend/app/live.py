"""Live scoring of tracker sessions: detectors -> packet -> decision (+ read-only investigation for
medium confidence) -> alert, in-session nudge (high confidence + auto_allowed only) and SSE update."""
from __future__ import annotations

import json
import threading
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from backend.app.actions.alerts import create_alert, key_evidence
from backend.app.actions.recovery import plan_recovery
from backend.app.agents.investigator import Investigator
from backend.app.api.sse import Broadcaster
from backend.app.audit.log import audit
from backend.app.config import Settings, get_settings
from backend.app.db.models import AlertRow, PacketRow, RecoveryRow
from backend.app.decision.engine import decide
from backend.app.detection.scorer import Scorer
from backend.app.fusion.evidence import is_at_risk
from backend.app.llm.client import LLMClient
from backend.app.llm.explain import explain
from backend.app.schemas.alerts import Decision
from backend.app.schemas.events import PAGE_TO_STEP, Event
from backend.app.schemas.evidence import SessionPacket, Signal
from backend.app.store import DataStore


def _context(events: list[dict[str, Any]], store: DataStore) -> dict[str, Any]:
    first = events[0]["metadata"] if events and events[0]["event"] == "page_view" else {}
    pay = [e["metadata"] for e in events if e["event"] == "payment_attempt"]
    info = [e["metadata"] for e in events if e["event"] == "delivery_info_view"]
    products = [e["product_id"] for e in events if e.get("product_id")]
    body = [e for e in events if e["event"] != "exit"]
    order = next((e["order_id"] for e in events if e.get("order_id")), None)
    return {
        "device": first.get("device"), "app_version": first.get("app_version"), "city": first.get("city"),
        "city_tier": first.get("city_tier"), "source": first.get("source", "live"),
        "gateway": pay[-1].get("gateway") if pay else None, "payment_method": pay[-1].get("method") if pay else None,
        "courier": info[-1].get("courier") if info else None,
        "primary_product_id": max(set(products), key=products.count) if products else None,
        "order_id": order, "exit_step": PAGE_TO_STEP[body[-1]["page"]] if body else "browse",
        "furthest_step": PAGE_TO_STEP[body[-1]["page"]] if body else "browse",
        "converted": any(e["event"] == "order_placed" for e in events), "abandoned": False,
        "start": events[0]["timestamp"].isoformat(), "order_value": None, "live": True,
    }


class LiveEngine:
    def __init__(self, store: DataStore, scorer: Scorer, broadcaster: Broadcaster, investigator: Investigator,
                 settings: Settings | None = None) -> None:
        self.store, self.scorer, self.broadcaster, self.investigator = store, scorer, broadcaster, investigator
        self.settings = settings or get_settings()
        self.sessions: dict[str, dict[str, Any]] = {}
        self.lock = threading.Lock()
        self.offline = LLMClient(self.settings.model_copy(update={"llm_enabled": False}))

    def add(self, db: Session, events: list[Event]) -> dict[str, Any]:
        with self.lock:
            touched: dict[str, dict[str, Any]] = {}
            for e in events:
                st = self.sessions.setdefault(e.session_id, {"events": [], "user_id": e.user_id, "ended": False,
                                                             "nudged": False, "last_gate": None})
                st["events"].append({"timestamp": e.timestamp.replace(tzinfo=None), "event": e.event, "page": e.page,
                                     "product_id": e.product_id, "order_id": e.order_id, "metadata": e.metadata})
                st["last_seen"] = datetime.now()
                st["ended"] = False
                touched[e.session_id] = st
            responses = [self._evaluate(db, sid, st) for sid, st in touched.items()]
        return responses[-1] if responses else {"accepted": 0}

    def events_for(self, session_id: str) -> list[dict[str, Any]]:
        st = self.sessions.get(session_id)
        return list(st["events"]) if st else []

    def packet_for(self, session_id: str, st: dict[str, Any]) -> SessionPacket | None:
        evs = sorted(st["events"], key=lambda e: e["timestamp"])
        scored = self.scorer.score_events(session_id, evs)
        ctx = _context(evs, self.store)
        if not is_at_risk(float(scored["risk_score"]), scored["rule_flags"], [], ctx["converted"], self.settings):
            st["risk_score"] = float(scored["risk_score"])
            return None
        return SessionPacket(
            packet_id=f"pk_live_{session_id}", session_id=session_id, user_id=st["user_id"],
            session_kind="post_purchase" if scored["features"].get("is_post_purchase") else "shopping",
            risk_score=float(scored["risk_score"]), cart_value=float(scored["features"].get("cart_value", 0.0)),
            rule_flags=scored["rule_flags"], top_signals=[Signal(**s) for s in scored["top_signals"]],
            friction_probs=scored["friction_probs"],
            friction_signals={k: [Signal(**s) for s in v] for k, v in scored["friction_signals"].items()},
            context=ctx)

    def _evaluate(self, db: Session, session_id: str, st: dict[str, Any]) -> dict[str, Any]:
        packet = self.packet_for(session_id, st)
        base = {"accepted": len(st["events"]), "session_id": session_id}
        if packet is None:
            return base | {"risk_score": round(st.get("risk_score", 0.0), 3), "at_risk": False}
        decision, packet = decide(packet, self.investigator, moment="in_session")
        st["risk_score"], st["decision"], st["packet"] = packet.risk_score, decision, packet
        alert = self._upsert(db, decision, packet)
        nudge = self._nudge(db, decision, packet, st)
        db.commit()
        message = {
            "type": "at_risk", "session_id": session_id, "ts": datetime.now().isoformat(),
            "risk_score": round(packet.risk_score, 3), "friction_type": decision.friction_type,
            "confidence": decision.confidence, "gate": decision.gate, "owner_team": decision.owner_team,
            "priority": decision.priority, "rule_flags": packet.rule_flags, "alert_id": alert.id if alert else None,
            "customer_action": decision.customer_action.id if decision.customer_action else None,
            "nudge": nudge, "investigated": decision.investigated, "cart_value": packet.cart_value,
            "device": packet.context.get("device"), "step": packet.context.get("exit_step"),
        }
        if decision.gate != "low":
            self.broadcaster.publish(message)
        return base | {"at_risk": decision.gate != "low", **{k: message[k] for k in
                       ("risk_score", "friction_type", "confidence", "gate", "nudge", "alert_id")}}

    def _upsert(self, db: Session, decision: Decision, packet: SessionPacket) -> AlertRow | None:
        row = db.get(PacketRow, packet.packet_id)
        payload, dec = json.loads(packet.model_dump_json()), json.loads(decision.model_dump_json())
        if row is None:
            row = PacketRow(id=packet.packet_id, packet_type="session", session_id=packet.session_id, source="live",
                            created_at=datetime.now())
            db.add(row)
        row.friction_type, row.gate, row.confidence = decision.friction_type, decision.gate, decision.confidence
        row.risk_score, row.payload, row.decision = packet.risk_score, payload, dec
        audit(db, "decision", "packet", packet.packet_id,
              {"friction_type": decision.friction_type, "confidence": decision.confidence, "gate": decision.gate,
               "investigated": decision.investigated, "source": "live"})
        if decision.gate == "low":
            return None
        alert = db.query(AlertRow).filter(AlertRow.packet_id == packet.packet_id).first()
        if alert is None:
            return create_alert(db, decision, packet, explain(packet, decision, self.offline), "live")
        if alert.status in ("open", "needs_review"):
            alert.friction_type, alert.confidence, alert.gate = decision.friction_type, decision.confidence, decision.gate
            alert.priority, alert.status = decision.priority, "open" if decision.gate == "high" else "needs_review"
            alert.key_evidence = key_evidence(decision, packet)
            alert.explanation = explain(packet, decision, self.offline).model_dump()
            alert.team_action = decision.team_action.model_dump()
            alert.customer_action = decision.customer_action.model_dump() if decision.customer_action else None
            alert.updated_at = datetime.now()
        return alert

    def _nudge(self, db: Session, decision: Decision, packet: SessionPacket, st: dict[str, Any]) -> dict | None:
        """In-session message: only at high confidence, only auto_allowed playbook actions, once per session."""
        action = decision.customer_action
        if st["nudged"] or decision.gate != "high" or action is None or not action.auto_allowed:
            return None
        row = plan_recovery(db, decision, packet, "in_session", datetime.now(),
                            self._product_name(packet), LLMClient(self.settings), simulate=False)
        if row is None or row.status != "sent":
            return None
        st["nudged"] = True
        return {"action_id": row.action_id, "channel": row.channel, "message": row.message,
                "source": row.message_source}

    def _product_name(self, packet: SessionPacket) -> str | None:
        p = self.store.product_by_id.get(packet.context.get("primary_product_id") or "")
        return p.get("subcategory") if p else None

    def finalize_idle(self, db: Session) -> int:
        """Sessions idle for live_idle_minutes are over: plan post-session recovery if still at risk."""
        now, done = datetime.now(), 0
        with self.lock:
            for sid, st in self.sessions.items():
                if st["ended"] or now - st.get("last_seen", now) < timedelta(minutes=self.settings.live_idle_minutes):
                    continue
                st["ended"] = True
                decision, packet = st.get("decision"), st.get("packet")
                if decision is None or packet.context.get("converted"):
                    continue
                exists = db.query(RecoveryRow).filter(RecoveryRow.session_id == sid,
                                                      RecoveryRow.moment == "post_session").first()
                if exists:
                    continue
                row = plan_recovery(db, decision, packet, "post_session", now, self._product_name(packet),
                                    LLMClient(self.settings), simulate=False)
                if row is not None:
                    done += 1
                    self.broadcaster.publish({"type": "session_ended", "session_id": sid, "ts": now.isoformat(),
                                              "recovery": {"action_id": row.action_id, "status": row.status,
                                                           "channel": row.channel, "message": row.message}})
            db.commit()
        return done
