"""Evidence fusion (CLAUDE.md §7.5): one packet per at-risk session and one per aggregate anomaly."""
from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

import numpy as np
import pandas as pd

from backend.app.config import Settings, get_settings
from backend.app.decision.signals import theme_frictions
from backend.app.detection.rules import rule_frictions
from backend.app.schemas.evidence import AggregatePacket, SessionPacket, Signal
from backend.app.schemas.taxonomy import FRICTION_TYPES

CONTEXT_COLUMNS = ["device", "app_version", "city", "city_tier", "source", "gateway", "payment_method", "courier",
                   "primary_product_id", "order_id", "exit_step", "furthest_step", "converted", "abandoned"]


def session_themes(text_themes: pd.DataFrame, orders_by_session: dict[str, str | None]) -> dict[str, list[str]]:
    """Themes of texts linked to each session directly or through the session's order."""
    by_session: dict[str, list[str]] = defaultdict(list)
    by_order: dict[str, list[str]] = defaultdict(list)
    for row in text_themes.itertuples():
        if row.session_id:
            by_session[row.session_id].append(row.theme)
        if row.order_id:
            by_order[row.order_id].append(row.theme)
    out: dict[str, list[str]] = {}
    for sid, oid in orders_by_session.items():
        themes = by_session.get(sid, []) + (by_order.get(oid, []) if oid else [])
        if themes:
            out[sid] = list(dict.fromkeys(themes))
    return out


def aggregate_context_index(aggregates: list[AggregatePacket]) -> dict[str, dict[str, Any]]:
    """session_id -> context of the strongest aggregate anomaly that session belongs to."""
    index: dict[str, dict[str, Any]] = {}
    for agg in sorted(aggregates, key=lambda a: a.z_score):
        ctx = {"packet_id": agg.packet_id, "segment_type": agg.segment_type, "segment": agg.segment_value,
               "metric": agg.metric, "friction_hint": agg.friction_hint, "multiplier": agg.multiplier,
               "observed_rate": agg.observed, "baseline_rate": agg.baseline,
               "affected_sessions": agg.affected_sessions, "window_start": agg.window_start.isoformat(),
               "window_end": agg.window_end.isoformat()}
        for sid in agg.session_ids:
            index[sid] = ctx  # strongest (highest z) wins because of the sort
    return index


def is_at_risk(risk: float, flags: list[str], themes: list[str], converted: bool, settings: Settings) -> bool:
    if flags or theme_frictions(themes):
        return True
    return risk >= settings.at_risk_threshold and not converted


def _plain(value: Any) -> Any:
    """JSON-friendly scalar: numpy -> python, NaN -> None."""
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, float) and np.isnan(value):
        return None
    return value


def build_session_packets(scores: pd.DataFrame, sessions: pd.DataFrame, themes: dict[str, list[str]],
                          agg_index: dict[str, dict[str, Any]], order_values: dict[str, float],
                          settings: Settings | None = None) -> list[SessionPacket]:
    s = settings or get_settings()
    info = sessions.set_index("session_id", drop=False).to_dict("index")
    packets: list[SessionPacket] = []
    for row in scores.itertuples():
        sess = info[row.session_id]
        sid_themes = themes.get(row.session_id, [])
        if not is_at_risk(row.risk_score, row.rule_flags, sid_themes, bool(sess["converted"]), s):
            continue
        context = {c: _plain(sess[c]) for c in CONTEXT_COLUMNS}
        context["start"] = sess["start"].isoformat()
        context["order_value"] = order_values.get(context["order_id"]) if context["order_id"] else None
        packets.append(SessionPacket(
            packet_id=f"pk_{row.session_id}", session_id=row.session_id, user_id=sess["user_id"],
            session_kind=sess["session_kind"], risk_score=float(row.risk_score), cart_value=float(sess["cart_value"]),
            rule_flags=row.rule_flags, top_signals=[Signal(**x) for x in row.top_signals],
            friction_probs=row.friction_probs,
            friction_signals={k: [Signal(**x) for x in v] for k, v in row.friction_signals.items()},
            text_themes=sid_themes, aggregate_context=agg_index.get(row.session_id, {}), context=context,
        ))
    return packets


def enrich_aggregate(agg: AggregatePacket, scores_by_session: dict[str, Any],
                     themes: dict[str, list[str]], settings: Settings | None = None) -> AggregatePacket:
    """Summarise the affected sessions' detector outputs onto the aggregate packet.

    rule_support_share / model_support_share: share of affected sessions whose rules / classifier
    (prob >= threshold) point at the anomaly's friction; confidence.py compares them to config.
    """
    s = settings or get_settings()
    rows = [scores_by_session[sid] for sid in agg.session_ids if sid in scores_by_session]
    if not rows:
        return agg
    hint = agg.friction_hint
    flag_counts = Counter(f for r in rows for f in r["rule_flags"])
    common = [f for f, c in flag_counts.most_common() if c / len(rows) >= s.aggregate_rule_support_share]
    probs = {f: round(float(np.mean([r["friction_probs"][f] for r in rows])), 4) for f in FRICTION_TYPES}
    rule_share = sum(hint in rule_frictions(r["rule_flags"]) for r in rows) / len(rows)
    model_share = sum(r["friction_probs"].get(hint, 0) >= s.friction_prob_threshold for r in rows) / len(rows)
    signal_sum: dict[str, float] = defaultdict(float)
    for r in rows:
        for sig in r["top_signals"]:
            signal_sum[sig["feature"]] += sig["shap"] / len(rows)
    top = sorted(signal_sum.items(), key=lambda kv: (-kv[1], kv[0]))[:5]
    hint_sum: dict[str, float] = defaultdict(float)  # classifier SHAP for the anomaly's own friction type
    for r in rows:
        for sig in r["friction_signals"].get(hint, []):
            hint_sum[sig["feature"]] += sig["shap"] / len(rows)
    hint_top = sorted(hint_sum.items(), key=lambda kv: (-kv[1], kv[0]))[:5] or top
    theme_counts = Counter(t for sid in agg.session_ids for t in themes.get(sid, []) if t != "other")
    return agg.model_copy(update={
        "rule_flags": common,
        "friction_probs": probs,
        "top_signals": [Signal(feature=f, shap=round(v, 4)) for f, v in top],
        "friction_signals": {hint: [Signal(feature=f, shap=round(v, 4)) for f, v in hint_top]} if hint else {},
        "text_themes": [t for t, _ in theme_counts.most_common(3)],
        "aggregate_context": {**agg.aggregate_context, "sessions_scored": len(rows),
                              "rule_support_share": round(rule_share, 3),
                              "model_support_share": round(model_share, 3)},
    })
