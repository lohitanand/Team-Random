"""Aggregate anomaly detection per segment (CLAUDE.md §7.4).

Each detector turns source tables into "units" (one row per session or order) with a `bad` flag,
then compares the bad-rate of a segment against its baseline:
- over time: trailing rolling baseline, windows of 15-60 min (gateway) or 1 day (courier/city);
- across segments: one segment against all others (product, device).
A window is flagged when bad >= min_count and (z > anomaly_z_threshold or rate >= multiplier x baseline).

    python -m backend.app.detection.anomaly
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import datetime

import numpy as np
import pandas as pd

from backend.app.config import Settings, get_settings
from backend.app.schemas.evidence import AggregatePacket


@dataclass(frozen=True)
class Detector:
    segment_type: str
    metric: str
    friction_hint: str | None


GATEWAY = Detector("gateway", "payment_session_failure_rate", "payment_failure")
COURIER_ETA = Detector("courier_city", "long_eta_share", "delivery_uncertainty")
COURIER_DELAY = Detector("courier_city", "delayed_order_share", "post_purchase_concern")
PRODUCT_SIZE = Detector("product", "size_chart_no_add_rate", "unclear_product_info")
PRODUCT_FEEDBACK = Detector("product", "negative_feedback_rate", "unclear_product_info")
DEVICE_ERRORS = Detector("device", "error_session_rate", "technical_glitch")


# --- statistics ------------------------------------------------------------------

def binomial_z(p: float, p0: float, n: float) -> float:
    p0 = min(max(p0, 1e-3), 0.999)
    return (p - p0) / math.sqrt(p0 * (1 - p0) / max(n, 1))


def is_flagged(bad: float, z: float, multiplier: float, s: Settings) -> bool:
    return bad >= s.anomaly_min_count and (z > s.anomaly_z_threshold or multiplier >= s.anomaly_rate_multiplier)


def _packet_id(det: Detector, segment: str, start: datetime) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", f"{det.segment_type}-{segment}-{det.metric}".lower()).strip("-")
    return f"agg_{slug}_{start:%Y%m%d%H%M}"


def _packet(det: Detector, segment: str, units: pd.DataFrame, start: datetime, end: datetime,
            p0: float, z: float, trend: str) -> AggregatePacket:
    bad = units[units["bad"]]
    n = len(units)
    p = len(bad) / max(n, 1)
    lost = bad[~bad["converted"]]
    sessions = sorted({s for s in bad["session_id"] if isinstance(s, str)})
    return AggregatePacket(
        packet_id=_packet_id(det, segment, start), segment_type=det.segment_type, segment_value=segment,
        metric=det.metric, friction_hint=det.friction_hint, window_start=start, window_end=end,
        observed=round(p, 4), baseline=round(p0, 4), z_score=round(z, 2),
        multiplier=round(p / max(p0, 1e-3), 2), affected_sessions=len(sessions), session_ids=sessions,
        revenue_at_risk=round(float(lost["value"].sum()), 2), trend=trend,
        aggregate_context={"segment_type": det.segment_type, "segment": segment, "metric": det.metric,
                           "units_in_window": n, "bad_units": int(len(bad))},
    )


def _merge_intervals(intervals: list[tuple[pd.Timestamp, pd.Timestamp]]) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    merged: list[list[pd.Timestamp]] = []
    for start, end in sorted(intervals):
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return [(a, b) for a, b in merged]


def temporal_anomalies(units: pd.DataFrame, det: Detector, windows_min: list[int], baseline_hours: int,
                       s: Settings) -> list[AggregatePacket]:
    """units: ts, segment, bad, session_id, converted, value."""
    packets: list[AggregatePacket] = []
    for segment, g in units.groupby("segment"):
        g = g.sort_values("ts")
        intervals: list[tuple[pd.Timestamp, pd.Timestamp]] = []
        for w in windows_min:
            freq = f"{w}min"
            n = g.set_index("ts")["bad"].resample(freq).size()
            bad = g.set_index("ts")["bad"].resample(freq).sum()
            bins = max(int(baseline_hours * 60 / w), 2)
            prior_n = n.shift(1).rolling(bins, min_periods=max(bins // 4, 1)).sum()
            prior_bad = bad.shift(1).rolling(bins, min_periods=max(bins // 4, 1)).sum()
            for ts in n.index[n > 0]:
                if not prior_n.get(ts, 0) or np.isnan(prior_n[ts]):
                    continue
                p0 = prior_bad[ts] / prior_n[ts]
                p = bad[ts] / n[ts]
                z = binomial_z(p, p0, n[ts])
                if is_flagged(bad[ts], z, p / max(p0, 1e-3), s):
                    intervals.append((ts, ts + pd.Timedelta(minutes=w)))
        for start, end in _merge_intervals(intervals):
            window = g[(g["ts"] >= start) & (g["ts"] < end)]
            prior = g[(g["ts"] < start) & (g["ts"] >= start - pd.Timedelta(hours=baseline_hours))]
            p0 = prior["bad"].mean() if len(prior) else g["bad"].mean()
            p = window["bad"].mean()
            z = binomial_z(p, p0, len(window))
            trend = "rising" if p >= 2 * p0 else "elevated"
            packets.append(_packet(det, str(segment), window, start.to_pydatetime(), end.to_pydatetime(), p0, z, trend))
    return packets


def cross_sectional_anomalies(units: pd.DataFrame, det: Detector, s: Settings) -> list[AggregatePacket]:
    """Compare each segment's bad-rate over the whole period with all other segments pooled."""
    packets: list[AggregatePacket] = []
    totals = units.groupby("segment")["bad"].agg(["size", "sum"])
    all_n, all_bad = totals["size"].sum(), totals["sum"].sum()
    for segment, row in totals.iterrows():
        other_n, other_bad = all_n - row["size"], all_bad - row["sum"]
        if other_n == 0:
            continue
        p0 = other_bad / other_n
        p = row["sum"] / row["size"]
        z = binomial_z(p, p0, row["size"])
        if is_flagged(row["sum"], z, p / max(p0, 1e-3), s):
            g = units[units["segment"] == segment]
            packets.append(_packet(det, str(segment), g, g["ts"].min().to_pydatetime(),
                                   g["ts"].max().to_pydatetime(), p0, z, "persistent"))
    return packets


