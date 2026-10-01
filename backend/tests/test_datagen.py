"""Phase 1: synthetic data generator."""
from __future__ import annotations

import json
import re

import numpy as np
import pandas as pd
import pytest

from backend.app.config import Settings
from backend.app.schemas.events import FORBIDDEN_METADATA_KEYS, Event
from backend.app.schemas.taxonomy import FRICTION_TYPES, TEXT_THEMES
from datagen.config import load_config
from datagen.generate import TABLES, friction_rates, generate, plan_frictions, write_tables
from datagen.scenarios import INCIDENT_VARIANTS, VARIANTS

@pytest.fixture(scope="module")
def cfg():
    """Full-size config: tests check the actual deliverable (about 15 s to generate)."""
    return load_config()


@pytest.fixture(scope="module")
def tables(full_raw):
    return full_raw


def _none(value):
    return None if value is None or (isinstance(value, float) and np.isnan(value)) else value


# --- config ---------------------------------------------------------------------

def test_config_variants_match_scenarios() -> None:
    cfg = load_config()
    for friction in FRICTION_TYPES:
        configured = set(cfg.friction.variants[friction])
        assert configured <= set(VARIANTS[friction]), friction
        assert set(VARIANTS[friction]) - configured <= INCIDENT_VARIANTS, friction
        assert len(configured) >= 4, f"{friction} needs several behaviour variants"


def test_planned_friction_rates_within_bounds() -> None:
    cfg = load_config()
    rng = np.random.default_rng(0)
    plans = [plan_frictions(cfg, rng) for _ in range(40_000)]
    low, high = cfg.friction.target_rate_bounds
    assert abs(np.mean([not p for p in plans]) - cfg.friction.clean_share) < 0.01
    assert abs(np.mean([len(p) == 2 for p in plans]) - cfg.friction.double_share) < 0.01
    for friction in FRICTION_TYPES:
        rate = np.mean([any(x.friction == friction for x in p) for p in plans])
        assert low <= rate <= high, (friction, rate)


# --- tables & ground truth ---------------------------------------------------------

def test_all_tables_written(tables, tmp_path) -> None:
    write_tables(tables, tmp_path)
    for name in TABLES:
        df = pd.read_parquet(tmp_path / f"{name}.parquet")
        assert len(df) > 0, name


def test_ground_truth_covers_every_session(tables, cfg) -> None:
    gt, events = tables["ground_truth"], tables["events"]
    assert len(gt) == cfg.sizes.sessions
    assert gt["session_id"].is_unique
    assert set(events["session_id"]) == set(gt["session_id"])
    assert {"friction_types", "abandoned", "incident_id"} <= set(gt.columns)


def test_realized_mix_matches_config(tables, cfg) -> None:
    gt = tables["ground_truth"]
    assert abs(gt["is_clean"].mean() - cfg.friction.clean_share) < 0.02
    assert abs((gt["n_frictions"] == 2).mean() - cfg.friction.double_share) < 0.02
    low, high = cfg.friction.target_rate_bounds
    for friction, rate in friction_rates(gt).items():
        assert low <= rate <= high, (friction, rate)


def test_every_configured_variant_appears(tables, cfg) -> None:
    gt = tables["ground_truth"]
    seen = set(zip(gt["primary_friction"], gt["primary_variant"])) | set(
        zip(gt["secondary_friction"], gt["secondary_variant"]))
    for friction, variants in cfg.friction.variants.items():
        for variant, weight in variants.items():
            if weight > 0:
                assert (friction, variant) in seen, (friction, variant)


def test_labels_are_consistent(tables) -> None:
    gt, events, orders = tables["ground_truth"], tables["events"], tables["orders"]
    assert (gt["abandoned"] == (gt["reached_cart"] & ~gt["converted"])).all()
    placed = set(events.loc[events["event"] == "order_placed", "session_id"])
    assert placed == set(gt.loc[gt["converted"], "session_id"])
    assert set(gt["order_id"].dropna()) <= set(orders["order_id"])
    clean = gt[gt["is_clean"]]
    assert clean["primary_friction"].isna().all() and (clean["n_frictions"] == 0).all()
    pp = gt[gt["session_kind"] == "post_purchase"]
    assert not pp["reached_cart"].any()
    assert (gt.loc[gt["n_frictions"] == 2, "secondary_friction"].notna()).all()


def test_symptoms_are_not_friction_types(tables) -> None:
    labels = set("|".join(tables["ground_truth"]["friction_types"]).split("|")) - {""}
    assert labels <= set(FRICTION_TYPES)


# --- planted incidents ---------------------------------------------------------

