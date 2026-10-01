"""Phase 2: cleaning, sessionization, features, prefixes and joins."""
from __future__ import annotations

import json
from datetime import datetime, timedelta

import pandas as pd

from backend.app.ingestion.features import (
    FEATURE_COLUMNS, compute_features, features_for_events, fit_dwell_baselines, prefix_cuts,
)
from backend.app.ingestion.sessionize import clean_events, sessionize

T0 = datetime(2026, 9, 20, 10, 0, 0)


def ev(sec: int, event: str, page: str, product_id: str | None = None, **metadata) -> dict:
    return {"timestamp": T0 + timedelta(seconds=sec), "event": event, "page": page,
            "product_id": product_id, "order_id": None, "metadata": metadata}


def raw_frame(rows: list[dict], session_id: str = "s_1", user_id: str = "u_abc") -> pd.DataFrame:
    return pd.DataFrame([{**r, "session_id": r.get("session_id", session_id), "user_id": user_id,
                          "metadata": json.dumps(r["metadata"])} for r in rows])


def test_clean_drops_duplicates_invalid_rows_and_sensitive_keys() -> None:
    rows = [ev(0, "page_view", "home", device="mobile_web"),
            ev(5, "payment_attempt", "checkout_payment", method="UPI", otp="123456", card_number="4111")]
    rows.append(dict(rows[1]))                                   # exact duplicate
    rows.append(ev(9, "teleport", "home"))                       # unknown event
    clean = clean_events(raw_frame(rows))
    assert len(clean) == 2
    assert clean.iloc[1]["metadata"] == {"method": "UPI"}
    assert clean["product_id"].tolist() == [None, None]


def test_sessionize_splits_on_inactivity_and_id_change() -> None:
    rows = [ev(0, "page_view", "home"), ev(60, "search", "search"),
            ev(60 + 31 * 60, "page_view", "home"),              # 31 min later, same tracker id
            {**ev(60 + 32 * 60, "page_view", "home"), "session_id": "s_2"}]
    out = sessionize(clean_events(raw_frame(rows)), gap_minutes=30)
    assert out["session_id"].tolist() == ["s_1", "s_1", "s_1_2", "s_2"]


def test_features_capture_loops_retries_and_exit_context() -> None:
    events = [
        ev(0, "page_view", "home", device="android_app", city_tier="tier_2", source="email", is_logged_in=True),
        ev(10, "product_view", "product", "p_1", in_stock=True),
        ev(40, "product_view", "product", "p_2", in_stock=True),
        ev(70, "product_view", "product", "p_1", in_stock=True),
        ev(80, "size_chart_open", "product", "p_1", available=False),
        ev(90, "add_to_cart", "product", "p_1", cart_value=1999),
        ev(100, "checkout_start", "cart"),
        ev(110, "total_shown", "checkout_summary", delta_pct=12.5, handling_fee=99, total=2250),
        ev(120, "cart_view", "cart"),
        ev(130, "payment_attempt", "checkout_payment", method="UPI", gateway="B"),
        ev(160, "payment_failed", "checkout_payment", method="UPI", error="timeout"),
        ev(170, "payment_attempt", "checkout_payment", method="card", gateway="B"),
        ev(175, "payment_failed", "checkout_payment", method="card", error="card_declined"),
        ev(400, "exit", "checkout_payment"),
    ]
    f = compute_features(events)
    assert f["pdp_loops"] == 1 and f["unique_products"] == 2
    assert f["checkout_cart_loops"] == 1
    assert f["payment_failures"] == 2 and f["method_switches"] == 1 and f["payment_timeouts"] == 1
    assert f["size_chart_unavailable"] == 1
    assert f["max_extra_fees"] == 99 and f["max_total_delta_pct"] == 12.5
    assert f["exit_after_payment_failure"] == 1 and f["exit_dwell_s"] == 225
    assert f["cart_value"] == 1999 and f["n_events"] == 13
    assert f["is_android_app"] == 1 and f["city_tier_num"] == 2 and f["logged_in_at_start"] == 1
    assert f["dwell_payment_s"] == 270  # 130->400 on the payment page, exit dwell included


def test_prefix_cuts_never_include_the_outcome() -> None:
    events = [ev(0, "page_view", "home"), ev(10, "product_view", "product", "p_1"),
              ev(20, "add_to_cart", "product", "p_1"), ev(30, "cart_view", "cart"),
              ev(40, "payment_attempt", "checkout_payment"), ev(45, "payment_success", "checkout_payment"),
              ev(50, "order_placed", "checkout_payment"), ev(60, "page_view", "order_confirmation")]
    cuts = prefix_cuts(events, max_prefixes=8)
    assert cuts == [1, 3, 4, 5]
    assert all(e["event"] not in ("payment_success", "order_placed") for e in events[: max(cuts)])


def test_prefix_cuts_ignore_exit_beacon() -> None:
    events = [ev(0, "page_view", "home"), ev(10, "product_view", "product", "p_1"), ev(300, "exit", "product")]
    assert prefix_cuts(events, max_prefixes=8) == [1, 2]


def test_live_feature_vector_has_all_columns() -> None:
    baselines = {s: {"mean": 3.0, "std": 1.0} for s in
                 ["browse", "product", "cart", "checkout", "payment", "order", "post_purchase"]}
    vec = features_for_events([ev(0, "page_view", "home"), ev(500, "product_view", "product", "p_1")], baselines)
    assert set(FEATURE_COLUMNS) <= set(vec)
    assert vec["dwell_z_browse"] > 0


def test_pipeline_recovers_planted_sessions(small_raw, small_processed) -> None:
    gt = small_raw["ground_truth"].set_index("session_id")
    sessions = small_processed["sessions"].set_index("session_id")
    assert set(sessions.index) == set(gt.index)
    joined = sessions.join(gt, rsuffix="_gt")
    for col in ("session_kind", "converted", "reached_cart", "exit_step", "furthest_step"):
        assert (joined[col] == joined[f"{col}_gt"]).all(), col


def test_feature_and_prefix_tables(small_processed) -> None:
    features, prefixes = small_processed["features"], small_processed["prefixes"]
    assert len(features) == len(small_processed["sessions"])
    assert set(FEATURE_COLUMNS) <= set(features.columns)
    assert not features[FEATURE_COLUMNS].isna().any().any()
    assert prefixes.groupby("session_id").size().max() <= 8
    assert prefixes.groupby("session_id")["is_final"].sum().eq(1).all()
    assert (small_processed["root"] / "models" / "dwell_baselines.json").exists()


def test_joins_link_payments_orders_and_feedback(small_raw, small_processed) -> None:
    features = small_processed["features"].set_index("session_id")
    gt = small_raw["ground_truth"]
    deducted = gt.loc[gt["primary_variant"] == "money_deducted", "session_id"]
    assert (features.loc[deducted, "failed_debited_payments"] > 0).all()
    ticket_sessions = small_raw["tickets"]["session_id"].unique()
    assert (features.loc[ticket_sessions, "n_tickets"] > 0).all()


def test_dwell_baselines_fit() -> None:
    frame = pd.DataFrame({f"dwell_{s}_s": [10.0, 20.0, 0.0] for s in
                          ["browse", "product", "cart", "checkout", "payment", "order", "post_purchase"]})
    baselines = fit_dwell_baselines(frame)
    assert baselines["browse"]["std"] > 0
