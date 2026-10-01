"""Session features (CLAUDE.md §7.3), computed from an ordered list of events.

The same function scores full sessions, training prefixes and live sessions from the tracker.
"""
from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from typing import Any

import numpy as np
import pandas as pd

from backend.app.schemas.events import PAGE_TO_STEP
from backend.app.schemas.taxonomy import FUNNEL_STEPS

Event = dict[str, Any]  # keys: timestamp, event, page, product_id, order_id, metadata

DWELL_STEPS = list(FUNNEL_STEPS)
CHECKOUT_PAGES = {"checkout_login", "checkout_address", "checkout_delivery", "checkout_summary", "checkout_payment"}
DEVICE_CODES = {"mobile_web": 0, "android_app": 1, "ios_app": 2, "desktop": 3}
SOURCE_CODES = {"direct": 0, "organic_search": 1, "paid_ads": 2, "social": 3, "email": 4, "push": 5}
STANDARD_TOTAL_KEYS = {"subtotal", "shipping", "platform_fee", "cod_fee", "discount", "total", "delta_pct",
                       "payment_method"}

# What the customer was doing right before leaving (or right now, for live prefixes).
LAST_EVENT_GROUPS = {
    "total_shown": "exit_after_total_shown",
    "payment_failed": "exit_after_payment_failure",
    "delivery_info_view": "exit_after_delivery_info",
    "pincode_check": "exit_after_delivery_info",
    "login_wall": "exit_after_login",
    "otp_sent": "exit_after_login",
    "otp_resend": "exit_after_login",
    "otp_failed": "exit_after_login",
    "coupon_failed": "exit_after_coupon_failure",
    "size_chart_open": "exit_after_product_info",
    "spec_open": "exit_after_product_info",
    "review_open": "exit_after_product_info",
    "size_unavailable_click": "exit_after_oos",
    "notify_me": "exit_after_oos",
    "remove_from_cart": "exit_after_oos",
    "js_error": "exit_after_error",
    "slow_load": "exit_after_error",
    "rage_click": "exit_after_error",
    "dead_click": "exit_after_error",
    "search": "exit_after_search",
    "search_zero_results": "exit_after_search",
    "rec_impression": "exit_after_recs",
    "tracking_view": "exit_after_tracking",
    "help_view": "exit_after_tracking",
}
EXIT_AFTER_COLUMNS = sorted(set(LAST_EVENT_GROUPS.values()))

COUNTED_EVENTS = {
    "product_views": "product_view", "size_chart_opens": "size_chart_open", "spec_opens": "spec_open",
    "review_opens": "review_open", "pincode_checks": "pincode_check", "delivery_info_views": "delivery_info_view",
    "searches": "search", "zero_result_searches": "search_zero_results", "rec_impressions": "rec_impression",
    "rec_clicks": "rec_click", "payment_attempts": "payment_attempt", "payment_failures": "payment_failed",
    "coupon_attempts": "coupon_apply", "coupon_failures": "coupon_failed", "coupons_applied": "coupon_applied",
    "login_walls": "login_wall", "otp_sends": "otp_sent", "otp_resends": "otp_resend", "otp_failures": "otp_failed",
    "login_successes": "login_success", "rage_clicks": "rage_click", "dead_clicks": "dead_click",
    "js_errors": "js_error", "slow_loads": "slow_load", "size_unavailable_clicks": "size_unavailable_click",
    "notify_me": "notify_me", "cart_removals": "remove_from_cart", "add_to_carts": "add_to_cart",
    "total_shown_count": "total_shown", "chat_opens": "chat_open", "help_views": "help_view",
    "tracking_views": "tracking_view", "returns_initiated": "return_initiated", "orders_cancelled": "order_cancelled",
    "checkout_starts": "checkout_start",
}

BEHAVIOUR_COLUMNS = [
    "n_events", "duration_s", "max_gap_s", "exit_dwell_s",
    *[f"dwell_{s}_s" for s in DWELL_STEPS],
    "furthest_step_idx", "current_step_idx",
    *COUNTED_EVENTS,
    "unique_products", "pdp_loops", "checkout_cart_loops", "size_chart_unavailable", "max_review_page",
    "max_eta_days", "max_delivery_fee", "fee_first_shown", "oos_product_views",
    "method_switches", "payment_timeouts", "rage_clicks_checkout", "max_load_ms", "fatal_errors", "oos_removals",
    "cart_value", "max_total_delta_pct", "max_extra_fees", "cod_selected",
    "refund_pending_views", "delayed_status_views", "max_last_update_hours",
    "info_mismatch_returns", "quality_returns",
    *EXIT_AFTER_COLUMNS,
]
INFO_RETURN_REASONS = {"not_as_described", "size_mismatch", "colour_different"}
QUALITY_RETURN_REASONS = {"damaged", "defective", "poor_quality"}
CONTEXT_COLUMNS = ["device_code", "is_android_app", "city_tier_num", "source_code", "logged_in_at_start",
                   "hour", "is_weekend", "is_post_purchase"]
