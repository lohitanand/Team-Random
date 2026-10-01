"""Phase 3: rules fire on planted sessions; planted incidents are detected."""
from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd
import pytest

from backend.app.config import Settings
from backend.app.detection.anomaly import (
    GATEWAY, PRODUCT_SIZE, cross_sectional_anomalies, detect_anomalies, match_incidents, temporal_anomalies,
)
from backend.app.detection.rules import RULE_FRICTION, RULES, evaluate_rules, rule_frictions
from backend.app.schemas.taxonomy import FRICTION_TYPES

SETTINGS = Settings(_env_file=None)


# --- rules -------------------------------------------------------------------------

def test_every_friction_has_rules_and_names_are_unique() -> None:
    assert len({r.name for r in RULES}) == len(RULES)
    assert set(RULE_FRICTION.values()) == set(FRICTION_TYPES)


def test_rules_on_hand_built_features() -> None:
    features = {"payment_failures": 2, "coupon_failures": 1, "otp_resends": 3, "exit_after_total_shown": 1}
    flags = evaluate_rules(features)
    assert flags == ["payment_retry_x2", "otp_resend_x2", "exit_after_total_shown"]
    assert rule_frictions(flags) == ["payment_failure", "login_otp_issue", "price_shock"]
    assert evaluate_rules({}) == []


def test_single_retries_do_not_fire() -> None:
    noise = {"payment_failures": 1, "coupon_failures": 1, "otp_resends": 1, "rage_clicks": 1, "size_chart_opens": 1}
    assert evaluate_rules(noise) == []


@pytest.fixture(scope="module")
def rule_hits(full_processed):
    store = full_processed["store"]
    features = store.features.set_index("session_id")
    hits = {sid: set(rule_frictions(evaluate_rules(row))) for sid, row in features.to_dict("index").items()}
    return store.ground_truth.set_index("session_id"), hits


def test_rules_fire_on_planted_sessions(rule_hits) -> None:
    gt, hits = rule_hits
    for friction in FRICTION_TYPES:
        planted = gt.index[gt["friction_types"].str.split("|").map(lambda xs, f=friction: f in xs)]
        recall = sum(friction in hits[s] for s in planted) / len(planted)
        assert recall >= 0.6, (friction, recall)


def test_rules_rarely_fire_on_clean_sessions(rule_hits) -> None:
    gt, hits = rule_hits
    clean = gt.index[gt["is_clean"]]
    assert sum(bool(hits[s]) for s in clean) / len(clean) < 0.15


# --- anomaly statistics ---------------------------------------------------------------

def _units(bad_rate_by_hour: dict[int, float], n_per_hour: int = 40, segment: str = "B") -> pd.DataFrame:
    rows = []
    start = datetime(2026, 9, 14)
    for hour in range(96):
        rate = bad_rate_by_hour.get(hour, 0.1)
        for i in range(n_per_hour):
            rows.append({"session_id": f"s_{hour}_{i}", "ts": start + timedelta(hours=hour, minutes=i),
                         "segment": segment, "bad": i < rate * n_per_hour, "converted": False, "value": 1000.0})
    return pd.DataFrame(rows)


def test_temporal_spike_is_flagged_once() -> None:
    packets = temporal_anomalies(_units({70: 0.8, 71: 0.8}), GATEWAY, [30, 60], 48, SETTINGS)
    assert len(packets) == 1
    p = packets[0]
    assert p.window_start <= datetime(2026, 9, 16, 22) < p.window_end
    assert p.multiplier >= SETTINGS.anomaly_rate_multiplier and p.affected_sessions >= 50
    assert p.friction_hint == "payment_failure" and p.revenue_at_risk > 0


def test_flat_series_is_not_flagged() -> None:
    assert temporal_anomalies(_units({}), GATEWAY, [15, 30, 60], 48, SETTINGS) == []


def test_cross_sectional_outlier() -> None:
    normal = pd.concat([_units({}, 5, segment=f"p_{i}") for i in range(10)])
    outlier = _units({h: 0.8 for h in range(96)}, 5, segment="p_bad")
    packets = cross_sectional_anomalies(pd.concat([normal, outlier]), PRODUCT_SIZE, SETTINGS)
    assert [p.segment_value for p in packets] == ["p_bad"]


# --- planted incidents on the full dataset ----------------------------------------------

def test_planted_incidents_detected(full_processed) -> None:
    store = full_processed["store"]
    packets = detect_anomalies(store.sessions, store.events, store.payments, store.orders, store.reviews, SETTINGS)
    matches = match_incidents(packets, store.incidents)
    assert all(matches.values()), matches

    courier_cities = {p.segment_value.split("|")[1] for p in packets
                      if p.packet_id in matches["INC_COURIERX_DAY5_7"]}
    assert len(courier_cities) >= 2
    missing_products = {p.segment_value for p in packets if p.packet_id in matches["INC_MISSING_SIZE_12"]}
    assert len(missing_products) >= 4

    matched = {pid for ids in matches.values() for pid in ids}
    unmatched = [p for p in packets if p.packet_id not in matched and p.segment_type != "device"]
    assert len(unmatched) <= 4, [p.packet_id for p in unmatched]
