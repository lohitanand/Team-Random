"""Batch pipeline over historical data: detectors -> evidence packets -> deterministic decisions.

    python -m backend.app.pipeline
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from backend.app.config import MODELS_DIR, PROCESSED_DIR, Settings, get_settings
from backend.app.decision.engine import Investigator, decide
from backend.app.detection.anomaly import detect_anomalies
from backend.app.detection.scorer import SCORE_JSON_COLUMNS, Scorer, encode_json_columns
from backend.app.fusion.evidence import (
    aggregate_context_index, build_session_packets, enrich_aggregate, session_themes,
)
from backend.app.schemas.alerts import Decision
from backend.app.schemas.evidence import AggregatePacket, Packet, SessionPacket
from backend.app.store import DataStore, get_store
from backend.ml.common import FRICTION_FEATURES, RISK_FEATURES


def score_sessions(store: DataStore, scorer: Scorer) -> pd.DataFrame:
    full = store.features.set_index("session_id")
    final = store.prefixes[store.prefixes["is_final"]].set_index("session_id").reindex(full.index)
    final = final[RISK_FEATURES].fillna(0.0)
    kinds = store.sessions.set_index("session_id").reindex(full.index)["session_kind"]
    frame = full[FRICTION_FEATURES].reset_index()
    return scorer.score(frame, final.reset_index(drop=True), (kinds == "post_purchase").to_numpy())


def build_packets(store: DataStore, scores: pd.DataFrame, settings: Settings) -> list[Packet]:
    sessions = store.sessions
    themes = session_themes(store.text_themes, dict(zip(sessions["session_id"], sessions["order_id"])))
    aggregates = detect_anomalies(sessions, store.events, store.payments, store.orders, store.reviews, settings)
    by_session = scores.set_index("session_id").to_dict("index")
    aggregates = [enrich_aggregate(a, by_session, themes, settings) for a in aggregates]
    order_values = dict(zip(store.orders["order_id"], store.orders["order_value"].astype(float)))
    session_packets = build_session_packets(scores, sessions, themes, aggregate_context_index(aggregates),
                                            order_values, settings)
    return [*aggregates, *session_packets]


def decide_all(packets: list[Packet], investigator: Investigator | None = None,
               investigate_limit: int | None = None) -> list[tuple[Decision, Packet]]:
    """Decide every packet. The investigator (if any) runs for aggregates and the highest-risk
    medium-confidence sessions, up to `investigate_limit` calls."""
    budget = investigate_limit if investigate_limit is not None else len(packets)
    order = sorted(range(len(packets)), key=lambda i: (packets[i].packet_type != "aggregate",
                                                       -getattr(packets[i], "risk_score", 1.0), packets[i].packet_id))
    results: dict[int, tuple[Decision, Packet]] = {}
    for i in order:
        use = investigator if (investigator is not None and budget > 0) else None
        decision, packet = decide(packets[i], use)
        if decision.investigated:
            budget -= 1
        results[i] = (decision, packet)
    return [results[i] for i in range(len(packets))]


def packets_frame(results: list[tuple[Decision, Packet]]) -> pd.DataFrame:
    return pd.DataFrame([{
        "packet_id": p.packet_id, "packet_type": p.packet_type,
        "session_id": p.session_id if isinstance(p, SessionPacket) else None,
        "packet": p.model_dump_json(),
    } for _, p in results])


def decisions_frame(results: list[tuple[Decision, Packet]]) -> pd.DataFrame:
    rows = []
    for d, p in results:
        rows.append({
            "packet_id": d.packet_id, "packet_type": d.packet_type,
            "session_id": p.session_id if isinstance(p, SessionPacket) else None,
            "friction_type": d.friction_type, "secondary_friction": d.secondary_friction,
            "classification_source": d.classification_source, "confidence": d.confidence, "gate": d.gate,
            "owner_team": d.owner_team, "priority": d.priority, "impact": d.impact,
            "revenue_at_risk": d.revenue_at_risk, "customers_affected": d.customers_affected,
            "investigated": d.investigated, "needs_review": d.needs_review,
            "team_action_id": d.team_action.id,
            "customer_action_id": d.customer_action.id if d.customer_action else None,
            "decision": d.model_dump_json(),
        })
    return pd.DataFrame(rows)


def _when(packet: Packet) -> datetime:
    if isinstance(packet, SessionPacket):
        return datetime.fromisoformat(packet.context["start"])
    return packet.window_end


def persist(results: list[tuple[Decision, Packet]], store: DataStore) -> dict[str, int]:
    """Write packets, decisions, alerts, recovery actions and the audit trail (batch uses fallbacks)."""
    from backend.app.actions.alerts import create_alert
    from backend.app.actions.recovery import plan_recovery
    from backend.app.audit.log import audit
    from backend.app.db.models import PacketRow
    from backend.app.db.session import get_session_factory, reset_db
    from backend.app.decision.playbook import default_moment
    from backend.app.llm.client import LLMClient
    from backend.app.llm.explain import explain

    reset_db()
    offline = LLMClient(get_settings().model_copy(update={"llm_enabled": False}))
    counts = {"packets": 0, "alerts": 0, "recoveries": 0}
    user_sends: dict[str, list[datetime]] = {}
    with get_session_factory()() as db:
        for decision, packet in sorted(results, key=lambda r: _when(r[1])):
            when = _when(packet)
            db.add(PacketRow(id=packet.packet_id, packet_type=packet.packet_type,
                             session_id=getattr(packet, "session_id", None), source="batch",
                             friction_type=decision.friction_type, gate=decision.gate, confidence=decision.confidence,
                             risk_score=getattr(packet, "risk_score", None),
                             payload=json.loads(packet.model_dump_json()), decision=json.loads(decision.model_dump_json()),
                             created_at=when))
            audit(db, "decision", "packet", packet.packet_id,
                  {"friction_type": decision.friction_type, "confidence": decision.confidence, "gate": decision.gate,
                   "priority": decision.priority, "breakdown": decision.breakdown.model_dump(),
                   "investigated": decision.investigated, "team_action": decision.team_action.id}, ts=when)
            counts["packets"] += 1
            if decision.gate != "low":
                create_alert(db, decision, packet, explain(packet, decision, offline), "batch", when)
                counts["alerts"] += 1
            if isinstance(packet, SessionPacket):
                sends = [t for t in user_sends.get(packet.user_id, []) if when - t < timedelta(hours=24)]
                product = store.product_by_id.get(packet.context.get("primary_product_id") or "", {})
                row = plan_recovery(db, decision, packet, default_moment(packet), when, product.get("subcategory"),
                                    offline, sent_in_24h=len(sends))
                if row is not None:
                    counts["recoveries"] += 1
                    if row.status in ("sent", "pending_approval"):
                        user_sends[packet.user_id] = [*sends, when]
        db.commit()
    return counts


def run(store: DataStore | None = None, models_dir: Path = MODELS_DIR, out_dir: Path = PROCESSED_DIR,
        investigator: Investigator | None = None, investigate_limit: int | None = None,
        write_db: bool = False) -> dict[str, Any]:
    settings = get_settings()
    store = store or get_store()
    scorer = Scorer.load(models_dir)
    scores = score_sessions(store, scorer)
    out_dir.mkdir(parents=True, exist_ok=True)
    encode_json_columns(scores, SCORE_JSON_COLUMNS).to_parquet(out_dir / "session_scores.parquet", index=False)

    packets = build_packets(store, scores, settings)
    results = decide_all(packets, investigator, investigate_limit)
    packets_frame(results).to_parquet(out_dir / "packets.parquet", index=False)
    decisions = decisions_frame(results)
    decisions.to_parquet(out_dir / "decisions.parquet", index=False)
    counts = persist(results, store) if write_db else {}
    return {"scores": scores, "results": results, "decisions": decisions, "db": counts}


def summarize(decisions: pd.DataFrame) -> str:
    lines = [f"Packets: {len(decisions):,}  ({(decisions['packet_type'] == 'aggregate').sum()} aggregate)"]
    lines.append("Gates:      " + json.dumps(decisions["gate"].value_counts().to_dict()))
    lines.append("Priorities: " + json.dumps(decisions["priority"].value_counts().to_dict()))
    lines.append("Teams:      " + json.dumps(decisions["owner_team"].value_counts().to_dict()))
    lines.append("Investigated: " + str(int(decisions["investigated"].sum())))
    agg = decisions[decisions["packet_type"] == "aggregate"]
    for row in agg.itertuples():
        lines.append(f"  AGG {row.friction_type:<24}{row.gate:<7}{row.confidence:<6}{row.priority:<9}{row.packet_id}")
    return "\n".join(lines)


def main() -> int:
    from backend.app.agents.investigator import Investigator
    from backend.app.agents.tools import Tools

    started = time.perf_counter()
    store = get_store()
    investigator = Investigator(Tools(store), use_llm=False)  # batch: deterministic plan, no LLM calls
    out = run(store, investigator=investigator, investigate_limit=get_settings().batch_investigate_limit,
              write_db=True)
    print(summarize(out["decisions"]))
    print("Database: " + json.dumps(out["db"]))
    print(f"Done in {time.perf_counter() - started:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