Z_COLUMNS = [f"dwell_z_{s}" for s in DWELL_STEPS] + ["max_dwell_z"]
FEATURE_COLUMNS = BEHAVIOUR_COLUMNS + CONTEXT_COLUMNS + Z_COLUMNS


def _step_idx(step: str) -> int:
    return FUNNEL_STEPS.index(step)


def compute_features(events: Sequence[Event]) -> dict[str, float]:
    """Features for one session (or session prefix). `events` must be time-ordered."""
    f: dict[str, float] = {c: 0.0 for c in BEHAVIOUR_COLUMNS + CONTEXT_COLUMNS}
    if not events:
        return f
    body = [e for e in events if e["event"] != "exit"] or list(events[:1])
    times = [pd.Timestamp(e["timestamp"]) for e in events]
    deltas = [(b - a).total_seconds() for a, b in zip(times, times[1:])]

    f["n_events"] = len(body)
    f["duration_s"] = (times[-1] - times[0]).total_seconds()
    f["max_gap_s"] = max(deltas, default=0.0)
    if events[-1]["event"] == "exit" and len(events) > 1:
        f["exit_dwell_s"] = (times[-1] - pd.Timestamp(body[-1]["timestamp"])).total_seconds()
    for e, d in zip(events, deltas):
        f[f"dwell_{PAGE_TO_STEP[e['page']]}_s"] += d

    steps = [PAGE_TO_STEP[e["page"]] for e in body]
    f["furthest_step_idx"] = max(_step_idx(s) for s in steps)
    f["current_step_idx"] = _step_idx(steps[-1])

    names = [e["event"] for e in body]
    for column, name in COUNTED_EVENTS.items():
        f[column] = float(names.count(name))

    products = [e["product_id"] for e in body if e["event"] == "product_view" and isinstance(e.get("product_id"), str)]
    f["unique_products"] = len(set(products))
    f["pdp_loops"] = sum(1 for i in range(2, len(products)) if products[i] == products[i - 2] != products[i - 1])
    pages = [e["page"] for e in body]
    f["checkout_cart_loops"] = sum(1 for a, b in zip(pages, pages[1:]) if a in CHECKOUT_PAGES and b == "cart")

    methods: list[str] = []
    for e in body:
        name, m = e["event"], e.get("metadata") or {}
        if name == "size_chart_open" and m.get("available") is False:
            f["size_chart_unavailable"] += 1
        elif name == "review_open":
            f["max_review_page"] = max(f["max_review_page"], float(m.get("review_page", 1)))
        elif name in ("pincode_check", "delivery_info_view"):
            f["max_eta_days"] = max(f["max_eta_days"], float(m.get("eta_days", 0)))
            f["max_delivery_fee"] = max(f["max_delivery_fee"], float(m.get("delivery_fee", 0)))
            f["fee_first_shown"] = max(f["fee_first_shown"], float(bool(m.get("fee_first_shown"))))
        elif name == "product_view" and m.get("in_stock") is False:
            f["oos_product_views"] += 1
        elif name == "payment_attempt":
            methods.append(str(m.get("method")))
        elif name == "payment_failed" and "timeout" in str(m.get("error", "")):
            f["payment_timeouts"] += 1
        elif name == "rage_click" and e["page"] in CHECKOUT_PAGES:
            f["rage_clicks_checkout"] += 1
        elif name == "slow_load":
            f["max_load_ms"] = max(f["max_load_ms"], float(m.get("load_ms", 0)))
        elif name == "js_error" and m.get("fatal"):
            f["fatal_errors"] += 1
        elif name == "remove_from_cart" and m.get("reason") == "out_of_stock":
            f["oos_removals"] += 1
        elif name == "total_shown":
            f["max_total_delta_pct"] = max(f["max_total_delta_pct"], float(m.get("delta_pct", 0)))
            extra = sum(float(v) for k, v in m.items() if k not in STANDARD_TOTAL_KEYS and isinstance(v, (int, float)))
            f["max_extra_fees"] = max(f["max_extra_fees"], extra)
            f["cod_selected"] = max(f["cod_selected"], float(m.get("payment_method") == "COD"))
        elif name == "tracking_view":
            f["refund_pending_views"] += float(m.get("refund_status") == "pending")
            f["delayed_status_views"] += float(m.get("status") == "delayed")
            f["max_last_update_hours"] = max(f["max_last_update_hours"], float(m.get("last_update_hours", 0)))
        elif name == "return_initiated":
            f["info_mismatch_returns"] += float(m.get("reason") in INFO_RETURN_REASONS)
            f["quality_returns"] += float(m.get("reason") in QUALITY_RETURN_REASONS)
        if "cart_value" in m:
            f["cart_value"] = max(f["cart_value"], float(m["cart_value"]))
    f["method_switches"] = sum(1 for a, b in zip(methods, methods[1:]) if a != b)

    group = LAST_EVENT_GROUPS.get(body[-1]["event"])
    if group:
        f[group] = 1.0

    context = (events[0].get("metadata") or {}) if events[0]["event"] == "page_view" else {}
    f["device_code"] = DEVICE_CODES.get(context.get("device"), -1)
    f["is_android_app"] = float(context.get("device") == "android_app")
    f["city_tier_num"] = {"tier_1": 1, "tier_2": 2, "tier_3": 3}.get(context.get("city_tier"), 0)
    f["source_code"] = SOURCE_CODES.get(context.get("source"), -1)
    f["logged_in_at_start"] = float(bool(context.get("is_logged_in")))
    f["hour"] = times[0].hour
    f["is_weekend"] = float(times[0].dayofweek >= 5)
    f["is_post_purchase"] = float(any(p in ("order_tracking", "returns") for p in pages)
                                  and "add_to_cart" not in names and "checkout_start" not in names)
    return f