# --- unit builders (one row per session/order with a `bad` flag) --------------------

def gateway_units(payments: pd.DataFrame, sessions: pd.DataFrame) -> pd.DataFrame:
    pay = payments.dropna(subset=["gateway"])
    per = pay.groupby(["session_id", "gateway"]).agg(ts=("timestamp", "min"),
                                                     bad=("status", lambda x: (x == "failed").any()))
    per = per.reset_index().rename(columns={"gateway": "segment"})
    return _with_session_outcome(per, sessions)


def courier_eta_units(events: pd.DataFrame, sessions: pd.DataFrame) -> pd.DataFrame:
    info = events[events["event"] == "delivery_info_view"]
    meta = pd.DataFrame(info["metadata"].tolist(), index=info.index)
    df = pd.DataFrame({"session_id": info["session_id"], "ts": info["timestamp"],
                       "courier": meta.get("courier"), "eta": pd.to_numeric(meta.get("eta_days"), errors="coerce")})
    df = df.dropna(subset=["courier", "eta"]).groupby("session_id").agg(ts=("ts", "min"), courier=("courier", "last"),
                                                                       eta=("eta", "max")).reset_index()
    df = df.merge(sessions[["session_id", "city"]], on="session_id")
    df["segment"] = df["courier"] + "|" + df["city"]
    typical = df.groupby("segment")["eta"].transform("median")
    df["bad"] = df["eta"] >= typical + 3
    return _with_session_outcome(df[["session_id", "ts", "segment", "bad"]], sessions)


def courier_delay_units(orders: pd.DataFrame, events: pd.DataFrame) -> pd.DataFrame:
    """One unit per order, timed at placement. The affected session is the customer's
    post-purchase visit about that order when there is one, else the ordering session."""
    visits = events[events["page"].isin(["order_tracking", "returns"])].dropna(subset=["order_id"])
    first_visit = visits.drop_duplicates("order_id").set_index("order_id")["session_id"].to_dict()
    df = pd.DataFrame({
        "session_id": [first_visit.get(o, s) for o, s in zip(orders["order_id"], orders["session_id"])],
        "ts": pd.to_datetime(orders["placed_at"]),
        "segment": orders["courier"] + "|" + orders["city"], "bad": orders["delay_days"] >= 2,
        "converted": False, "value": orders["order_value"].astype(float),
    })
    return df


def product_size_units(events: pd.DataFrame, sessions: pd.DataFrame) -> pd.DataFrame:
    opens = events[events["event"] == "size_chart_open"].dropna(subset=["product_id"])
    adds = events[events["event"] == "add_to_cart"].dropna(subset=["product_id"])
    added = set(zip(adds["session_id"], adds["product_id"]))
    per = opens.groupby(["session_id", "product_id"]).agg(ts=("timestamp", "min")).reset_index()
    per["bad"] = [(s, p) not in added for s, p in zip(per["session_id"], per["product_id"])]
    per = per.rename(columns={"product_id": "segment"})
    return _with_session_outcome(per, sessions)


