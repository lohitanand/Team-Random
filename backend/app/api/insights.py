"""Read models for the dashboard: overview, team insights, friction health (computed, cached briefly)."""
from __future__ import annotations

import time
from collections import Counter
from typing import Any

import pandas as pd
from sqlalchemy.orm import Session

from backend.app.audit.outcomes import recovery_stats
from backend.app.db.models import AlertRow, PacketRow
from backend.app.decision.playbook import get_playbook
from backend.app.decision.routing import OWNER_TEAM, TEAM_VIEWS
from backend.app.detection.rules import RULES_BY_NAME
from backend.app.llm.fallbacks import FRICTION_LABELS, LIKELY_CAUSES
from backend.app.schemas.taxonomy import FRICTION_TYPES
from backend.app.store import DataStore

STEPS = ["browse", "product", "cart", "checkout", "payment", "order"]
_cache: dict[str, tuple[float, Any]] = {}


def _cached(key: str, ttl: float, fn):
    hit = _cache.get(key)
    if hit and time.monotonic() - hit[0] < ttl:
        return hit[1]
    value = fn()
    _cache[key] = (time.monotonic(), value)
    return value


def clear_cache() -> None:
    _cache.clear()


def packet_frame(db: Session) -> pd.DataFrame:
    def build() -> pd.DataFrame:
        rows = []
        for p in db.query(PacketRow).yield_per(2000):
            ctx = (p.payload or {}).get("context", {})
            dec = p.decision or {}
            rows.append({
                "packet_id": p.id, "packet_type": p.packet_type, "session_id": p.session_id, "source": p.source,
                "friction_type": p.friction_type, "gate": p.gate, "confidence": p.confidence,
                "risk_score": p.risk_score, "revenue_at_risk": dec.get("revenue_at_risk", 0.0),
                "priority": dec.get("priority"), "device": ctx.get("device"), "city": ctx.get("city"),
                "product": ctx.get("primary_product_id"), "gateway": ctx.get("gateway"), "courier": ctx.get("courier"),
                "rule_flags": (p.payload or {}).get("rule_flags", []), "themes": (p.payload or {}).get("text_themes", []),
                "signals": [s["feature"] for s in (p.payload or {}).get("top_signals", [])],
                "created_at": p.created_at, "customer_action": (dec.get("customer_action") or {}).get("id"),
            })
        return pd.DataFrame(rows)
    return _cached("packets", 10, build)


def funnel(store: DataStore) -> dict[str, Any]:
    def build() -> dict[str, Any]:
        s = store.sessions[store.sessions["session_kind"] == "shopping"].copy()
        s["furthest_idx"] = s["furthest_step"].map(STEPS.index)
        steps, heat = [], []
        for i, step in enumerate(STEPS[:-1]):
            reached = s[s["furthest_idx"] >= i]
            left = reached[(reached["exit_step"] == step) & ~reached["converted"]]
            steps.append({"step": step, "sessions": int(len(reached)), "dropped": int(len(left)),
                          "drop_rate": round(len(left) / max(len(reached), 1), 4)})
            for device, g in reached.groupby("device"):
                gl = left[left["device"] == device]
                heat.append({"step": step, "segment": device, "drop_rate": round(len(gl) / max(len(g), 1), 4),
                             "sessions": int(len(g))})
        steps.append({"step": "order", "sessions": int(s["converted"].sum()), "dropped": 0, "drop_rate": 0.0})
        return {"steps": steps, "heatmap": heat}
    return _cached("funnel", 3600, build)


def health(pf: pd.DataFrame, db: Session) -> dict[str, dict[str, Any]]:
    out = {}
    risky = pf[(pf["gate"] != "low") & (pf["packet_type"] == "session")]
    critical_open = {a.friction_type for a in db.query(AlertRow).filter(
        AlertRow.priority.in_(["critical", "high"]), AlertRow.status.in_(["open", "needs_review"])).all()}
    days = pd.to_datetime(risky["created_at"]).dt.normalize()
    last_day = days.max() if len(days) else None
    for f in FRICTION_TYPES:
        d = days[risky["friction_type"] == f]
        if last_day is None or d.empty:
            out[f] = {"status": "normal", "recent_per_day": 0, "baseline_per_day": 0}
            continue
        recent = (d > last_day - pd.Timedelta(days=3)).sum() / 3
        base_days = max((last_day - d.min()).days - 2, 1)
        baseline = (d <= last_day - pd.Timedelta(days=3)).sum() / base_days
        ratio = recent / baseline if baseline else 1.0
        status = "critical" if f in critical_open else "rising" if ratio >= 1.3 else "normal"
        out[f] = {"status": status, "recent_per_day": round(float(recent), 1),
                  "baseline_per_day": round(float(baseline), 1), "ratio": round(float(ratio), 2)}
    return out