OUTCOME_EVENTS = {"payment_success", "order_placed"}


def live_view(events: Sequence[Event]) -> list[Event]:
    """What a live scorer can know: no `exit` beacon, nothing from the successful payment onward."""
    body = [e for e in events if e["event"] != "exit"]
    end = next((i for i, e in enumerate(body) if e["event"] in OUTCOME_EVENTS), len(body))
    return body[:end]


def prefix_cuts(events: Sequence[Event], max_prefixes: int) -> list[int]:
    """Prefix lengths (into live_view(events)) ending where the funnel step changes.

    Prefixes never contain the outcome (payment_success / order_placed) or the exit beacon,
    so the risk model cannot learn the answer from the prefix itself.
    """
    usable = live_view(events)
    if not usable:
        return []
    cuts = [i for i in range(1, len(usable))
            if PAGE_TO_STEP[usable[i]["page"]] != PAGE_TO_STEP[usable[i - 1]["page"]]]
    cuts.append(len(usable))
    return sorted(set(cuts))[-max_prefixes:]


# --- dwell z-scores ------------------------------------------------------------

def fit_dwell_baselines(features: pd.DataFrame) -> dict[str, dict[str, float]]:
    baselines: dict[str, dict[str, float]] = {}
    for step in DWELL_STEPS:
        values = np.log1p(features.loc[features[f"dwell_{step}_s"] > 0, f"dwell_{step}_s"])
        baselines[step] = {"mean": float(values.mean()) if len(values) else 0.0,
                           "std": float(values.std()) if len(values) > 1 else 1.0}
    return baselines


def add_dwell_z(features: pd.DataFrame, baselines: dict[str, dict[str, float]]) -> pd.DataFrame:
    out = features.copy()
    for step in DWELL_STEPS:
        b = baselines[step]
        dwell = out[f"dwell_{step}_s"]
        z = (np.log1p(dwell) - b["mean"]) / max(b["std"], 1e-6)
        out[f"dwell_z_{step}"] = np.where(dwell > 0, z, 0.0)
    out["max_dwell_z"] = out[[f"dwell_z_{s}" for s in DWELL_STEPS]].max(axis=1)
    return out


def features_for_events(events: Sequence[Event], baselines: dict[str, dict[str, float]]) -> dict[str, float]:
    """Full feature vector (incl. dwell z-scores) for one live or historical session."""
    row = pd.DataFrame([compute_features(events)])
    return add_dwell_z(row, baselines).iloc[0].to_dict()


def session_event_lists(events: pd.DataFrame) -> Iterable[tuple[str, list[Event]]]:
    """Yield (session_id, events) from a frame sorted by session_id then timestamp."""
    cols = ["timestamp", "event", "page", "product_id", "order_id", "metadata"]
    records = events[cols].to_dict("records")
    sids = events["session_id"].to_numpy()
    start = 0
    for i in range(1, len(sids) + 1):
        if i == len(sids) or sids[i] != sids[start]:
            yield str(sids[start]), records[start:i]
            start = i


def build_feature_tables(events: pd.DataFrame, max_prefixes: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return (session features, prefix features) without dwell z-scores."""
    full_rows: list[dict[str, Any]] = []
    prefix_rows: list[dict[str, Any]] = []
    for sid, evs in session_event_lists(events):
        full_rows.append({"session_id": sid, **compute_features(evs)})
        live = live_view(evs)
        cuts = prefix_cuts(evs, max_prefixes)
        for k, cut in enumerate(cuts):
            prefix_rows.append({
                "session_id": sid, "prefix_len": cut, "prefix_end": live[cut - 1]["timestamp"],
                "is_final": k == len(cuts) - 1, **compute_features(live[:cut]),
            })
    return pd.DataFrame(full_rows), pd.DataFrame(prefix_rows)


def safe_float(value: Any) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return 0.0
    return 0.0 if math.isnan(out) else out