def product_feedback_units(events: pd.DataFrame, reviews: pd.DataFrame, sessions: pd.DataFrame) -> pd.DataFrame:
    """One unit per review or return; bad = rating <= 2 or a return because the item differed from the listing."""
    rev = pd.DataFrame({"session_id": reviews["session_id"], "ts": reviews["created_at"],
                        "segment": reviews["product_id"], "bad": reviews["rating"] <= 2})
    returns = events[events["event"] == "return_initiated"].dropna(subset=["product_id"])
    reasons = returns["metadata"].map(lambda m: m.get("reason"))
    ret = pd.DataFrame({"session_id": returns["session_id"], "ts": returns["timestamp"],
                        "segment": returns["product_id"],
                        "bad": reasons.isin(["not_as_described", "size_mismatch", "colour_different"])})
    return _with_session_outcome(pd.concat([rev, ret], ignore_index=True), sessions)


def device_error_units(events: pd.DataFrame, sessions: pd.DataFrame) -> pd.DataFrame:
    errors = set(events.loc[events["event"].isin(["js_error"]), "session_id"])
    df = sessions[["session_id", "start", "device", "app_version"]].rename(columns={"start": "ts"}).copy()
    df["segment"] = df["device"] + np.where(df["app_version"].notna(), " " + df["app_version"].fillna(""), "")
    df["bad"] = df["session_id"].isin(errors)
    return _with_session_outcome(df[["session_id", "ts", "segment", "bad"]], sessions)


def _with_session_outcome(units: pd.DataFrame, sessions: pd.DataFrame) -> pd.DataFrame:
    out = units.merge(sessions[["session_id", "converted", "cart_value"]], on="session_id", how="left")
    out["converted"] = out["converted"].fillna(False).astype(bool)
    out["value"] = out["cart_value"].fillna(0.0).astype(float)
    out["ts"] = pd.to_datetime(out["ts"])
    out["bad"] = out["bad"].astype(bool)
    return out.drop(columns=["cart_value"])


# --- entrypoint -----------------------------------------------------------------------

def detect_anomalies(sessions: pd.DataFrame, events: pd.DataFrame, payments: pd.DataFrame,
                     orders: pd.DataFrame, reviews: pd.DataFrame | None = None,
                     settings: Settings | None = None) -> list[AggregatePacket]:
    s = settings or get_settings()
    daily = s.anomaly_daily_baseline_days * 24
    packets = [
        *temporal_anomalies(gateway_units(payments, sessions), GATEWAY, s.anomaly_window_minutes,
                            s.anomaly_baseline_hours, s),
        *temporal_anomalies(courier_eta_units(events, sessions), COURIER_ETA, [1440], daily, s),
        *temporal_anomalies(courier_delay_units(orders[pd.to_datetime(orders["placed_at"]) >= sessions["start"].min()],
                                            events), COURIER_DELAY, [1440], daily, s),
        *cross_sectional_anomalies(product_size_units(events, sessions), PRODUCT_SIZE, s),
        *cross_sectional_anomalies(device_error_units(events, sessions), DEVICE_ERRORS, s),
    ]
    if reviews is not None:
        packets += cross_sectional_anomalies(product_feedback_units(events, reviews, sessions), PRODUCT_FEEDBACK, s)
    return sorted(packets, key=lambda p: (-p.z_score, p.packet_id))


def match_incidents(packets: list[AggregatePacket], incidents: pd.DataFrame) -> dict[str, list[str]]:
    """Planted incident id -> ids of packets that detect it (same scope, overlapping time)."""
    import json

    matches: dict[str, list[str]] = {}
    for inc in incidents.itertuples():
        scope = json.loads(inc.scope)
        hits: list[str] = []
        for p in packets:
            overlaps = p.window_start < pd.Timestamp(inc.end) and p.window_end > pd.Timestamp(inc.start)
            if inc.kind == "gateway_outage":
                ok = p.segment_type == "gateway" and p.segment_value == scope["gateway"] and overlaps
            elif inc.kind == "courier_delay":
                courier, _, city = p.segment_value.partition("|")
                ok = (p.segment_type == "courier_city" and courier == scope["courier"]
                      and city in scope["cities"] and overlaps)
            else:
                ok = p.segment_type == "product" and p.segment_value in scope["product_ids"]
            if ok:
                hits.append(p.packet_id)
        matches[inc.incident_id] = hits
    return matches


def main() -> int:
    from backend.app.store import get_store

    store = get_store()
    packets = detect_anomalies(store.sessions, store.events, store.payments, store.orders, store.reviews)
    print(f"{len(packets)} aggregate anomalies:")
    for p in packets:
        print(f"  z={p.z_score:>6.1f} x{p.multiplier:<5} {p.segment_type:<13}{p.segment_value:<24}"
              f"{p.metric:<28}{p.window_start:%m-%d %H:%M} affected={p.affected_sessions}")
    print("\nPlanted incidents:")
    for inc, hits in match_incidents(packets, store.incidents).items():
        print(f"  {inc:<24} {'DETECTED' if hits else 'missed'}  ({len(hits)} packets)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