def overview(store: DataStore, db: Session) -> dict[str, Any]:
    pf = packet_frame(db)
    sessions = store.sessions
    shopping = sessions[sessions["session_kind"] == "shopping"]
    risky = pf[(pf["gate"] != "low") & (pf["packet_type"] == "session")] if len(pf) else pf
    top = []
    hl = health(pf, db) if len(pf) else {}
    for f in FRICTION_TYPES:
        g = risky[risky["friction_type"] == f] if len(risky) else risky
        top.append({"friction_type": f, "label": FRICTION_LABELS[f], "owner_team": OWNER_TEAM[f],
                    "sessions": int(len(g)), "revenue_at_risk": round(float(g["revenue_at_risk"].sum()) if len(g) else 0, 2),
                    "high": int((g["gate"] == "high").sum()) if len(g) else 0,
                    "needs_review": int((g["gate"] == "medium").sum()) if len(g) else 0,
                    "health": hl.get(f, {"status": "normal"})})
    top.sort(key=lambda r: -r["revenue_at_risk"])
    daily = []
    if len(risky):
        d = risky.assign(day=pd.to_datetime(risky["created_at"]).dt.strftime("%m-%d"))
        pivot = d.pivot_table(index="day", columns="friction_type", values="packet_id", aggfunc="count", fill_value=0)
        daily = [{"day": day, **{k: int(v) for k, v in row.items()}} for day, row in pivot.iterrows()]
    open_alerts = db.query(AlertRow).filter(AlertRow.status.in_(["open", "needs_review"]))
    return {
        "kpis": {
            "sessions": int(len(sessions)), "shopping_sessions": int(len(shopping)),
            "conversion_rate": round(float(shopping["converted"].mean()), 4),
            "cart_abandonment_rate": round(float(shopping["abandoned"].sum() / max(shopping["reached_cart"].sum(), 1)), 4),
            "at_risk_sessions": int(len(risky)),
            "revenue_at_risk": round(float(risky["revenue_at_risk"].sum()) if len(risky) else 0.0, 2),
            "open_alerts": open_alerts.filter(AlertRow.status == "open").count(),
            "needs_review": open_alerts.filter(AlertRow.status == "needs_review").count(),
            "live_sessions": int((pf["source"] == "live").sum()) if len(pf) else 0,
        },
        "funnel": funnel(store),
        "top_frictions": top,
        "daily": daily,
        "recovery": recovery_stats(db),
    }


def team_insights(team: str, store: DataStore, db: Session) -> dict[str, Any]:
    owners = TEAM_VIEWS[team]
    frictions = [f for f, t in OWNER_TEAM.items() if t in owners]
    pf = packet_frame(db)
    hl = health(pf, db) if len(pf) else {}
    book = get_playbook()
    items = []
    for f in frictions:
        g = pf[(pf["friction_type"] == f) & (pf["gate"] != "low")] if len(pf) else pf
        sess = g[g["packet_type"] == "session"] if len(g) else g
        flags = Counter(x for fl in sess["rule_flags"] for x in fl) if len(sess) else Counter()
        themes = Counter(x for th in sess["themes"] for x in th if x != "other") if len(sess) else Counter()
        signals = Counter(x for sg in sess["signals"] for x in sg) if len(sess) else Counter()

        def top_values(col: str) -> list[dict[str, Any]]:
            if not len(sess):
                return []
            vc = sess[col].dropna().value_counts().head(3)
            return [{"value": str(k), "sessions": int(v)} for k, v in vc.items()]

        alerts = (db.query(AlertRow).filter(AlertRow.friction_type == f, AlertRow.status.in_(["open", "needs_review",
                  "approved", "assigned"])).order_by(AlertRow.alert_type.asc(), AlertRow.impact.desc()).limit(6).all())
        default_team = book.team[f][-1]
        agg_team = next((a for a in book.team[f] if a.when.get("packet_type") == "aggregate"), None)
        items.append({
            "friction_type": f, "label": FRICTION_LABELS[f], "owner_team": OWNER_TEAM[f],
            "health": hl.get(f, {"status": "normal"}),
            "what": {"sessions": int(len(sess)), "revenue_at_risk": round(float(sess["revenue_at_risk"].sum()) if len(sess) else 0, 2),
                     "high_confidence": int((sess["gate"] == "high").sum()) if len(sess) else 0,
                     "needs_review": int((sess["gate"] == "medium").sum()) if len(sess) else 0,
                     "aggregate_anomalies": int((g["packet_type"] == "aggregate").sum()) if len(g) else 0,
                     "top_devices": top_values("device"), "top_cities": top_values("city"),
                     "top_products": top_values("product"), "top_gateways": top_values("gateway"),
                     "top_couriers": top_values("courier")},
            "why": {"likely_cause": LIKELY_CAUSES[f],
                    "rule_flags": [{"flag": k, "description": RULES_BY_NAME[k].description, "sessions": v}
                                   for k, v in flags.most_common(4) if k in RULES_BY_NAME],
                    "themes": [{"theme": k, "texts": v} for k, v in themes.most_common(3)],
                    "signals": [{"feature": k, "sessions": v} for k, v in signals.most_common(4)]},
            "recommended_action": {"team": default_team.model_dump(),
                                   "incident": agg_team.model_dump() if agg_team else None,
                                   "customer": [a.model_dump() for a in book.customer[f]]},
            "alerts": [{"id": a.id, "title": a.title, "gate": a.gate, "priority": a.priority, "status": a.status,
                        "confidence": a.confidence, "alert_type": a.alert_type, "revenue_at_risk": a.revenue_at_risk}
                       for a in alerts],
        })
    items.sort(key=lambda i: -i["what"]["revenue_at_risk"])
    return {"team": team, "frictions": frictions, "items": items}