def test_gateway_outage_is_a_failure_spike(tables, cfg) -> None:
    go = cfg.incidents.gateway_outage
    pay = tables["payments"]
    failed_b = pay[(pay["gateway"] == go.gateway) & (pay["status"] == "failed")]
    ts = pd.to_datetime(failed_b["timestamp"])
    start = pd.Timestamp(cfg.start_date) + pd.Timedelta(days=go.day - 1, hours=go.start_hour)
    in_window = (ts >= start) & (ts < start + pd.Timedelta(hours=go.hours))
    window_rate = in_window.sum() / go.hours
    baseline_rate = (~in_window).sum() / (cfg.days * 24 - go.hours)
    assert window_rate >= Settings(_env_file=None).anomaly_rate_multiplier * baseline_rate

    labelled = tables["ground_truth"].query("incident_id == @go.id")
    assert len(labelled) > 0
    labelled_pay = pay[pay["session_id"].isin(labelled["session_id"]) & (pay["status"] == "failed")]
    assert set(labelled_pay["gateway"]) == {go.gateway}


def test_courier_delay_incident(tables, cfg) -> None:
    cd = cfg.incidents.courier_delay
    gt = tables["ground_truth"]
    labelled = gt[gt["incident_id"] == cd.id]
    assert len(labelled) > 0
    assert set(labelled["city"]) <= set(cd.cities)
    shopping = labelled[labelled["session_kind"] == "shopping"]
    days = (pd.to_datetime(shopping["session_start"]).dt.normalize() - pd.Timestamp(cfg.start_date)).dt.days + 1
    assert set(days) <= set(cd.days)
    orders = tables["orders"]
    in_scope = orders[(orders["courier"] == cd.courier) & orders["city"].isin(cd.cities)]
    placed_day = (pd.to_datetime(in_scope["placed_at"]).dt.normalize() - pd.Timestamp(cfg.start_date)).dt.days + 1
    assert (in_scope.loc[placed_day.isin(cd.days), "delay_days"] >= cd.order_delay_days[0]).all()


def test_missing_size_incident(tables, cfg) -> None:
    ms = cfg.incidents.missing_size_info
    products = tables["products"]
    missing = products[products["sizes"].map(json.loads).map(bool) & ~products["has_size_chart"]]
    assert len(missing) == ms.n_products
    labelled = tables["ground_truth"].query("incident_id == @ms.id")
    assert len(labelled) > 0
    ev = tables["events"]
    viewed = ev[ev["session_id"].isin(labelled["session_id"]) & ev["product_id"].isin(missing["product_id"])]
    assert set(viewed["session_id"]) | set(labelled.loc[labelled["session_kind"] == "post_purchase", "session_id"]) \
        == set(labelled["session_id"])


# --- determinism, privacy, text, raw-log noise ---------------------------------

def test_same_seed_same_data() -> None:
    small = load_config(overrides={"sizes": {"sessions": 500, "users": 80, "products": 80}})
    first, second = generate(small), generate(small)
    for name in ("events", "ground_truth", "payments", "tickets", "products"):
        pd.testing.assert_frame_equal(first[name], second[name])


def test_privacy(tables) -> None:
    for name in ("events", "payments", "orders", "tickets", "reviews", "chats", "ground_truth"):
        assert tables[name]["user_id"].str.fullmatch(r"u_[0-9a-f]{12}").all(), name
    keys = set().union(*tables["events"]["metadata"].map(lambda m: set(json.loads(m))))
    assert not keys & FORBIDDEN_METADATA_KEYS
    texts = pd.concat([tables["tickets"]["text"], tables["reviews"]["text"], tables["chats"]["transcript"]])
    pii = re.compile(r"[\w.]+@[\w.]+|\b\d{10}\b|\b\d{4}[ -]?\d{4}[ -]?\d{4}[ -]?\d{4}\b")
    assert not texts.str.contains(pii).any()


def test_events_match_schema(tables) -> None:
    sample = tables["events"].sample(3000, random_state=0)
    for row in sample.itertuples(index=False):
        Event(session_id=row.session_id, user_id=row.user_id, timestamp=row.timestamp, event=row.event,
              page=row.page, product_id=_none(row.product_id), order_id=_none(row.order_id),
              metadata=json.loads(row.metadata))


def test_text_variety(tables) -> None:
    texts = pd.concat([tables[t][["text" if t != "chats" else "customer_text", "theme_label", "language"]]
                      .set_axis(["text", "theme", "language"], axis=1) for t in ("tickets", "reviews", "chats")])
    assert set(texts["theme"]) == set(TEXT_THEMES)
    assert {"en", "hinglish"} <= set(texts["language"])
    assert texts["text"].nunique() / len(texts) > 0.6


def test_user_sessions_never_overlap(tables) -> None:
    gt = tables["ground_truth"].sort_values(["user_id", "session_start"])
    gap = gt.groupby("user_id")["session_start"].shift(-1) - gt["session_end"]
    assert gap.dropna().min() >= pd.Timedelta(minutes=30)


def test_raw_log_noise_present(tables) -> None:
    events = tables["events"]
    assert events.duplicated().sum() > 0
    missing_exit = 1 - events.loc[events["event"] == "exit", "session_id"].nunique() / events["session_id"].nunique()
    assert 0.05 < missing_exit < 0.15
